"""Domain-scoped RMS API for reasons-service.

PostgreSQL: delegates to reasons_lib.pg.PgApi for row-level operations.
SQLite: delegates to reasons_lib.api functions with per-domain db files.
"""

from pathlib import Path
from uuid import UUID

from reasons_service.config import settings


def _is_sqlite() -> bool:
    return settings.db_backend == "sqlite"


# --- PostgreSQL helpers ---

def _conninfo() -> str:
    """Convert SQLAlchemy sync URL to psycopg conninfo."""
    url = settings.database_url_sync
    if "+psycopg" in url:
        url = url.replace("+psycopg", "")
    return url


def _api(domain_id: UUID):
    """Create a PgApi instance for a domain."""
    from reasons_lib.pg import PgApi
    return PgApi(_conninfo(), domain_id)


# --- SQLite helpers ---

def _db_path(domain_id: UUID) -> str:
    """Per-domain SQLite database path for reasons_lib.Storage."""
    path = settings.data_dir / str(domain_id)
    path.mkdir(parents=True, exist_ok=True)
    return str(path / "reasons.db")


# --- Public API (dispatch based on backend) ---

def add_node(
    domain_id: UUID,
    node_id: str,
    text: str,
    sl: str = "",
    cp: str = "",
    unless: str = "",
    label: str = "",
    source: str = "",
    example: str | None = None,
    access_tags: list[str] | None = None,
) -> dict:
    """Add a node to the domain's RMS network."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.add_node(node_id, text, sl=sl, cp=cp, unless=unless,
                             label=label, source=source, example=example,
                             access_tags=access_tags,
                             db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.add_node(node_id, text, sl=sl, cp=cp, unless=unless,
                            label=label, source=source, example=example,
                            access_tags=access_tags)


def update_node(
    domain_id: UUID,
    node_id: str,
    text: str | None = None,
    source: str | None = None,
    example: str | None = None,
) -> dict:
    """Update mutable fields on an existing node."""
    if _is_sqlite():
        from reasons_lib.storage import Storage
        db = _db_path(domain_id)
        store = Storage(db)
        net = store.load()
        if node_id not in net.nodes:
            store.close()
            raise KeyError(f"Node '{node_id}' not found")
        node = net.nodes[node_id]
        if text is not None:
            node.text = text
        if source is not None:
            node.source = source
        if example is not None:
            if node.metadata is None:
                node.metadata = {}
            node.metadata["example"] = example
        store.save(net)
        store.close()
        return {"node_id": node_id, "updated": True}
    import json as _json
    from reasons_service.db.connection import get_sync_session
    from sqlalchemy import text as sa_text
    with get_sync_session() as session:
        row = session.execute(
            sa_text("SELECT metadata FROM rms_nodes WHERE domain_id = :pid AND id = :nid"),
            {"pid": str(domain_id), "nid": node_id},
        ).fetchone()
        if not row:
            raise KeyError(f"Node '{node_id}' not found")
        sets = []
        params: dict = {"pid": str(domain_id), "nid": node_id}
        if text is not None:
            sets.append("text = :text")
            params["text"] = text
        if source is not None:
            sets.append("source = :source")
            params["source"] = source
        if example is not None:
            meta = _json.loads(row[0]) if row[0] else {}
            meta["example"] = example
            sets.append("metadata = :metadata")
            params["metadata"] = _json.dumps(meta)
        if sets:
            session.execute(
                sa_text(f"UPDATE rms_nodes SET {', '.join(sets)} WHERE domain_id = :pid AND id = :nid"),
                params,
            )
            session.commit()
        return {"node_id": node_id, "updated": True}


def retract_node(domain_id: UUID, node_id: str) -> dict:
    """Retract a node and cascade."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.retract_node(node_id, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.retract_node(node_id)


def assert_node(domain_id: UUID, node_id: str) -> dict:
    """Assert a node and cascade restoration."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.assert_node(node_id, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.assert_node(node_id)


def get_status(domain_id: UUID, visible_to: list[str] | None = None) -> dict:
    """Get all nodes with truth values."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.get_status(visible_to=visible_to, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.get_status(visible_to=visible_to)


