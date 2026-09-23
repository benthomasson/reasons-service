import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from reasons_service.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Read database URL from environment (not settings, which may have wrong defaults)
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL environment variable not set")

config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata

_EXCLUDED_PREFIXES = ("rms_",)


def include_name(name, type_, parent_names):
    if type_ == "table" and any(name.startswith(p) for p in _EXCLUDED_PREFIXES):
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=False,  # SQLite offline mode doesn't support literal_binds
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


# Use synchronous SQLite URL for alembic (not aiosqlite)
is_sqlite = db_url and "sqlite" in db_url.lower()
if is_sqlite:
    # Convert aiosqlite URL to sync sqlite URL
    sync_url = db_url.replace("sqlite+aiosqlite://", "sqlite:///")
    config.set_main_option("sqlalchemy.url", sync_url)
    print(f"Converted to sync SQLite: {sync_url}")

run_migrations_online()
