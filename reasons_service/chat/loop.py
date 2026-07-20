"""LangGraph agent streaming with SSE translation."""

import asyncio
import json
import logging
import math
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text as sa_text

from reasons_service.chat.agent import get_agent
from reasons_service.config import settings
from reasons_service.connectors import ConnectorRegistry, query_data
from reasons_service.db.connection import get_sync_session
from reasons_service.db.search import fts_clause
from reasons_service.llm.provider import get_chat_model
from reasons_service.rms import api as rms_api

logger = logging.getLogger(__name__)

# Context budget constants
MAX_CHUNK_CHARS = 2000  # Truncate individual source chunks
MAX_CONTEXT_CHARS = 30000  # Total source chunk context budget (~7500 tokens)
MAX_BELIEF_CONTEXT_CHARS = 30000  # Total belief context budget (~7500 tokens)
MAX_TOOL_RESULT_CHARS = 10000  # Truncate individual tool/connector results


def _langfuse_config() -> dict:
    """Return a LangChain config dict with langfuse callbacks if configured."""
    if not settings.langfuse_secret_key:
        return {}
    from langfuse.langchain import CallbackHandler

    return {"callbacks": [CallbackHandler()]}


def _check_llm_ready(model: str | None = None) -> str | None:
    """Check if the LLM is configured and return an error message if not."""
    model = model or settings.default_model
    if model.startswith("ollama:"):
        return None  # Ollama doesn't need cloud credentials
    if not settings.google_cloud_project:
        return "LLM mode is enabled but no LLM is configured."
    return None

# Common stop words to exclude from OR queries (matches reasons_lib)
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "ought",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "this", "that", "these", "those", "what",
    "which", "who", "whom", "how", "when", "where", "why", "if", "then",
    "than", "so", "no", "not", "only", "very", "too", "also", "just",
    "about", "above", "after", "before", "between", "but", "by", "for",
    "from", "in", "into", "of", "on", "or", "out", "over", "to", "up",
    "with", "and", "as", "at",
})


def _get_query_terms(question: str) -> list[str]:
    """Extract meaningful query terms (lowercased) from a question."""
    words = re.findall(r'\w+', question)
    terms = [w.lower() for w in words if w.lower() not in _STOP_WORDS and len(w) > 1]
    if not terms:
        terms = [w.lower() for w in re.findall(r'\w+', question) if len(w) > 1]
    return terms


def _build_or_tsquery(question: str) -> str:
    """Build an OR-based tsquery string from a question, matching FTS5 behavior."""
    terms = _get_query_terms(question)
    if not terms:
        return ""
    return " | ".join(terms)


def _compute_idf(session, project_id: str, terms: list[str],
                 table: str, text_col: str = "text",
                 extra_where: str = "") -> dict[str, float]:
    """Compute IDF weight for each query term against a table's tsvector index.

    IDF = log((N + 1) / (df + 1)) where N = total docs, df = docs containing term.
    Rare terms get high weight, common terms get low weight — approximates BM25.

    Requires PostgreSQL tsvector; returns empty dict on SQLite (no IDF re-ranking).
    """
    if settings.db_backend == "sqlite":
        return {}
    where = f"WHERE project_id = :pid {extra_where}"
    total = session.execute(
        sa_text(f"SELECT count(*) FROM {table} {where}"),
        {"pid": project_id},
    ).scalar() or 0
    if total == 0:
        return {}
    idfs = {}
    for term in terms:
        df = session.execute(
            sa_text(
                f"SELECT count(*) FROM {table} "
                f"{where} "
                f"AND to_tsvector('english', {text_col}) @@ to_tsquery('english', :term)"
            ),
            {"pid": project_id, "term": term},
        ).scalar() or 0
        idfs[term] = math.log((total + 1) / (df + 1))
    return idfs


def _idf_score(text: str, term_idfs: dict[str, float]) -> float:
    """Score text by sum of IDF weights for matched terms."""
    text_lower = text.lower()
    return sum(idf for term, idf in term_idfs.items() if term in text_lower)


@dataclass
class SourceRef:
    """A source reference for the ## Sources section."""
    label: str       # Display label (e.g. "Ansible 3 Pager")
    slug: str        # Raw identifier for deduplication
    url: str         # URL if available
    category: str    # "Primary", "Supporting", "Data"
    cite_key: str = ""  # Key the LLM uses to cite this source (belief ID or chunk slug)


