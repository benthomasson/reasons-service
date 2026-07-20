"""FTS abstraction layer — PostgreSQL tsvector/tsquery vs SQLite LIKE.

Returns SQL fragments and parameters so callers can build raw SQL queries
that work on both backends.
"""

import re

from reasons_service.config import settings

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
        terms = [w.lower() for w in re.findall(r'\w+', question) if len(w) > 1]
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
