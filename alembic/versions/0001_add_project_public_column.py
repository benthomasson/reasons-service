"""Add public column to projects table

Revision ID: 0001
Revises:
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("public", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("projects", "public")
