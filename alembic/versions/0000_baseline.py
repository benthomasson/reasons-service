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


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        try:
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:
            pass
    tables = [t for t in Base.metadata.sorted_tables if t.name != "embeddings"]
    Base.metadata.create_all(bind, tables=tables)
    # Create embeddings table only if pgvector extension is available
    embeddings = Base.metadata.tables.get("embeddings")
    if embeddings is not None:
        try:
            Base.metadata.create_all(bind, tables=[embeddings])
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
