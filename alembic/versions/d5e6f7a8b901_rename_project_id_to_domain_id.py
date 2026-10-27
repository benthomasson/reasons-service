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

    bind.execute(sa.text("""
        ALTER TABLE rms_nodes RENAME COLUMN project_id TO domain_id;
        ALTER TABLE rms_justifications RENAME COLUMN project_id TO domain_id;
        ALTER TABLE rms_nogoods RENAME COLUMN project_id TO domain_id;
        ALTER TABLE rms_propagation_log RENAME COLUMN project_id TO domain_id;
        ALTER TABLE rms_network_meta RENAME COLUMN project_id TO domain_id;
    """))

    bind.execute(sa.text("""
        ALTER INDEX IF EXISTS idx_rms_nodes_project RENAME TO idx_rms_nodes_domain;
        ALTER INDEX IF EXISTS idx_rms_nogoods_project RENAME TO idx_rms_nogoods_domain;
        ALTER INDEX IF EXISTS idx_rms_log_project RENAME TO idx_rms_log_domain;
    """))


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