def show_node(domain_id: UUID, node_id: str, visible_to: list[str] | None = None) -> dict:
    """Get full details for a node. Raises PermissionError if filtered out."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.show_node(node_id, visible_to=visible_to, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.show_node(node_id, visible_to=visible_to)


def explain_node(domain_id: UUID, node_id: str, visible_to: list[str] | None = None) -> dict:
    """Explain why a node is IN or OUT. Raises PermissionError if filtered out."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.explain_node(node_id, visible_to=visible_to, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.explain_node(node_id, visible_to=visible_to)


def trace_assumptions(domain_id: UUID, node_id: str, visible_to: list[str] | None = None) -> dict:
    """Trace backward to find all premises a node rests on. Raises PermissionError if filtered out."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.trace_assumptions(node_id, visible_to=visible_to, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.trace_assumptions(node_id, visible_to=visible_to)


def challenge(
    domain_id: UUID,
    target_id: str,
    reason: str,
    challenge_id: str | None = None,
) -> dict:
    """Challenge a node -- target goes OUT."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.challenge(target_id, reason, challenge_id=challenge_id,
                              db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.challenge(target_id, reason, challenge_id=challenge_id)


def defend(
    domain_id: UUID,
    target_id: str,
    challenge_id: str,
    reason: str,
    defense_id: str | None = None,
) -> dict:
    """Defend a node against a challenge -- target restored."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.defend(target_id, challenge_id, reason,
                           defense_id=defense_id, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.defend(target_id, challenge_id, reason, defense_id=defense_id)


def add_nogood(domain_id: UUID, node_ids: list[str]) -> dict:
    """Record a contradiction and use backtracking to resolve."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.add_nogood(node_ids, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.add_nogood(node_ids)


def export_markdown(domain_id: UUID, status: str | None = None, visible_to: list[str] | None = None) -> str:
    """Export the belief network as markdown, optionally filtered by status."""
    if _is_sqlite() and status is None:
        import reasons_lib.api as rlib
        return rlib.export_markdown(visible_to=visible_to, db_path=_db_path(domain_id))
    nodes_result = list_nodes(domain_id, status=status, visible_to=visible_to)
    nodes = nodes_result.get("nodes", [])
    nodes.sort(key=lambda n: (n.get("truth_value") != "IN", n.get("id", "")))
    lines = [
        "# Belief Registry",
        "",
        "## Claims",
        "",
    ]
    for n in nodes:
        tv = n.get("truth_value", "IN")
        ntype = "OBSERVATION"
        lines.append(f"### {n['id']} [{tv}] {ntype}")
        lines.append(n.get("text", ""))
        if n.get("source"):
            lines.append(f"- Source: {n['source']}")
        lines.append("")
    return "\n".join(lines)


def search(domain_id: UUID, query: str, limit: int = 20, offset: int = 0, visible_to: list[str] | None = None) -> dict:
    """Search nodes by text. Returns up to *limit* results starting at *offset*."""
    terms = [t.lower() for t in query.split() if len(t) > 1]
    if not terms:
        return {"results": [], "count": 0, "limit": limit, "offset": offset}
    nodes_result = list_nodes(domain_id, visible_to=visible_to)
    nodes = nodes_result.get("nodes", [])
    results = []
    for n in nodes:
        text_lower = n.get("text", "").lower()
        id_lower = n.get("id", "").lower()
        score = sum(1 for t in terms if t in text_lower or t in id_lower)
        if score > 0:
            n["_score"] = score
            results.append(n)
    results.sort(key=lambda n: -n.pop("_score"))
    total = len(results)
    results = results[offset:offset + limit] if limit else results[offset:]
    return {"results": results, "count": total, "limit": limit, "offset": offset}


def list_nodes(
    domain_id: UUID,
    status: str | None = None,
    premises_only: bool = False,
    visible_to: list[str] | None = None,
) -> dict:
    """List nodes with optional filters."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.list_nodes(status=status, premises_only=premises_only,
                               visible_to=visible_to,
                               db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.list_nodes(status=status, premises_only=premises_only,
                              visible_to=visible_to)


def compact(domain_id: UUID, budget: int = 500, visible_to: list[str] | None = None) -> str:
    """Generate a token-budgeted summary of the belief network."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.compact(budget=budget, visible_to=visible_to, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.compact(budget=budget, visible_to=visible_to)


