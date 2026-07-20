"""Database connection management — supports PostgreSQL and SQLite."""

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

from reasons_service.config import settings

_is_sqlite = settings.db_backend == "sqlite"

if _is_sqlite:
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Enable WAL and foreign keys on every async SQLite connection
    @event.listens_for(engine.sync_engine, "connect")
    def _async_sqlite_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    engine = create_async_engine(settings.database_url, echo=False,
                                 pool_size=5, max_overflow=5)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for LangGraph graph nodes (which are synchronous)
_sync_engine = None


def get_sync_engine():
    """Lazy-initialized sync engine for graph nodes."""
    global _sync_engine
    if _sync_engine is None:
        if _is_sqlite:
            _sync_engine = create_engine(
                settings.database_url_sync,
                echo=False,
                connect_args={"check_same_thread": False},
            )
            # Enable WAL and foreign keys on every SQLite connection
            @event.listens_for(_sync_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        else:
            _sync_engine = create_engine(settings.database_url_sync, echo=False,
                                         pool_size=5, max_overflow=5)
    return _sync_engine


def get_sync_session() -> SyncSession:
    """Create a sync database session for use in graph nodes."""
    return SyncSession(get_sync_engine())


async def get_session():
    """FastAPI dependency for async database sessions."""
    async with async_session() as session:
        yield session


def init_db():
    """Create all tables from SQLAlchemy metadata (SQLite only).

    On PostgreSQL, tables are created via schema.sql in docker-compose.
    """
    if not _is_sqlite:
        return
    # Ensure the data directory exists
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    from reasons_service.db.models import Base
    from sqlalchemy import text as sa_text
    eng = get_sync_engine()
    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.execute(sa_text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS source_chunks_fts "
            "USING fts5(id, text, content=source_chunks, content_rowid=id)"
        ))
        for trigger in [
            "CREATE TRIGGER IF NOT EXISTS source_chunks_ai AFTER INSERT ON source_chunks BEGIN "
            "INSERT INTO source_chunks_fts(rowid, id, text) VALUES (new.id, new.id, new.text); END",
            "CREATE TRIGGER IF NOT EXISTS source_chunks_ad AFTER DELETE ON source_chunks BEGIN "
            "INSERT INTO source_chunks_fts(source_chunks_fts, rowid, id, text) VALUES ('delete', old.id, old.id, old.text); END",
            "CREATE TRIGGER IF NOT EXISTS source_chunks_au AFTER UPDATE ON source_chunks BEGIN "
            "INSERT INTO source_chunks_fts(source_chunks_fts, rowid, id, text) VALUES ('delete', old.id, old.id, old.text); "
            "INSERT INTO source_chunks_fts(rowid, id, text) VALUES (new.id, new.id, new.text); END",
        ]:
            conn.execute(sa_text(trigger))
        conn.execute(sa_text("INSERT INTO source_chunks_fts(source_chunks_fts) VALUES ('rebuild')"))
        conn.commit()
