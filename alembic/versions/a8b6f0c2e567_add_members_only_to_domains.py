"""add_members_only_to_domains

Revision ID: a8b6f0c2e567
Revises: f7a5e9b1d456
Create Date: 2026-09-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b6f0c2e567"
down_revision: Union[str, None] = "f7a5e9b1d456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("domains", sa.Column("members_only", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("domains", "members_only")