def list_gated(domain_id: UUID, visible_to: list[str] | None = None) -> dict:
    """Find OUT beliefs blocked by IN outlist nodes (active gates)."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.list_gated(visible_to=visible_to, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.list_gated(visible_to=visible_to)


def what_if_retract(domain_id: UUID, node_id: str) -> dict:
    """Simulate retracting a node — shows cascade without modifying the database."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.what_if_retract(node_id, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.what_if_retract(node_id)


def what_if_assert(domain_id: UUID, node_id: str) -> dict:
    """Simulate asserting a node — shows cascade without modifying the database."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.what_if_assert(node_id, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.what_if_assert(node_id)


def import_network(domain_id: UUID, network) -> dict:
    """Import a reasons_lib Network into a domain.

    SQLite: saves directly via reasons_lib.Storage.
    PostgreSQL: inserts nodes, justifications, and nogoods via PgApi.

    Returns dict with node_count and nogood_count.
    """
    node_count = len(network.nodes)
    nogood_count = len(network.nogoods)

    if _is_sqlite():
        from reasons_lib.storage import Storage
        db = _db_path(domain_id)
        store = Storage(db)
        store.save(network)
        store.close()
    else:
        with _api(domain_id) as api:
            for node in network.nodes.values():
                api.add_node(
                    node.id, node.text,
                    source=node.source or "",
                )
                if node.truth_value == "OUT":
                    api.retract_node(node.id)

                # Add non-trivial justifications (SL with antecedents)
                for j in node.justifications:
                    if j.type == "SL" and not j.antecedents and not j.outlist:
                        continue  # skip bare SL created by add_node
                    api.add_justification(
                        node.id,
                        sl=",".join(j.antecedents) if j.type == "SL" else "",
                        cp=",".join(j.antecedents) if j.type == "CP" else "",
                        unless=",".join(j.outlist) if j.outlist else "",
                        label=j.label or "",
                    )

            for nogood in network.nogoods:
                api.add_nogood(nogood.nodes)

    return {"node_count": node_count, "nogood_count": nogood_count}


# --- Belief/nogood count helpers (avoids direct rms_nodes SQL) ---

def trace_access_tags(domain_id: UUID, node_id: str, visible_to: list[str] | None = None) -> dict:
    """Trace access tags through the dependency chain for a node."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.trace_access_tags(node_id, visible_to=visible_to, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.trace_access_tags(node_id, visible_to=visible_to)


