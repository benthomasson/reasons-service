"""Application configuration."""

import os
from pathlib import Path

from pydantic import BaseModel, model_validator


class Settings(BaseModel):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://expert:expert_dev@localhost:5432/reasons_service",
    )
    # Sync URL for LangGraph checkpointer (uses psycopg, not asyncpg)
    database_url_sync: str = os.getenv(
        "DATABASE_URL_SYNC",
        "postgresql+psycopg://expert:expert_dev@localhost:5432/reasons_service",
    )

    @model_validator(mode="after")
    def _derive_sqlite_sync_url(self):
        """Auto-derive sync URL when using SQLite."""
        if self.db_backend == "sqlite" and "psycopg" in self.database_url_sync:
            # User set DATABASE_URL to sqlite but left sync at postgres default
            self.database_url_sync = self.database_url.replace(
                "sqlite+aiosqlite://", "sqlite://"
            )
        return self

    @property
    def db_backend(self) -> str:
        """'sqlite' or 'postgresql' based on DATABASE_URL."""
        if self.database_url.startswith("sqlite"):
            return "sqlite"
        return "postgresql"

    @property
    def data_dir(self) -> Path:
        """Directory for SQLite data files. Extracted from the database URL path."""
        if self.db_backend != "sqlite":
            return Path("data")
        # sqlite+aiosqlite:///data/expert.db → data/
        url = self.database_url
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if url.startswith(prefix):
                url = url[len(prefix):]
                break
        return Path(url).parent
    # Vertex AI configuration (shared with agents-python)
    google_cloud_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    google_cloud_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    default_model: str = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-20250514")
    # Ollama configuration (optional — for local model serving)
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    # LangFuse tracing (optional — disabled when secret_key is empty)
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
    # Auth (optional — when unset, dev mode allows anonymous access)
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    secret_key: str = os.getenv("SECRET_KEY", "dev-insecure-key")
    api_key: str = os.getenv("REASONS_SERVICE_API_KEY", os.getenv("EXPERT_SERVICE_API_KEY", ""))
    mcp_issuer_url: str = os.getenv("MCP_ISSUER_URL", "https://reasons.reasonsforge.com/mcp")

    @property
    def llm_enabled(self) -> bool:
        """Whether LLM-powered endpoints (chat, ask+synthesis, pipelines) are enabled.

        Set EXPERT_LLM=false for data-only mode where clients bring their own LLM.
        """
        return os.getenv("REASONS_LLM", os.getenv("EXPERT_LLM", "true")).lower() not in ("false", "0", "no")

    @property
    def hub_mode(self) -> bool:
        """Public hub mode — disables login UI and authenticated domain pages."""
        return os.getenv("REASONS_HUB_MODE", os.getenv("EXPERT_HUB_MODE", "false")).lower() in ("true", "1", "yes")


settings = Settings()
