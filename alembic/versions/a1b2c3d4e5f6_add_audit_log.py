"""add_audit_log

Revision ID: a1b2c3d4e5f6
Revises: f7a5e9b1d456
Create Date: 2026-09-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f7a5e9b1d456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_log',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('actor', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('resource_type', sa.String(), nullable=False),
        sa.Column('resource_id', sa.String(), nullable=True),
        sa.Column('domain_id', sa.UUID(), nullable=True),
        sa.Column('before_state', JSONB, nullable=True),
        sa.Column('after_state', JSONB, nullable=True),
        sa.Column('metadata', JSONB, nullable=True),
    )
    op.create_index('ix_audit_log_domain_id', 'audit_log', ['domain_id'])
    op.create_index('ix_audit_log_actor', 'audit_log', ['actor'])
    op.create_index('ix_audit_log_action', 'audit_log', ['action'])
    op.create_index('ix_audit_log_resource_type', 'audit_log', ['resource_type'])
    op.create_index('ix_audit_log_timestamp', 'audit_log', ['timestamp'])


def downgrade() -> None:
    op.drop_index('ix_audit_log_timestamp')
    op.drop_index('ix_audit_log_resource_type')
    op.drop_index('ix_audit_log_action')
    op.drop_index('ix_audit_log_actor')
    op.drop_index('ix_audit_log_domain_id')
    op.drop_table('audit_log')
