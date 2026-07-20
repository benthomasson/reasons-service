"""add_visible_tags_to_users

Revision ID: b3c1a5e7f912
Revises: af7a7f2dd4e8
Create Date: 2026-06-23 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3c1a5e7f912'
down_revision: Union[str, None] = 'af7a7f2dd4e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('visible_tags', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'visible_tags')
