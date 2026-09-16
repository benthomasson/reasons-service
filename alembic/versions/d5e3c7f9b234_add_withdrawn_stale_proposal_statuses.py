"""add_withdrawn_stale_proposal_statuses

Revision ID: d5e3c7f9b234
Revises: c4d2b6f8a123
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd5e3c7f9b234'
down_revision: Union[str, None] = 'c4d2b6f8a123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE proposals DROP CONSTRAINT IF EXISTS proposals_status_check")
    op.execute(
        "ALTER TABLE proposals ADD CONSTRAINT proposals_status_check "
        "CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn', 'stale'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE proposals DROP CONSTRAINT IF EXISTS proposals_status_check")
    op.execute(
        "ALTER TABLE proposals ADD CONSTRAINT proposals_status_check "
        "CHECK (status IN ('pending', 'approved', 'rejected'))"
    )