def _source_title_from_path(path: str) -> str:
    """Convert a source file path to a readable title.

    entries/2026/04/17/ansible-3-pager.md → Ansible 3 Pager
    """
    name = path.rsplit("/", 1)[-1]
    name = re.sub(r'\.(md|json|txt|yaml|yml)$', '', name)
    name = name.replace("-", " ").replace("_", " ")
    return name.strip().title()


MAX_SOURCES = 10  # Cap displayed sources to keep responses readable


def _extract_cited_keys(text: str) -> set[str]:
    """Extract [citation] keys from LLM response text.

    Matches belief IDs like [engineering:belief-name] and
    chunk slugs like [engineering/source-name].
    Skips markdown links [text](url) and numeric-only refs [1].
    """
    keys = set()
    for m in re.finditer(r'\[([^\]]+)\]', text):
        key = m.group(1)
        # Skip markdown links (followed by parenthesized URL)
        end = m.end()
        if end < len(text) and text[end] == '(':
            continue
        # Skip pure numbers, truth values, and common markdown patterns
        if re.match(r'^(\d+|IN|OUT|\.\.\.truncated)$', key):
            continue
        # Handle comma-separated keys like [belief-a, belief-b]
        if ", " in key:
            for part in key.split(", "):
                part = part.strip()
                if part and not re.match(r'^(\d+|IN|OUT)$', part):
                    keys.add(part)
        else:
            keys.add(key)
    return keys


def _build_sources_section(sources: list[SourceRef], response_text: str = "") -> str:
    """Build a ## Sources section from collected source refs.

    If response_text is provided, only includes sources that the LLM
    actually cited inline via [belief-id] or [slug] markers. Data sources
    are always included.
    """
    if not sources:
        return ""

    # Filter to cited sources if we have response text
    if response_text:
        cited_keys = _extract_cited_keys(response_text)
        filtered = []
        for s in sources:
            if s.category == "Data":
                filtered.append(s)
            elif s.cite_key and s.cite_key in cited_keys:
                filtered.append(s)
        # Fall back to all sources if nothing was cited (LLM didn't use inline citations)
        if filtered:
            sources = filtered

    # Deduplicate by slug, preserving order
    seen: set[str] = set()
    unique: list[SourceRef] = []
    for s in sources:
        if s.slug not in seen:
            seen.add(s.slug)
            unique.append(s)

    # Separate derived beliefs (no source doc) from sourced references
    # Do this BEFORE the cap so beliefs aren't truncated by MAX_SOURCES
    data = [s for s in unique if s.category == "Data"]
    beliefs = [s for s in unique if s.category == "Primary" and not s.url and "/" not in s.slug]
    rest = [s for s in unique if s not in data and s not in beliefs]
    order = {"Primary": 0, "Supporting": 1}
    rest.sort(key=lambda s: order.get(s.category, 9))
    rest = rest[:MAX_SOURCES - len(data)]
    sourced = data + rest

    lines = []

    if sourced:
        lines += ["", "", "## Sources", ""]
        for s in sourced:
            key = s.cite_key or s.slug
            lines.append(f"- **[{key}]** {s.label}")
            if s.url:
                lines.append(f"  [Source]({s.url})")
            elif "/" in s.slug:
                lines.append(f"  [Source: {s.slug}]")
            lines.append("")

    if beliefs:
        lines += ["", "## Beliefs", ""]
        for s in beliefs:
            key = s.cite_key or s.slug
            lines.append(f"- **[{key}]** {s.label}")
            lines.append("")

    return "\n".join(lines)


def _strip_hallucinated_refs(text: str, valid_keys: set[str]) -> str:
    """Remove bracketed references that don't match any valid citation key.

    LLMs (especially smaller models like Gemma3) hallucinate citations —
    inventing numbered refs like [5] or citing belief IDs not in the search
    results. This strips any [ref] that isn't in the valid set.
    """
    stripped: list[str] = []

    def _replace(m):
        key = m.group(1)
        end = m.end()
        # Keep markdown links [text](url)
        if end < len(text) and text[end] == '(':
            return m.group(0)
        if key in valid_keys:
            return m.group(0)
        # Keep common markdown patterns
        if key in ('x', ' ', '!') or key.startswith('^'):
            return m.group(0)
        stripped.append(key)
        return ''

    result = re.sub(r'\[([^\]]+)\]', _replace, text)
    if stripped:
        logger.info("Stripped %d citation(s): %s", len(stripped), stripped)
    return result



