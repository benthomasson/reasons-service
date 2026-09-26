"""merge_heads

Revision ID: 9f2d0422d685
Revises: a1b2c3d4e567, a8b6f0c2e567, b2c3d4e5f678
Create Date: 2026-09-25 22:20:20.011094
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f2d0422d685'
down_revision: Union[str, None] = ('a1b2c3d4e567', 'a8b6f0c2e567', 'b2c3d4e5f678')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
