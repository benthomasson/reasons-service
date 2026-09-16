"""add_proposal_snapshot_result_columns

Revision ID: e6f4d8a0c345
Revises: d5e3c7f9b234
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'e6f4d8a0c345'
down_revision: Union[str, None] = 'd5e3c7f9b234'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('proposals', sa.Column('snapshot_json', JSONB, nullable=True))
    op.add_column('proposals', sa.Column('result_json', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('proposals', 'result_json')
    op.drop_column('proposals', 'snapshot_json')
