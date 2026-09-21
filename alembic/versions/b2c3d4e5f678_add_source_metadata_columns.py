"""add_source_metadata_columns

Revision ID: b2c3d4e5f678
Revises: a1b2c3d4e5f6
Create Date: 2026-09-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f678'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sources', sa.Column('title', sa.String(), nullable=True))
    op.add_column('sources', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('sources', sa.Column('author', sa.String(), nullable=True))
    op.add_column('sources', sa.Column('content_type', sa.String(), nullable=True))
    op.add_column('sources', sa.Column('added_by', sa.String(), nullable=True))
    op.add_column('sources', sa.Column('license', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('sources', 'license')
    op.drop_column('sources', 'added_by')
    op.drop_column('sources', 'content_type')
    op.drop_column('sources', 'author')
    op.drop_column('sources', 'description')
    op.drop_column('sources', 'title')