def _quick_belief_search(project_id: UUID, question: str, limit: int = 10) -> tuple[str, list[SourceRef]]:
    """Fast belief pre-check with IDF re-ranking.

    PostgreSQL: tsvector FTS with ts_rank_cd baseline, IDF re-ranking.
    SQLite: delegates to rms_api.search_beliefs_fts (reasons_lib FTS5).

    Returns (context_string, source_refs) where source_refs tracks provenance.
    """
    # Get belief rows (backend-dispatched)
    belief_rows = rms_api.search_beliefs_fts(project_id, question, limit * 3)
    if not belief_rows:
        return "", []

    # IDF re-ranking (PostgreSQL only; returns empty dict on SQLite)
    if settings.db_backend == "postgresql":
        terms = _get_query_terms(question)
        pid = str(project_id)
        with get_sync_session() as session:
            idfs = _compute_idf(session, pid, terms, "rms_nodes",
                                   extra_where="AND truth_value = 'IN'")
        if idfs:
            belief_rows = sorted(belief_rows, key=lambda r: _idf_score(r["text"], idfs), reverse=True)

    belief_rows = belief_rows[:limit]
    parts = []
    total = 0
    included_rows = []
    for r in belief_rows:
        line = f"[{r.get('truth_value', 'IN')}] {r['id']} — {r['text']}"
        if total + len(line) > MAX_BELIEF_CONTEXT_CHARS:
            break
        parts.append(line)
        total += len(line)
        included_rows.append(r)
    context = "\n".join(parts)
    belief_rows = included_rows
    sources = []
    for r in belief_rows:
        rid = r["id"]
        domain = rid.split(":")[0] if ":" in rid else ""
        source = r.get("source", "")
        source_url = r.get("source_url", "")
        if source:
            title = _source_title_from_path(source)
            label = f'{domain}, "{title}"' if domain else f'"{title}"'
            url = source_url or ""
            if not url and "/" in source:
                url = f"/projects/{project_id}/source/{source}"
        else:
            title = rid.split(":", 1)[-1].replace("-", " ").title()
            label = f'{domain}, "{title}"' if domain else f'"{title}"'
            url = ""
        slug = rid
        sources.append(SourceRef(
            label=label,
            slug=slug,
            url=url,
            category="Primary",
            cite_key=rid,
        ))
    return context, sources


