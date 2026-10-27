"""Rename project_id to domain_id on rms_* tables.

Revision ID: d5e6f7a8b901
Revises: c4d5e6f7a890
Create Date: 2026-10-27

Aligns with ftl-reasons PR #273 which standardized on domain_id.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d5e6f7a8b901"
down_revision: Union[str, None] = "c4d5e6f7a890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in ("rms_nodes", "rms_justifications", "rms_nogoods",
                   "rms_propagation_log", "rms_network_meta"):
        has_col = bind.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'project_id'"
        ), {"t": table}).fetchone()
        if has_col:
            bind.execute(sa.text(
                f"ALTER TABLE {table} RENAME COLUMN project_id TO domain_id"
            ))

    for old, new in (("idx_rms_nodes_project", "idx_rms_nodes_domain"),
                     ("idx_rms_nogoods_project", "idx_rms_nogoods_domain"),
                     ("idx_rms_log_project", "idx_rms_log_domain")):
        has_new = bind.execute(sa.text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :n"
        ), {"n": new}).fetchone()
        if has_new:
            bind.execute(sa.text(f"DROP INDEX IF EXISTS {old}"))
        else:
            bind.execute(sa.text(
                f"ALTER INDEX IF EXISTS {old} RENAME TO {new}"
            ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    bind.execute(sa.text("""
        ALTER TABLE rms_nodes RENAME COLUMN domain_id TO project_id;
        ALTER TABLE rms_justifications RENAME COLUMN domain_id TO project_id;
        ALTER TABLE rms_nogoods RENAME COLUMN domain_id TO project_id;
        ALTER TABLE rms_propagation_log RENAME COLUMN domain_id TO project_id;
        ALTER TABLE rms_network_meta RENAME COLUMN domain_id TO project_id;
    """))

    bind.execute(sa.text("""
        ALTER INDEX IF EXISTS idx_rms_nodes_domain RENAME TO idx_rms_nodes_project;
        ALTER INDEX IF EXISTS idx_rms_nogoods_domain RENAME TO idx_rms_nogoods_project;
        ALTER INDEX IF EXISTS idx_rms_log_domain RENAME TO idx_rms_log_project;
    """))
