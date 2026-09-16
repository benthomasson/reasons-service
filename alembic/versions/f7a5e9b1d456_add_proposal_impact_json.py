"""add_proposal_impact_json

Revision ID: f7a5e9b1d456
Revises: e6f4d8a0c345
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'f7a5e9b1d456'
down_revision: Union[str, None] = 'e6f4d8a0c345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('proposals', sa.Column('impact_json', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('proposals', 'impact_json')