def _extract_text(content) -> str:
    """Extract plain text from LLM content (handles str, list of dicts, etc.)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content)


async def chat_stream(
    project_id: UUID,
    model: str,
    message: str,
    thread_id: str,
) -> AsyncGenerator[str, None]:
    """Stream a chat response via LangGraph react agent.

    Translates LangGraph streaming events into SSE:
      data: {"type": "token", "content": "..."}
      event: tool_call\\ndata: {"name": "...", "args": {...}}
      event: tool_result\\ndata: {"name": "...", "summary": "..."}
      event: done\\ndata: {}
    """
    llm_error = _check_llm_ready(model)
    if llm_error:
        yield f"data: {json.dumps({'type': 'token', 'content': llm_error})}\n\n"
        yield "event: done\ndata: {}\n\n"
        return

    agent = await get_agent(project_id, model)
    config = {"configurable": {"thread_id": f"{project_id}:{thread_id}"}}
    config.update(_langfuse_config())

    # Belief-first pre-check: inject matching beliefs so the LLM can
    # answer directly without a tool call when beliefs are sufficient.
    belief_context, _sources = _quick_belief_search(project_id, message)
    if belief_context:
        augmented = f"{message}\n\n[Belief matches:\n{belief_context}\n]"
        logger.info("Belief pre-check: %d matches for %r",
                     belief_context.count("\n") + 1, message[:60])
    else:
        augmented = message

    inputs = {"messages": [{"role": "user", "content": augmented}]}

    buffered_tokens: list[str] = []

    async for mode, data in agent.astream(
        inputs, config, stream_mode=["messages", "updates"]
    ):
        if mode == "messages":
            chunk, metadata = data
            # Only buffer tokens from the agent node (not tools)
            if metadata.get("langgraph_node") == "agent":
                text = _extract_text(chunk.content) if chunk.content else ""
                if text:
                    buffered_tokens.append(text)

        elif mode == "updates":
            if "agent" in data:
                msg = data["agent"]["messages"][-1]
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    # Intermediate round — suppress text, emit tool indicators
                    buffered_tokens.clear()
                    for tc in msg.tool_calls:
                        yield (
                            f"event: tool_call\n"
                            f"data: {json.dumps({'name': tc['name'], 'args': tc['args']})}\n\n"
                        )
                else:
                    # Final round — flush buffered tokens
                    for text in buffered_tokens:
                        yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
                    buffered_tokens.clear()

            elif "tools" in data:
                for msg in data["tools"]["messages"]:
                    summary = str(msg.content)[:200]
                    name = getattr(msg, "name", "tool")
                    yield (
                        f"event: tool_result\n"
                        f"data: {json.dumps({'name': name, 'summary': summary})}\n\n"
                    )

    yield "event: done\ndata: {}\n\n"


# --- Dual-path architecture ---

def _search_source_chunks(project_id: UUID, query: str, limit: int = 10) -> tuple[str, list[SourceRef]]:
    """FTS search over source_chunks with IDF re-ranking.

    PostgreSQL: tsvector with ts_rank_cd baseline, IDF re-ranking.
    SQLite: FTS5 with BM25 ranking, falls back to LIKE if FTS5 unavailable.

    Returns (context_string, source_refs) where source_refs tracks provenance.
    """
    terms = _get_query_terms(query)
    if not terms:
        return "", []
    pid = project_id.hex if settings.db_backend == "sqlite" else str(project_id)
    idfs = {}

    if settings.db_backend == "sqlite":
        fts5_query = " OR ".join(f'"{t}"' for t in terms)
        with get_sync_session() as session:
            try:
                rows = session.execute(
                    sa_text(
                        "SELECT c.text, c.section, s.slug, s.url "
                        "FROM source_chunks c "
                        "JOIN source_chunks_fts f ON f.id = c.id "
                        "JOIN sources s ON s.id = c.source_id "
                        "WHERE c.project_id = :pid "
                        "AND source_chunks_fts MATCH :q "
                        "ORDER BY f.rank "
                        "LIMIT :lim"
                    ),
                    {"pid": pid, "q": fts5_query, "lim": limit * 3},
                ).all()
            except Exception:
                where, order, params = fts_clause("c.text", query)
                params["pid"] = pid
                params["lim"] = limit * 3
                rows = session.execute(
                    sa_text(
                        f"SELECT c.text, c.section, s.slug, s.url "
                        f"FROM source_chunks c "
                        f"JOIN sources s ON s.id = c.source_id "
                        f"WHERE c.project_id = :pid "
                        f"AND {where} "
                        f"LIMIT :lim"
                    ),
                    params,
                ).all()
    else:
        where, order, params = fts_clause("c.text", query)
        params["pid"] = pid
        params["lim"] = limit * 3
        order_clause = f"ORDER BY {order}" if order else ""
        with get_sync_session() as session:
            idfs = _compute_idf(session, pid, terms, "source_chunks")
            rows = session.execute(
                sa_text(
                    f"SELECT c.text, c.section, s.slug, s.url "
                    f"FROM source_chunks c "
                    f"JOIN sources s ON s.id = c.source_id "
                    f"WHERE c.project_id = :pid "
                    f"AND {where} "
                    f"{order_clause} "
                    f"LIMIT :lim"
                ),
                params,
            ).all()
    if not rows:
        return "", []
    if idfs:
        rows = sorted(rows, key=lambda r: _idf_score(r.text, idfs), reverse=True)
    rows = rows[:limit]
    parts = []
    sources = []
    total = 0
    for i, r in enumerate(rows, 1):
        chunk_text = r.text[:MAX_CHUNK_CHARS]
        if len(r.text) > MAX_CHUNK_CHARS:
            chunk_text += "\n[...truncated]"
        header = f"[{i}] {r.slug}"
        if r.section:
            header += f" > {r.section}"
        part = f"### {header}\n\n{chunk_text}"
        if total + len(part) > MAX_CONTEXT_CHARS:
            break
        parts.append(part)
        total += len(part)
        # Extract domain and title from slug (e.g. "engineering/00 - OCP vs K8's")
        if "/" in r.slug:
            domain, title = r.slug.split("/", 1)
            label = f'{domain}, "{title}"'
        else:
            label = f'"{r.slug}"'
        url = r.url or ""
        if not url:
            # Generate internal URL to view the source entry
            url = f"/projects/{project_id}/source/{r.slug}"
        sources.append(SourceRef(
            label=label,
            slug=r.slug,
            url=url,
            category="Supporting",
            cite_key=r.slug,
        ))
    return "\n\n---\n\n".join(parts), sources


def _connector_tool_section(allowed_connectors: list[str] | None = None) -> str:
    """Build the query_data tool description if connectors are available."""
    connectors = ConnectorRegistry.get().list_connectors(allowed_connectors)
    if not connectors:
        return ""
    names = ", ".join(c.name for c in connectors)
    descriptions = "\n".join(f"- {c.name}: {c.description}" for c in connectors)
    return (
        f'\n{{"tool": "query_data", "question": "natural language question", "connector": "{connectors[0].name}"}}\n'
        f"\nAvailable data connectors:\n{descriptions}\n"
        f"\n- Only query live data when beliefs are insufficient (e.g. current numbers, temporal data).\n"
    )


TMS_ASK_PROMPT = """\
You are answering a question using a belief network (a Truth Maintenance System).
Each belief has an ID, text, and truth value (IN = held true, OUT = retracted).

