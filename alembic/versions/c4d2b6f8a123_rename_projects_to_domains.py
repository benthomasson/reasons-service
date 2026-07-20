"""rename_projects_to_domains

Revision ID: c4d2b6f8a123
Revises: b3c1a5e7f912
Create Date: 2026-07-20 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c4d2b6f8a123'
down_revision: Union[str, None] = 'b3c1a5e7f912'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All tables that have a project_id FK column
_FK_TABLES = [
    "sources",
    "entries",
    "claims",
    "nogoods",
    "assessments",
    "pipeline_runs",
    "embeddings",
    "rms_nodes",
    "rms_justifications",
    "rms_nogoods",
    "rms_propagation_log",
    "rms_network_meta",
    "source_chunks",
    "topics",
]


def upgrade() -> None:
    op.rename_table("projects", "domains")
    op.alter_column("domains", "domain", new_column_name="description")
    for table in _FK_TABLES:
        op.alter_column(table, "project_id", new_column_name="domain_id")
    op.alter_column("entry_sources", "entry_project_id", new_column_name="entry_domain_id")


def downgrade() -> None:
    op.alter_column("entry_sources", "entry_domain_id", new_column_name="entry_project_id")
    for table in reversed(_FK_TABLES):
        op.alter_column(table, "domain_id", new_column_name="project_id")
    op.alter_column("domains", "description", new_column_name="domain")
    op.rename_table("domains", "projects")