def set_access_tags(domain_id: UUID, node_id: str, tags: list[str]) -> dict:
    """Set access_tags on an existing node."""
    if _is_sqlite():
        import json as _json
        import sqlite3
        db = _db_path(domain_id)
        conn = sqlite3.connect(db)
        try:
            row = conn.execute("SELECT metadata FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                raise KeyError(f"Node '{node_id}' not found")
            meta = _json.loads(row[0]) if row[0] else {}
            meta["access_tags"] = sorted(set(tags))
            conn.execute("UPDATE nodes SET metadata = ? WHERE id = ?", (_json.dumps(meta), node_id))
            conn.commit()
        finally:
            conn.close()
        return {"node_id": node_id, "access_tags": meta["access_tags"]}
    from reasons_service.db.connection import get_sync_session
    from sqlalchemy import text
    import json as _json
    with get_sync_session() as session:
        row = session.execute(
            text("SELECT metadata FROM rms_nodes WHERE domain_id = :pid AND id = :nid"),
            {"pid": str(domain_id), "nid": node_id},
        ).fetchone()
        if not row:
            raise KeyError(f"Node '{node_id}' not found")
        meta = _json.loads(row[0]) if row[0] else {}
        meta["access_tags"] = sorted(set(tags))
        session.execute(
            text("UPDATE rms_nodes SET metadata = :meta WHERE domain_id = :pid AND id = :nid"),
            {"pid": str(domain_id), "nid": node_id, "meta": _json.dumps(meta)},
        )
        session.commit()
    return {"node_id": node_id, "access_tags": meta["access_tags"]}


def topics(domain_id: UUID, limit: int = 50) -> dict:
    """Extract topics from belief node IDs by word frequency."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.topics(limit=limit, db_path=_db_path(domain_id))
    with _api(domain_id) as api:
        return api.topics(limit=limit)


def count_beliefs(domain_id: UUID, status: str | None = "IN", visible_to: list[str] | None = None) -> int:
    """Count beliefs, optionally filtered by truth_value and access tags."""
    if visible_to is not None:
        result = list_nodes(domain_id, status=status, visible_to=visible_to)
        return result.get("count", len(result.get("nodes", [])))
    if _is_sqlite():
        import sqlite3
        db = _db_path(domain_id)
        if not Path(db).exists():
            return 0
        conn = sqlite3.connect(db)
        try:
            if status:
                count = conn.execute(
                    "SELECT count(*) FROM nodes WHERE truth_value = ?", (status,)
                ).fetchone()[0]
            else:
                count = conn.execute("SELECT count(*) FROM nodes").fetchone()[0]
        except sqlite3.OperationalError:
            count = 0
        finally:
            conn.close()
        return count
    from reasons_service.db.connection import get_sync_session
    from sqlalchemy import text
    with get_sync_session() as session:
        if status:
            return session.execute(
                text("SELECT count(*) FROM rms_nodes WHERE domain_id = :pid AND truth_value = :st"),
                {"pid": str(domain_id), "st": status},
            ).scalar() or 0
        return session.execute(
            text("SELECT count(*) FROM rms_nodes WHERE domain_id = :pid"),
            {"pid": str(domain_id)},
        ).scalar() or 0


def count_nogoods(domain_id: UUID) -> int:
    """Count nogood records for a domain."""
    if _is_sqlite():
        import sqlite3
        db = _db_path(domain_id)
        if not Path(db).exists():
            return 0
        conn = sqlite3.connect(db)
        try:
            count = conn.execute("SELECT count(*) FROM nogoods").fetchone()[0]
        except sqlite3.OperationalError:
            count = 0
        finally:
            conn.close()
        return count
    from reasons_service.db.connection import get_sync_session
    from sqlalchemy import text
    with get_sync_session() as session:
        return session.execute(
            text("SELECT count(*) FROM rms_nogoods WHERE domain_id = :pid"),
            {"pid": str(domain_id)},
        ).scalar() or 0


def search_beliefs_fts(domain_id: UUID, query: str, limit: int = 10, visible_to: list[str] | None = None) -> list[dict]:
    """Search IN beliefs by text. Returns list of dicts with id, text, truth_value, source, source_url."""
    if _is_sqlite():
        import json as _json
        import sqlite3
        db = _db_path(domain_id)
        if not Path(db).exists():
            return []
        from reasons_service.db.search import _get_terms
        terms = _get_terms(query)
        if not terms:
            return []
        fts5_query = " OR ".join(terms)
        fetch_limit = limit * 3 if visible_to is not None else limit
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            try:
                rows = conn.execute(
                    "SELECT n.id, n.text, n.truth_value, n.source, n.metadata "
                    "FROM nodes n "
                    "JOIN nodes_fts f ON f.id = n.id "
                    "WHERE nodes_fts MATCH ? AND n.truth_value = 'IN' "
                    "ORDER BY f.rank "
                    "LIMIT ?",
                    (fts5_query, fetch_limit),
                ).fetchall()
            except sqlite3.OperationalError:
                like_conditions = " OR ".join(f"lower(text) LIKE ?" for _ in terms)
                like_params = [f"%{t}%" for t in terms]
                rows = conn.execute(
                    f"SELECT id, text, truth_value, source, metadata FROM nodes "
                    f"WHERE truth_value = 'IN' AND ({like_conditions}) "
                    f"LIMIT ?",
                    like_params + [fetch_limit],
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()
        results = []
        visible_set = set(visible_to) if visible_to is not None else None
        for r in rows:
            if visible_set is not None:
                meta = _json.loads(r["metadata"]) if r["metadata"] else {}
                tags = meta.get("access_tags", [])
                if tags and not set(tags) <= visible_set:
                    continue
            results.append(
                {"id": r["id"], "text": r["text"], "truth_value": r["truth_value"],
                 "source": r["source"] or "", "source_url": ""}
            )
            if len(results) >= limit:
                break
        return results
    # PostgreSQL: use existing tsvector search
    from reasons_service.db.connection import get_sync_session
    from reasons_service.db.search import fts_clause
    from sqlalchemy import text
    where, order, params = fts_clause("text", query)
    params["pid"] = str(domain_id)
    params["lim"] = limit
    order_clause = f"ORDER BY {order}" if order else ""
    with get_sync_session() as session:
        rows = session.execute(
            text(
                f"SELECT id, text, truth_value, source, source_url "
                f"FROM rms_nodes "
                f"WHERE domain_id = :pid AND truth_value = 'IN' "
                f"AND {where} "
                f"{order_clause} "
                f"LIMIT :lim"
            ),
            params,
        ).all()
    return [
        {"id": r.id, "text": r.text, "truth_value": r.truth_value,
         "source": r.source or "", "source_url": r.source_url or ""}
        for r in rows
    ]


# Keywords that suggest a belief describes a problem, defect, or risk.
_NEGATIVE_TERMS = [
    'bug', 'defect', 'missing', 'fail', 'error', 'broken', 'incorrect',
    'wrong', 'risk', 'gap', 'lack', 'vulnerable', 'insecure', 'stale',
    'outdated', 'deprecated', 'fragile', 'brittle', 'hack', 'workaround',
    'technical debt', 'tech debt', 'not implemented', 'unimplemented',
    'incomplete', 'inconsistent', 'unclear', 'confusing', 'problem',
    'issue', 'concern', 'warning', 'danger', 'threat', 'weakness',
    'limitation', 'constraint', 'bottleneck', 'blocker', 'obstacle',
    'undermines', 'concentrated', 'single point of failure', 'no tests',
    'untested', 'not tested', 'hard-coded', 'hardcoded', 'tight coupling',
    'tightly coupled', 'monolithic', 'legacy', 'unmaintained',
    'worsening', 'decay', 'degradation', 'fragmentation', 'opacity',
    'ungoverned', 'unrecoverable', 'unverifiable', 'deadlock', 'paradox',
]


def list_negative_candidates(domain_id: UUID, visible_to: list[str] | None = None) -> dict:
    """Find IN beliefs whose text matches negative-sentiment keywords.

    Returns candidates only — the chat agent classifies which are genuinely
    negative vs. beliefs that merely describe error-handling mechanisms.
    """
    if _is_sqlite():
        import reasons_lib.api as rlib
        status = rlib.get_status(visible_to=visible_to, db_path=_db_path(domain_id))
        in_nodes = [n for n in status.get("nodes", []) if n.get("truth_value") == "IN"]
        total = len(in_nodes)
        candidates = []
        for n in in_nodes:
            text_lower = n["text"].lower()
            if any(term in text_lower for term in _NEGATIVE_TERMS):
                candidates.append({"id": n["id"], "text": n["text"]})
        candidates.sort(key=lambda c: c["id"])
        return {
            "candidates": candidates,
            "candidate_count": len(candidates),
            "total_in": total,
        }

    # PostgreSQL path
    from reasons_service.db.connection import get_sync_session
    from sqlalchemy import text
    conditions = " OR ".join(
        f"lower(text) LIKE :t{i}" for i in range(len(_NEGATIVE_TERMS))
    )
    params = {f"t{i}": f"%{term}%" for i, term in enumerate(_NEGATIVE_TERMS)}
    params["pid"] = str(domain_id)

    with get_sync_session() as session:
        total = session.execute(
            text(
                "SELECT count(*) FROM rms_nodes "
                "WHERE domain_id = :pid AND truth_value = 'IN'"
            ),
            {"pid": params["pid"]},
        ).scalar()

        rows = session.execute(
            text(
                f"SELECT id, text FROM rms_nodes "
                f"WHERE domain_id = :pid AND truth_value = 'IN' "
                f"AND ({conditions}) "
                f"ORDER BY id"
            ),
            params,
        ).all()

    return {
        "candidates": [{"id": r.id, "text": r.text} for r in rows],
        "candidate_count": len(rows),
        "total_in": total or 0,
    }