You have tools available:

{{"tool": "search_beliefs", "query": "search terms"}}
{connector_tools}
Rules:
- IMPORTANT: For questions asking for current numbers, counts, headcount, revenue,
  pipeline totals, or other live/temporal data: you MUST call query_data FIRST,
  even if beliefs mention related topics. Beliefs are documented knowledge from a
  point in time — they are NOT current data. Always prefer query_data for "how many",
  "what is the current", "what percentage", and similar quantitative questions.
- IMPORTANT: For questions about specific people ("who is", "what does X do",
  "who manages", "who works on"), you MUST call query_data to check employee
  directory data. Beliefs may mention people incidentally but the live data
  source has authoritative role, department, and reporting information.
- If the belief matches below are sufficient to answer the question AND it is not
  a live-data question, write your answer directly. Do NOT call a tool.
- If you need to search for more beliefs, respond with ONLY a single JSON line
  (no other text). The system will run the search and give you the results.
- Cite belief IDs in [brackets] when referencing specific beliefs.
- ONLY answer based on the beliefs and tool results provided. Do NOT use your
  training data or general knowledge to fill gaps.
- If the beliefs and data connectors are insufficient to answer, say so honestly
  and note what's missing.

## Question

{question}

## Belief matches

{beliefs}
{tool_history}"""

TMS_FINAL_PROMPT = """\
You are answering a question using a belief network (a Truth Maintenance System).
Each belief has an ID, text, and truth value (IN = held true, OUT = retracted).

Rules:
- Cite belief IDs in [brackets] when referencing specific beliefs.
- ONLY answer based on the beliefs provided. Do NOT use your training data or
  general knowledge to fill gaps.
- If the beliefs are insufficient to answer, say so honestly and note what's missing.
- Write your answer now.

## Question

{question}

## Belief matches

{beliefs}
{tool_history}"""

MAX_TMS_ITERATIONS = 3

FTS_RAG_PROMPT = """\
You are answering questions using retrieved document excerpts.

Below are the most relevant excerpts from source documents, retrieved via
full-text search. Use them to answer the question. Cite your sources by referencing
the document filename in [brackets].

If the excerpts don't contain enough information to answer the question, say so honestly.
Do not fabricate information that isn't in the provided excerpts.

## Retrieved Documents

{context}

## Question

{question}

## Instructions

- Answer the question based on the retrieved documents above
- Cite sources using [filename] notation
- If information is insufficient, say what you can and note the gaps
- Be specific and concise
"""

MERGE_PROMPT = """\
You are merging two answers to the same question. Each answer was produced
independently using a different retrieval method:

- Answer A used a structured belief network with dependency chains
- Answer B used full-text search over source documents

