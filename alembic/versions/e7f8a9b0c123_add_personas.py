"""Add personas tables.

Revision ID: e7f8a9b0c123
Revises: d5e6f7a8b901
Create Date: 2026-10-27

Personas are named collections of domains for multi-domain chat.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7f8a9b0c123"
down_revision: Union[str, None] = "d5e6f7a8b901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS personas (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            system_prompt TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS persona_domains (
            persona_id UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
            domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
            UNIQUE(persona_id, domain_id)
        )
    """))

    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_persona_domains_persona ON persona_domains(persona_id);
        CREATE INDEX IF NOT EXISTS idx_persona_domains_domain ON persona_domains(domain_id);
    """))

    bind.execute(sa.text("""
        ALTER TABLE chat_conversations
        ADD COLUMN IF NOT EXISTS persona_id UUID REFERENCES personas(id) ON DELETE SET NULL
    """))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    bind.execute(sa.text(
        "ALTER TABLE chat_conversations DROP COLUMN IF EXISTS persona_id"
    ))
    op.drop_table("persona_domains")
    op.drop_table("personas")
