"""Embedding generation and storage using fastembed + pgvector.

Requires pgvector extension — skipped entirely on SQLite.
"""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy import text as sa_text

from reasons_service.config import settings
from reasons_service.db.connection import get_sync_session
from reasons_service.db.models import Embedding, Entry, Source
from reasons_service.rms import api as rms_api

EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# Lazy-loaded model singleton
_model = None


def _get_model():
    from fastembed import TextEmbedding
    global _model
    if _model is None:
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def build_embeddings(domain_id: UUID) -> dict[str, int]:
    """Build embeddings for all entries, beliefs, and sources in a domain.

    Requires pgvector — returns empty counts on SQLite.
    """
    if settings.db_backend == "sqlite" or Embedding is None:
        return {"entries": 0, "beliefs": 0, "sources": 0}

    model = _get_model()

    with get_sync_session() as session:
        session.execute(
            delete(Embedding).where(Embedding.domain_id == domain_id)
        )

        items = []

        entries = session.execute(
            select(Entry.id, Entry.title, Entry.content)
            .where(Entry.domain_id == domain_id)
        ).all()
        for e in entries:
            text = f"{e.title}. {e.content}" if e.title else e.content
            items.append(("entries", e.id, e.title or e.id, text))

        beliefs = session.execute(
            sa_text("SELECT id, text FROM rms_nodes WHERE domain_id = :pid"),
            {"pid": str(domain_id)},
        ).all()
        for b in beliefs:
            items.append(("beliefs", b.id, b.text[:80], b.text))

        sources = session.execute(
            select(Source.slug, Source.content)
            .where(Source.domain_id == domain_id)
        ).all()
        for s in sources:
            text = f"{s.slug}. {s.content[:2000]}"
            items.append(("sources", s.slug, s.slug, text))

        if not items:
            return {"entries": 0, "beliefs": 0, "sources": 0}

        texts = [item[3] for item in items]
        vectors = list(model.embed(texts))

        for (source_table, source_id, label, _text), vector in zip(items, vectors):
            session.add(Embedding(
                domain_id=domain_id,
                source_table=source_table,
                source_id=source_id,
                label=label,
                embedding=vector.tolist(),
            ))

        session.commit()

    counts = {"entries": len(entries), "beliefs": len(beliefs), "sources": len(sources)}
    return counts


def embed_query(query: str) -> list[float]:
    """Embed a single query string. Returns vector as list of floats."""
    model = _get_model()
    vectors = list(model.embed([query]))
    return vectors[0].tolist()