Produce a single merged answer that:
- Combines information from both answers
- When both answers cover the same point, use the more specific/detailed version
- Preserve ALL citations from both answers in [brackets] — belief IDs like [belief-name] from Answer A, source slugs like [cluster/filename] from Answer B
- Every claim that came from a belief MUST retain its [belief-id] citation in the merged answer
- Every claim that came from a source document MUST retain its [source-slug] citation
- Do not add information that neither answer contains
- If the answers contradict each other, note the disagreement

## Question

{question}

## Answer A (Belief Network)

{answer_tms}

## Answer B (Source Documents)

{answer_fts}
"""


def _extract_tool_call(text: str) -> dict | None:
    """Extract a tool call from LLM response text. Returns parsed dict or None."""
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


async def _tms_answer_iterative(
    project_id: UUID, llm, question: str, initial_beliefs: str,
    allowed_connectors: list[str] | None = None,
) -> tuple[str, list[SourceRef]]:
    """TMS answer with up to 3 iterative search rounds, matching CLI behavior.

    When data connectors are available (via allowed_connectors), the LLM can
    also call query_data to fetch live data alongside belief searches.

    Returns (answer_text, extra_sources) where extra_sources includes both
    connector queries and beliefs discovered during iterative searches.
    """
    beliefs_ctx = initial_beliefs
    connector_tools = _connector_tool_section(allowed_connectors)

    if not beliefs_ctx and not connector_tools:
        return "No matching beliefs found in the network.", []
    if not beliefs_ctx:
        beliefs_ctx = "(no belief matches — use query_data if available)"
    logger.info("TMS iterative: connectors=%r, tools_section=%d chars",
                allowed_connectors, len(connector_tools))
    tool_history: list[dict] = []
    extra_sources: list[SourceRef] = []

    for iteration in range(MAX_TMS_ITERATIONS):
        history_section = ""
        if tool_history:
            parts = []
            for e in tool_history:
                result = e['result']
                if len(result) > MAX_TOOL_RESULT_CHARS:
                    result = result[:MAX_TOOL_RESULT_CHARS] + "\n[...truncated]"
                parts.append(f"### Tool call: {e['tool']}(\"{e['query']}\")\n\n{result}")
            history_section = "\n\n## Additional search results\n\n" + "\n\n---\n\n".join(parts)

        if iteration == MAX_TMS_ITERATIONS - 1:
            prompt = TMS_FINAL_PROMPT.format(
                question=question, beliefs=beliefs_ctx, tool_history=history_section,
            )
        else:
            prompt = TMS_ASK_PROMPT.format(
                question=question, beliefs=beliefs_ctx,
                tool_history=history_section, connector_tools=connector_tools,
            )

        resp = await llm.ainvoke(prompt, config=_langfuse_config())
        response_text = _extract_text(resp.content)

        tool_call = _extract_tool_call(response_text)
        if tool_call is None:
            return response_text, extra_sources

        if tool_call.get("tool") == "search_beliefs":
            query = tool_call.get("query", "")
            logger.info("TMS iterative search round %d: %r", iteration + 1, query)
            extra_ctx, iter_sources = await asyncio.to_thread(
                _quick_belief_search, project_id, query, 20,
            )
            tool_history.append({"tool": "search_beliefs", "query": query,
                                 "result": extra_ctx or "No results found."})
            if extra_ctx:
                beliefs_ctx = extra_ctx
                extra_sources.extend(iter_sources)
        elif tool_call.get("tool") == "query_data":
            q = tool_call.get("question", "")
            connector = tool_call.get("connector")
            logger.info("TMS data query round %d: connector=%s query=%r",
                        iteration + 1, connector, q)
            result = await query_data(q, connector_name=connector,
                                      allowed=allowed_connectors)
            if len(result) > MAX_TOOL_RESULT_CHARS:
                result = result[:MAX_TOOL_RESULT_CHARS] + "\n[...truncated]"
            tool_history.append({"tool": f"query_data({connector or 'all'})",
                                 "query": q, "result": result})
            connector_label = (connector or "data").title()
            extra_sources.append(SourceRef(
                label=f"{connector_label} Query: {q}",
                slug=f"{connector_label} - Direct Query",
                url="",
                category="Data",
            ))
        else:
            return response_text, extra_sources

    return response_text, extra_sources


async def dual_ask(
    project_id: UUID,
    model: str,
    message: str,
    allowed_connectors: list[str] | None = None,
) -> dict:
    """Dual-path: TMS (iterative) + FTS RAG in parallel, merge, return complete answer."""
    llm_error = _check_llm_ready(model)
    if llm_error:
        return {"answer": llm_error, "tms_chars": 0, "rag_chars": 0}

    # Phase 1: parallel retrieval
    (belief_ctx, belief_sources), (chunk_ctx, chunk_sources) = await asyncio.gather(
        asyncio.to_thread(_quick_belief_search, project_id, message, 20),
        asyncio.to_thread(_search_source_chunks, project_id, message, 10),
    )

    # Check if connectors are available before short-circuiting
    from reasons_service.connectors import ConnectorRegistry
    has_connectors = bool(ConnectorRegistry.get().list_connectors(allowed_connectors))

    if not belief_ctx and not chunk_ctx and not has_connectors:
        return {
            "answer": "No matching beliefs or source documents found for this question.",
            "tms_chars": 0,
            "rag_chars": 0,
        }

    # Phase 2: parallel synthesis (TMS iterative + RAG single-pass)
    llm = get_chat_model(model)

    async def _rag_answer() -> str:
        if not chunk_ctx:
            return "No relevant source documents found."
        prompt = FTS_RAG_PROMPT.format(context=chunk_ctx, question=message)
        resp = await llm.ainvoke(prompt, config=_langfuse_config())
        return _extract_text(resp.content)

    (answer_tms, data_sources), answer_fts = await asyncio.gather(
        _tms_answer_iterative(project_id, llm, message, belief_ctx,
                              allowed_connectors=allowed_connectors),
        _rag_answer(),
    )

    # Phase 3: merge
    merge_prompt = MERGE_PROMPT.format(
        question=message, answer_tms=answer_tms, answer_fts=answer_fts,
    )
    resp = await llm.ainvoke(merge_prompt, config=_langfuse_config())
    merged = _extract_text(resp.content)

    # Strip hallucinated refs, then append sources section
    all_sources = belief_sources + chunk_sources + data_sources
    valid_keys = {s.cite_key for s in all_sources if s.cite_key}
    merged = _strip_hallucinated_refs(merged, valid_keys)
    sources_section = _build_sources_section(all_sources, response_text=merged)
    merged += sources_section

    return {
        "answer": merged,
        "tms_chars": len(answer_tms),
        "rag_chars": len(answer_fts),
    }


SINGLE_PASS_PROMPT = """\
You are an expert assistant answering questions using a curated knowledge base.
You have two sources of context:

