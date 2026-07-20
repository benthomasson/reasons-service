"""LangGraph checkpointer setup."""

from reasons_service.config import settings


def get_checkpointer():
    """Create a checkpointer for LangGraph graphs.

    PostgreSQL: PostgresSaver with persistent state.
    SQLite: MemorySaver (in-memory, ephemeral — state lost on restart).
    """
    if settings.db_backend == "sqlite":
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()
    from langgraph.checkpoint.postgres import PostgresSaver
    checkpointer = PostgresSaver.from_conn_string(settings.database_url_sync)
    checkpointer.setup()
    return checkpointer
