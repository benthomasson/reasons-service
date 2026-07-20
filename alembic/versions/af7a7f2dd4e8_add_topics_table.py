"""add_topics_table

Revision ID: af7a7f2dd4e8
Revises: 0001
Create Date: 2026-06-17 10:53:26.241773
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'af7a7f2dd4e8'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('topics',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('belief_count', sa.Integer(), nullable=True),
        sa.Column('curated', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'name'),
    )


def downgrade() -> None:
    op.drop_table('topics')
