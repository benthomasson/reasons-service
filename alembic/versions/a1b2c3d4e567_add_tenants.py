"""add_tenants

Revision ID: a1b2c3d4e567
Revises: f7a5e9b1d456
Create Date: 2026-09-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e567'
down_revision: Union[str, None] = 'f7a5e9b1d456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create tenants table
    op.create_table(
        'tenants',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('name', sa.String, nullable=False, unique=True),
        sa.Column('display_name', sa.String),
        sa.Column('type', sa.String, nullable=False, server_default='organization'),
        sa.Column('public', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create tenant_members table
    op.create_table(
        'tenant_members',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', sa.String, sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_email', sa.String, sa.ForeignKey('users.email', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String, nullable=False, server_default='reader'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('tenant_id', 'user_email'),
    )

    # Insert default tenant
    op.execute("INSERT INTO tenants (id, name, display_name, type) VALUES ('default', 'default', 'Default', 'organization')")

    # Add tenant_id to users
    op.add_column('users', sa.Column('tenant_id', sa.String, sa.ForeignKey('tenants.id'), nullable=True))
    op.execute("UPDATE users SET tenant_id = 'default'")

    # Enroll existing users as tenant_admin in default tenant
    op.execute(
        "INSERT INTO tenant_members (id, tenant_id, user_email, role) "
        "SELECT gen_random_uuid(), 'default', email, 'tenant_admin' FROM users"
    )

    # Add tenant_id to domains
    op.add_column('domains', sa.Column('tenant_id', sa.String, sa.ForeignKey('tenants.id'), nullable=True))
    op.execute("UPDATE domains SET tenant_id = 'default'")

    # Replace global unique(name) with per-tenant unique(tenant_id, name)
    op.drop_constraint('domains_name_key', 'domains', type_='unique')
    op.create_unique_constraint('uq_domains_tenant_name', 'domains', ['tenant_id', 'name'])
    op.create_index('ix_domains_tenant', 'domains', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_domains_tenant', 'domains')
    op.drop_constraint('uq_domains_tenant_name', 'domains', type_='unique')
    op.create_unique_constraint('domains_name_key', 'domains', ['name'])
    op.drop_column('domains', 'tenant_id')
    op.drop_column('users', 'tenant_id')
    op.drop_table('tenant_members')
    op.drop_table('tenants')