1. **TMS Beliefs** — verified facts from a Truth Maintenance System, each with a truth value (IN = accepted, OUT = retracted) and a belief ID. Prefer IN beliefs. Cite beliefs by their ID in square brackets, e.g. [ec2-pay-per-instance-second].

2. **Source Documents** — relevant passages from source documents, each with a source slug. Cite sources by their slug in square brackets, e.g. [ec2-instance-types].

Rules:
- Answer the question comprehensively using ONLY the provided context
- If beliefs and sources disagree, prefer beliefs (they have been through truth maintenance)
- Cite your sources inline using [belief-id] or [source-slug]
- Structure your answer with clear headings and bullet points
- If the context does not contain enough information, say so explicitly
- Do not use knowledge outside the provided context

## Question

{question}

## TMS Beliefs

{beliefs}

## Source Documents

{sources}

---

Answer the question using the context above. Cite sources inline."""


async def single_ask(
    project_id: UUID,
    model: str,
    message: str,
) -> dict:
    """Single-pass: deep-search retrieval + one LLM synthesis call.

    Better for smaller models (e.g. Gemma3) that struggle with the
    3-call dual-path merge pattern. Mirrors the expert CLI ask-local flow.
    """
    llm_error = _check_llm_ready(model)
    if llm_error:
        return {"answer": llm_error, "tms_chars": 0, "rag_chars": 0}

    # Retrieval: same as deep-search
    (belief_ctx, belief_sources), (chunk_ctx, chunk_sources) = await asyncio.gather(
        asyncio.to_thread(_quick_belief_search, project_id, message, 20),
        asyncio.to_thread(_search_source_chunks, project_id, message, 10),
    )

    if not belief_ctx and not chunk_ctx:
        return {
            "answer": "No matching beliefs or source documents found for this question.",
            "tms_chars": 0,
            "rag_chars": 0,
        }

    # Single LLM call
    llm = get_chat_model(model)
    prompt = SINGLE_PASS_PROMPT.format(
        question=message,
        beliefs=belief_ctx or "(none found)",
        sources=chunk_ctx or "(none found)",
    )
    resp = await llm.ainvoke(prompt, config=_langfuse_config())
    answer = _extract_text(resp.content)

    # Strip hallucinated refs, append sources section
    all_sources = belief_sources + chunk_sources
    valid_keys = {s.cite_key for s in all_sources if s.cite_key}
    answer = _strip_hallucinated_refs(answer, valid_keys)
    sources_section = _build_sources_section(all_sources, response_text=answer)
    answer += sources_section

    return {
        "answer": answer,
        "tms_chars": len(belief_ctx or ""),
        "rag_chars": len(chunk_ctx or ""),
    }


async def dual_chat_stream(
    project_id: UUID,
    model: str,
    message: str,
    thread_id: str,
    allowed_connectors: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """Dual-path: TMS beliefs + FTS RAG in parallel, then merge with streaming.

    Three phases:
    1. Parallel retrieval: tsvector search over beliefs and source chunks
    2. Parallel synthesis: TMS answer + FTS RAG answer (two LLM calls)
    3. Merge: combine both answers in a third LLM call, streaming tokens
    """
    llm_error = _check_llm_ready(model)
    if llm_error:
        yield f"data: {json.dumps({'type': 'token', 'content': llm_error})}\n\n"
        yield "event: done\ndata: {}\n\n"
        return
    yield f"event: phase\ndata: {json.dumps({'phase': 'searching'})}\n\n"

    # Phase 1: parallel retrieval (sync → run in threads)
    (belief_ctx, belief_sources), (chunk_ctx, chunk_sources) = await asyncio.gather(
        asyncio.to_thread(_quick_belief_search, project_id, message, 20),
        asyncio.to_thread(_search_source_chunks, project_id, message, 10),
    )

    # Check if connectors are available before short-circuiting
    from reasons_service.connectors import ConnectorRegistry
    has_connectors = bool(ConnectorRegistry.get().list_connectors(allowed_connectors))

    if not belief_ctx and not chunk_ctx and not has_connectors:
        yield (
            f"data: {json.dumps({'type': 'token', 'content': 'No matching beliefs or source documents found for this question.'})}\n\n"
        )
        yield "event: done\ndata: {}\n\n"
        return

    # Phase 2: parallel synthesis
    yield f"event: phase\ndata: {json.dumps({'phase': 'synthesizing'})}\n\n"

    llm = get_chat_model(model)

    async def _rag_answer() -> str:
        if not chunk_ctx:
            return "No relevant source documents found."
        prompt = FTS_RAG_PROMPT.format(context=chunk_ctx, question=message)
        resp = await llm.ainvoke(prompt, config=_langfuse_config())
        return _extract_text(resp.content)

    (answer_tms, data_sources), answer_fts = await asyncio.gather(
        _tms_answer_iterative(project_id, llm, message, belief_ctx,
                              allowed_connectors=allowed_connectors),
        _rag_answer(),
    )

    logger.info(
        "Dual-path: TMS=%d chars, RAG=%d chars for %r",
        len(answer_tms), len(answer_fts), message[:60],
    )

    # Phase 3: merge — stream tokens
    yield f"event: phase\ndata: {json.dumps({'phase': 'merging'})}\n\n"

    merge_prompt = MERGE_PROMPT.format(
        question=message, answer_tms=answer_tms, answer_fts=answer_fts,
    )
    merged_text = ""
    async for chunk in llm.astream(merge_prompt, config=_langfuse_config()):
        text = _extract_text(chunk.content) if chunk.content else ""
        if text:
            merged_text += text
            yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"

    # Strip hallucinated refs, then stream sources section
    all_sources = belief_sources + chunk_sources + data_sources
    valid_keys = {s.cite_key for s in all_sources if s.cite_key}
    merged_text = _strip_hallucinated_refs(merged_text, valid_keys)
    sources_section = _build_sources_section(all_sources, response_text=merged_text)
    if sources_section:
        yield f"data: {json.dumps({'type': 'token', 'content': sources_section})}\n\n"

    yield "event: done\ndata: {}\n\n"
