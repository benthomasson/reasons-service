"""LangChain tools for knowledge base access, scoped per project."""

import json
from uuid import UUID

from langchain_core.tools import tool
from sqlalchemy import select, text

from reasons_service.config import settings
from reasons_service.db.connection import get_sync_session
from reasons_service.db.models import Entry, Source, entry_sources
from reasons_service.db.search import plainto_fts_clause
from reasons_service.rms import api as rms_api

try:
    from reasons_service.db.models import Embedding
    from reasons_service.embeddings import embed_query
    _has_pgvector = Embedding is not None
except ImportError:
    _has_pgvector = False


def _extract_match_context(content: str, pattern: str, context_chars: int = 200) -> str:
    """Extract text around the first match of pattern in content."""
    lower_content = content.lower()
    lower_pattern = pattern.lower()
    idx = lower_content.find(lower_pattern)
    if idx == -1:
        return content[:context_chars] + "..."
    start = max(0, idx - context_chars // 2)
    end = min(len(content), idx + len(pattern) + context_chars // 2)
    snippet = content[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    return snippet


def make_tools(project_id: UUID) -> list:
    """Create tools scoped to a specific project. The LLM never sees the project UUID."""

    @tool
    def search_knowledge(query: str) -> str:
        """Search entries and beliefs by keyword. Returns matching entries with content snippets and matching beliefs with full text. Use read_entry to get full content of a specific entry."""
        with get_sync_session() as session:
            # Search entries via FTS
            where, _order, params = plainto_fts_clause(
                "coalesce(title, '') || ' ' || content", query
            )
            entry_rows = session.execute(
                text(
                    f"SELECT id, title, topic, content FROM entries "
                    f"WHERE project_id = :pid AND {where} "
                    f"LIMIT 5"
                ),
                {"pid": str(project_id), **params},
            ).all()

        # Search RMS beliefs (backend-dispatched)
        belief_hits = rms_api.search_beliefs_fts(project_id, query, 10)

        results = {
            "entries": [
                {
                    "id": r.id,
                    "topic": r.topic,
                    "snippet": r.content[:300] + "..." if len(r.content) > 300 else r.content,
                }
                for r in entry_rows
            ],
            "beliefs": [
                {"id": b["id"], "text": b["text"], "truth_value": b.get("truth_value", "IN")}
                for b in belief_hits
            ],
        }
        if not results["entries"] and not results["beliefs"]:
            return f"No results found for '{query}'. Try different keywords."
        return json.dumps(results, indent=2)

    @tool
    def read_entry(entry_id: str) -> str:
        """Read the full content of a specific entry by its ID. Use search_knowledge first to find entry IDs."""
        with get_sync_session() as session:
            entry = session.execute(
                select(Entry).where(
                    Entry.project_id == project_id, Entry.id == entry_id
                )
            ).scalar_one_or_none()

            if not entry:
                return f"Entry '{entry_id}' not found."

            # Get linked source slugs
            source_rows = session.execute(
                select(Source.slug, Source.url)
                .join(entry_sources, entry_sources.c.source_id == Source.id)
                .where(
                    entry_sources.c.entry_id == entry.id,
                    entry_sources.c.entry_project_id == project_id,
                )
            ).all()

        return json.dumps(
            {
                "id": entry.id,
                "topic": entry.topic,
                "title": entry.title,
                "content": entry.content,
                "sources": [{"slug": r.slug, "url": r.url} for r in source_rows],
            },
            indent=2,
        )

    @tool
    def list_entries(topic: str = "") -> str:
        """List available entries. Optionally filter by topic keyword. Returns IDs and titles (not full content)."""
        with get_sync_session() as session:
            q = select(Entry.id, Entry.topic, Entry.title).where(
                Entry.project_id == project_id
            )
            if topic:
                q = q.where(Entry.topic.ilike(f"%{topic}%"))
            rows = session.execute(q.order_by(Entry.topic).limit(50)).all()

        entries = [{"id": r.id, "topic": r.topic, "title": r.title} for r in rows]
        return json.dumps(entries, indent=2)

    @tool
    def list_beliefs(status: str = "IN") -> str:
        """List beliefs in the knowledge base. Filter by truth_value: IN (believed) or OUT (retracted)."""
        result = rms_api.list_nodes(project_id, status=status)
        nodes = result["nodes"][:50]
        total_note = f" (showing first 50)" if len(nodes) == 50 else ""
        return f"{result['count']} beliefs with truth_value={status}{total_note}:\n" + json.dumps(
            nodes, indent=2
        )

    @tool
    def read_source(slug: str) -> str:
        """Read a source document by its slug. Sources are the raw fetched documentation. Content is truncated to 8000 chars."""
        with get_sync_session() as session:
            source = session.execute(
                select(Source).where(
                    Source.project_id == project_id, Source.slug == slug
                )
            ).scalar_one_or_none()

        if not source:
            return f"Source '{slug}' not found."

        content = source.content
        truncated = ""
        if len(content) > 8000:
            content = content[:8000]
            truncated = "\n\n[Content truncated — original was longer]"

        return json.dumps(
            {
                "slug": source.slug,
                "url": source.url,
                "word_count": source.word_count,
                "content": content + truncated,
            },
            indent=2,
        )

    @tool
    def list_source_entries(source_slug: str) -> str:
        """List all entries derived from a specific source document. Use this to navigate from a source to its summaries/entries."""
        with get_sync_session() as session:
            source = session.execute(
                select(Source.id).where(
                    Source.project_id == project_id, Source.slug == source_slug
                )
            ).scalar_one_or_none()

            if not source:
                return f"Source '{source_slug}' not found."

            rows = session.execute(
                select(Entry.id, Entry.topic, Entry.title)
                .join(entry_sources, (entry_sources.c.entry_id == Entry.id) & (entry_sources.c.entry_project_id == Entry.project_id))
                .where(entry_sources.c.source_id == source)
                .order_by(Entry.topic)
            ).all()

        if not rows:
            return f"No entries linked to source '{source_slug}'."
        return json.dumps(
            [{"id": r.id, "topic": r.topic, "title": r.title} for r in rows],
            indent=2,
        )

    @tool
    def grep_content(pattern: str) -> str:
        """Exact text search (case-insensitive) across entries and sources. Use this when search_knowledge misses results due to word stemming, or to find exact terms, commands, filenames, or configuration values."""
        with get_sync_session() as session:
            like_pattern = f"%{pattern}%"

            # Search entries
            entry_rows = session.execute(
                select(Entry.id, Entry.topic, Entry.content)
                .where(
                    Entry.project_id == project_id,
                    Entry.content.ilike(like_pattern),
                )
                .limit(5)
            ).all()

            # Search sources
            source_rows = session.execute(
                select(Source.slug, Source.url, Source.content)
                .where(
                    Source.project_id == project_id,
                    Source.content.ilike(like_pattern),
                )
                .limit(5)
            ).all()

            # Search RMS beliefs (via rms_api for SQLite compatibility)
            belief_rows = []
            belief_search = rms_api.search(project_id, pattern)
            for b in belief_search.get("results", [])[:10]:
                if pattern.lower() in b.get("text", "").lower():
                    belief_rows.append(b)

        results = {
            "entries": [
                {
                    "id": r.id,
                    "topic": r.topic,
                    "snippet": _extract_match_context(r.content, pattern, 200),
                }
                for r in entry_rows
            ],
            "sources": [
                {
                    "slug": r.slug,
                    "url": r.url,
                    "snippet": _extract_match_context(r.content, pattern, 200),
                }
                for r in source_rows
            ],
            "beliefs": [
                {"id": b.get("id", b.get("node_id", "")), "text": b["text"],
                 "truth_value": b.get("truth_value", "IN")}
                for b in belief_rows
            ],
        }
        total = len(results["entries"]) + len(results["sources"]) + len(results["beliefs"])
        if total == 0:
            return f"No exact matches for '{pattern}'."
        return json.dumps(results, indent=2)

    if _has_pgvector and settings.db_backend == "postgresql":
        @tool
        def semantic_search(query: str) -> str:
            """Find conceptually related content using semantic similarity. Use this when search_knowledge returns no results, or when the question uses different phrasing than the source text."""
            query_vec = embed_query(query)
            with get_sync_session() as session:
                rows = session.execute(
                    text(
                        "SELECT source_table, source_id, label, "
                        "1 - (embedding <=> CAST(:qvec AS vector)) AS similarity "
                        "FROM embeddings "
                        "WHERE project_id = :pid "
                        "ORDER BY embedding <=> CAST(:qvec AS vector) "
                        "LIMIT 8"
                    ),
                    {"qvec": str(query_vec), "pid": str(project_id)},
                ).all()

            results = [
                {
                    "type": r.source_table,
                    "id": r.source_id,
                    "label": r.label,
                    "similarity": round(r.similarity, 3),
                }
                for r in rows
                if r.similarity >= 0.3
            ]
            if not results:
                return f"No semantically similar content found for '{query}'."
            return json.dumps(results, indent=2)

    # --- RMS tools (Reason Maintenance System) ---

    @tool
    def rms_status() -> str:
        """Show all beliefs in the RMS network with truth values (IN or OUT).
        Returns node IDs, text, truth values, and justification counts."""
        result = rms_api.get_status(project_id)
        return json.dumps(result, indent=2)

    @tool
    def rms_add(node_id: str, text: str, sl: str = "", unless: str = "",
                label: str = "", source: str = "") -> str:
        """Add a belief to the RMS network.
        Use sl for dependencies (comma-separated node IDs that must be IN).
        Use unless for outlist (comma-separated node IDs that must be OUT).
        Without sl or unless, the node is a premise (IN by default)."""
        result = rms_api.add_node(project_id, node_id, text, sl=sl,
                                  unless=unless, label=label, source=source)
        return json.dumps(result)

    @tool
    def rms_retract(node_id: str) -> str:
        """Retract a belief and cascade to all dependents.
        Returns the list of all node IDs whose truth value changed."""
        result = rms_api.retract_node(project_id, node_id)
        return json.dumps(result)

    @tool
    def rms_assert(node_id: str) -> str:
        """Assert a belief (mark IN) and cascade restoration to dependents.
        Returns the list of all node IDs whose truth value changed."""
        result = rms_api.assert_node(project_id, node_id)
        return json.dumps(result)

    @tool
    def rms_explain(node_id: str) -> str:
        """Explain why a belief is IN or OUT by tracing its justification chain.
        Shows the full dependency path back to premises."""
        result = rms_api.explain_node(project_id, node_id)
        return json.dumps(result, indent=2)

    @tool
    def rms_show(node_id: str) -> str:
        """Show full details for a belief: text, status, source, justifications, dependents."""
        result = rms_api.show_node(project_id, node_id)
        return json.dumps(result, indent=2)

    @tool
    def rms_search(query: str) -> str:
        """Search beliefs by keyword (full-text search). Returns compact one-line-per-belief format."""
        result = rms_api.search(project_id, query)
        if not result["results"]:
            return f"No beliefs match '{query}'."
        lines = [
            f"[{r['truth_value']}] {r['id']} — {r['text']}"
            for r in result["results"]
        ]
        return "\n".join(lines)

    @tool
    def rms_trace(node_id: str) -> str:
        """Trace backward to find all premises (assumptions) a belief rests on."""
        result = rms_api.trace_assumptions(project_id, node_id)
        return json.dumps(result)

    @tool
    def rms_challenge(target_id: str, reason: str) -> str:
        """Challenge a belief. Creates a challenge node and the target goes OUT.
        Use when a reviewer or new evidence disputes a belief."""
        result = rms_api.challenge(project_id, target_id, reason)
        return json.dumps(result)

    @tool
    def rms_defend(target_id: str, challenge_id: str, reason: str) -> str:
        """Defend a belief against a challenge. Neutralises the challenge, target restored."""
        result = rms_api.defend(project_id, target_id, challenge_id, reason)
        return json.dumps(result)

    @tool
    def rms_nogood(node_ids: list[str]) -> str:
        """Record a contradiction — these beliefs cannot all be true.
        Uses dependency-directed backtracking to find and retract the responsible premise."""
        result = rms_api.add_nogood(project_id, node_ids)
        return json.dumps(result)

    @tool
    def rms_compact(budget: int = 500) -> str:
        """Generate a token-budgeted summary of the belief network.
        Priority: nogoods first, then OUT nodes, then IN nodes by importance."""
        return rms_api.compact(project_id, budget=budget)

    @tool
    def rms_find_issues() -> str:
        """Find issues in the belief network: blocked beliefs (gated by active problems)
        and beliefs that describe problems/defects/risks. Review the candidates and
        identify which are genuinely negative vs. beliefs that merely describe mechanisms."""
        gated = rms_api.list_gated(project_id)
        negative = rms_api.list_negative_candidates(project_id)

        parts = []

        if gated["blocker_count"] > 0:
            parts.append(f"## Blocked Beliefs ({gated['gated_count']} gated by {gated['blocker_count']} blockers)\n")
            for blocker_id, info in sorted(gated["blockers"].items()):
                parts.append(f"[BLOCKER] {blocker_id} — {info['text']}")
                for g in info["gated"]:
                    parts.append(f"  ⊢ {g['id']}: {g['text']}")
                parts.append("")
        else:
            parts.append("## Blocked Beliefs\nNone — all gated beliefs are satisfied.\n")

        if negative["candidate_count"] > 0:
            shown = negative["candidates"][:50]
            remaining = negative["candidate_count"] - len(shown)
            parts.append(f"## Negative Belief Candidates ({negative['candidate_count']} of {negative['total_in']} IN beliefs)\n")
            parts.append("Classify which are genuinely negative (problems/risks) vs. descriptions of mechanisms:\n")
            for c in shown:
                parts.append(f"[-?] {c['id']} — {c['text']}")
            if remaining > 0:
                parts.append(f"\n... and {remaining} more candidates (use rms_search to explore specific topics)")
        else:
            parts.append("## Negative Belief Candidates\nNo keyword matches found.\n")

        return "\n".join(parts)

    @tool
    def rms_what_if(node_id: str, action: str = "retract") -> str:
        """Simulate retracting or asserting a belief WITHOUT modifying the database.
        Shows what would cascade: which beliefs would go OUT, which would be restored.
        Use this to assess the impact of resolving a blocker before taking action.
        action: 'retract' (default) or 'assert'."""
        if action == "assert":
            result = rms_api.what_if_assert(project_id, node_id)
            already = result.get("already_in")
            if already:
                return f"{node_id} is already IN — no cascade."
        else:
            result = rms_api.what_if_retract(project_id, node_id)
            already = result.get("already_out")
            if already:
                return f"{node_id} is already OUT — no cascade."

        parts = [f"## What-if {action} {node_id}\n"]

        if result["retracted"]:
            parts.append(f"Would retract ({len(result['retracted'])} nodes):")
            for r in result["retracted"]:
                parts.append(f"  OUT depth={r['depth']} ({r['dependents']} deps) {r['id']} — {r['text']}")
            parts.append("")

        if result["restored"]:
            parts.append(f"Would restore ({len(result['restored'])} nodes):")
            for r in result["restored"]:
                parts.append(f"  IN  depth={r['depth']} ({r['dependents']} deps) {r['id']} — {r['text']}")
            parts.append("")

        parts.append(f"Total affected: {result['total_affected']}")
        return "\n".join(parts)

    tools = [
        search_knowledge, read_entry, list_entries, list_beliefs,
        read_source, list_source_entries, grep_content,
        rms_status, rms_add, rms_retract, rms_assert, rms_explain,
        rms_show, rms_search, rms_trace, rms_challenge, rms_defend,
        rms_nogood, rms_compact, rms_find_issues, rms_what_if,
    ]
    if _has_pgvector and settings.db_backend == "postgresql":
        tools.insert(7, semantic_search)  # after grep_content
    return tools
