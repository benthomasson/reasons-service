"""Baseline — create all tables from current models.

Revision ID: 0000
Revises:
Create Date: 2026-09-26

For fresh databases (e.g. OpenShift). Creates all tables as defined
in the current models, then subsequent migrations run as no-ops since
the schema is already up to date.
"""
from typing import Sequence, Union

from alembic import op
from reasons_service.db.models import Base

revision: str = "0000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pgvector_enabled(bind) -> bool:
    """Check if the vector extension is already enabled in this database."""
    from sqlalchemy import text
    result = bind.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    )
    return result.scalar() is not None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    skip_embeddings = dialect == "postgresql" and not _pgvector_enabled(bind)
    tables = [t for t in Base.metadata.sorted_tables
              if not (skip_embeddings and t.name == "embeddings")]
    Base.metadata.create_all(bind, tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
