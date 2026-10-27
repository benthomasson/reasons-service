"""Add RMS tables matching ftl-reasons SCHEMA constant.

Revision ID: c4d5e6f7a890
Revises: 9f2d0422d685
Create Date: 2026-10-27

Creates rms_nodes, rms_justifications, rms_nogoods, rms_propagation_log,
and rms_network_meta with domain_id (as expected by ftl-reasons) and all
timestamp columns (updated_at, reviewed_at, verified_at, retracted_at).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4d5e6f7a890"
down_revision: Union[str, None] = "9f2d0422d685"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS rms_nodes (
            id TEXT NOT NULL,
            domain_id UUID NOT NULL,
            text TEXT NOT NULL,
            truth_value TEXT NOT NULL DEFAULT 'IN' CHECK (truth_value IN ('IN', 'OUT')),
            source TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            source_hash TEXT DEFAULT '',
            date TEXT DEFAULT '',
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ,
            reviewed_at TIMESTAMPTZ,
            verified_at TIMESTAMPTZ,
            retracted_at TIMESTAMPTZ,
            PRIMARY KEY (id, domain_id)
        )
    """))

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS rms_justifications (
            id SERIAL PRIMARY KEY,
            node_id TEXT NOT NULL,
            domain_id UUID NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('SL', 'CP')),
            antecedents JSONB NOT NULL DEFAULT '[]',
            outlist JSONB NOT NULL DEFAULT '[]',
            label TEXT DEFAULT '',
            FOREIGN KEY (node_id, domain_id) REFERENCES rms_nodes(id, domain_id) ON DELETE CASCADE
        )
    """))

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS rms_nogoods (
            id TEXT NOT NULL,
            domain_id UUID NOT NULL,
            nodes JSONB NOT NULL DEFAULT '[]',
            discovered TEXT DEFAULT '',
            resolution TEXT DEFAULT '',
            PRIMARY KEY (id, domain_id)
        )
    """))

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS rms_propagation_log (
            id SERIAL PRIMARY KEY,
            domain_id UUID NOT NULL,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            value TEXT NOT NULL
        )
    """))

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS rms_network_meta (
            key TEXT NOT NULL,
            domain_id UUID NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (key, domain_id)
        )
    """))

    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_rms_nodes_domain ON rms_nodes(domain_id);
        CREATE INDEX IF NOT EXISTS idx_rms_nodes_status ON rms_nodes(domain_id, truth_value);
        CREATE INDEX IF NOT EXISTS idx_rms_justifications_node ON rms_justifications(node_id, domain_id);
        CREATE INDEX IF NOT EXISTS idx_rms_nogoods_domain ON rms_nogoods(domain_id);
        CREATE INDEX IF NOT EXISTS idx_rms_log_domain ON rms_propagation_log(domain_id);
        CREATE INDEX IF NOT EXISTS idx_rms_nodes_fts ON rms_nodes USING gin(to_tsvector('english', text));
        CREATE INDEX IF NOT EXISTS idx_rms_justifications_antecedents ON rms_justifications USING gin(antecedents);
        CREATE INDEX IF NOT EXISTS idx_rms_justifications_outlist ON rms_justifications USING gin(outlist);
    """))


def downgrade() -> None:
    op.drop_table("rms_network_meta")
    op.drop_table("rms_propagation_log")
    op.drop_table("rms_nogoods")
    op.drop_table("rms_justifications")
    op.drop_table("rms_nodes")
