"""Add tasks table for background job processing.

Revision ID: f8a9b0c1d234
Revises: e7f8a9b0c123
Create Date: 2026-10-28
"""

from alembic import op
import sqlalchemy as sa

revision = "f8a9b0c1d234"
down_revision = "e7f8a9b0c123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'tasks'")
    ).fetchone()
    if exists:
        return

    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", sa.Uuid(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("config", sa.JSON, server_default="{}"),
        sa.Column("progress", sa.JSON, server_default="{}"),
        sa.Column("result", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("created_by", sa.String),
        sa.Column("job_name", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tasks_domain_status", "tasks", ["domain_id", "status"])
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_tasks_created_at")
    op.drop_index("ix_tasks_domain_status")
    op.drop_table("tasks")
