"""FTS abstraction layer — PostgreSQL tsvector/tsquery vs SQLite LIKE.

Returns SQL fragments and parameters so callers can build raw SQL queries
that work on both backends.  Also provides IDF re-ranking and high-level
search helpers used by the API endpoints.
"""

import math
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text as sa_text

from reasons_service.config import settings
from reasons_service.db.connection import get_sync_session
from reasons_service.rms import api as rms_api

# Allowlist of column expressions that may be interpolated into SQL.
# All callers must use one of these — prevents SQL injection via text_expr.
_ALLOWED_TEXT_EXPRS = frozenset({
    "text",
    "c.text",
    "coalesce(title, '') || ' ' || content",
})


def _validate_text_expr(text_expr: str) -> None:
    if text_expr not in _ALLOWED_TEXT_EXPRS:
        raise ValueError(f"Disallowed text_expr: {text_expr!r}")


# Stop words to exclude from search queries
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


def _get_terms(question: str) -> list[str]:
    """Extract meaningful search terms from a question."""
    words = re.findall(r'\w+', question)
    terms = [w.lower() for w in words if w.lower() not in _STOP_WORDS and len(w) > 1]
    if not terms:
        terms = [w.lower() for w in words]
    return terms


def fts_clause(text_expr: str, question: str) -> tuple[str, str, dict]:
    """Build FTS WHERE and ORDER BY clauses with OR-query semantics.

    Returns (where_sql, order_sql, params).

    PostgreSQL: to_tsvector @@ to_tsquery with ts_rank_cd ranking.
    SQLite: multi-term LIKE OR conditions, no ranking.
    """
    _validate_text_expr(text_expr)
    terms = _get_terms(question)
    if not terms:
        return "1=0", "", {}

    if settings.db_backend == "postgresql":
        or_query = " | ".join(terms)
        where = (
            f"to_tsvector('english', {text_expr}) "
            f"@@ to_tsquery('english', :q)"
        )
        order = (
            f"ts_rank_cd(to_tsvector('english', {text_expr}), "
            f"to_tsquery('english', :q)) DESC"
        )
        return where, order, {"q": or_query}
    else:
        # SQLite: LIKE-based OR search
        conditions = " OR ".join(
            f"lower({text_expr}) LIKE :q{i}" for i in range(len(terms))
        )
        params = {f"q{i}": f"%{term}%" for i, term in enumerate(terms)}
        return f"({conditions})", "", params


def plainto_fts_clause(text_expr: str, question: str) -> tuple[str, str, dict]:
    """Build FTS clause with AND-query semantics (plainto_tsquery equivalent).

    Returns (where_sql, order_sql, params).
    """
    _validate_text_expr(text_expr)
    if settings.db_backend == "postgresql":
        where = (
            f"to_tsvector('english', {text_expr}) "
            f"@@ plainto_tsquery('english', :q)"
        )
        order = ""
        return where, order, {"q": question}
    else:
        # SQLite: AND of per-term LIKE conditions (matches plainto_tsquery semantics)
        terms = _get_terms(question)
        if not terms:
            return "1=0", "", {}
        conditions = " AND ".join(
            f"lower({text_expr}) LIKE :q{i}" for i in range(len(terms))
        )
        params = {f"q{i}": f"%{term}%" for i, term in enumerate(terms)}
        return f"({conditions})", "", params


# ---------------------------------------------------------------------------
# IDF re-ranking and high-level search helpers
# ---------------------------------------------------------------------------

MAX_CHUNK_CHARS = 2000
MAX_CONTEXT_CHARS = 30000
MAX_BELIEF_CONTEXT_CHARS = 30000


def _build_or_tsquery(question: str) -> str:
    terms = _get_terms(question)
    if not terms:
        return ""
    return " | ".join(terms)


def _compute_idf(session, domain_id: str, terms: list[str],
                 table: str, text_col: str = "text",
                 extra_where: str = "") -> dict[str, float]:
    if settings.db_backend == "sqlite":
        return {}
    where = f"WHERE domain_id = :pid {extra_where}"
    total = session.execute(
        sa_text(f"SELECT count(*) FROM {table} {where}"),
        {"pid": domain_id},
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
            {"pid": domain_id, "term": term},
        ).scalar() or 0
        idfs[term] = math.log((total + 1) / (df + 1))
    return idfs


def _idf_score(text: str, term_idfs: dict[str, float]) -> float:
    text_lower = text.lower()
    return sum(idf for term, idf in term_idfs.items() if term in text_lower)


@dataclass
class SourceRef:
    """A source reference for search results."""
    label: str
    slug: str
    url: str
    category: str
    cite_key: str = ""


def _source_title_from_path(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    name = re.sub(r'\.(md|json|txt|yaml|yml)$', '', name)
    name = name.replace("-", " ").replace("_", " ")
    return name.strip().title()


def quick_belief_search(domain_id: UUID, question: str, limit: int = 10) -> tuple[str, list[SourceRef]]:
    """Fast belief search with IDF re-ranking.

    Returns (context_string, source_refs).
    """
    belief_rows = rms_api.search_beliefs_fts(domain_id, question, limit * 3)
    if not belief_rows:
        return "", []

    if settings.db_backend == "postgresql":
        terms = _get_terms(question)
        pid = str(domain_id)
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
                url = f"/domains/{domain_id}/source/{source}"
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


def search_source_chunks(domain_id: UUID, query: str, limit: int = 10) -> tuple[str, list[SourceRef]]:
    """FTS search over source_chunks with IDF re-ranking.

    Returns (context_string, source_refs).
    """
    terms = _get_terms(query)
    if not terms:
        return "", []
    pid = domain_id.hex if settings.db_backend == "sqlite" else str(domain_id)
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
                        "WHERE c.domain_id = :pid "
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
                        f"WHERE c.domain_id = :pid "
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
                    f"WHERE c.domain_id = :pid "
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
        if "/" in r.slug:
            domain, title = r.slug.split("/", 1)
            label = f'{domain}, "{title}"'
        else:
            label = f'"{r.slug}"'
        url = r.url or ""
        if not url:
            url = f"/domains/{domain_id}/source/{r.slug}"
        sources.append(SourceRef(
            label=label,
            slug=r.slug,
            url=url,
            category="Supporting",
            cite_key=r.slug,
        ))
    return "\n\n---\n\n".join(parts), sources
