-- Reasons Service Schema (PostgreSQL 16)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'reader' CHECK (role IN ('admin', 'editor', 'reader')),
    display_name TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    config JSONB DEFAULT '{}',
    public BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    url TEXT,
    slug TEXT NOT NULL,
    content TEXT NOT NULL,
    word_count INT,
    fetched_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(domain_id, slug)
);

CREATE TABLE IF NOT EXISTS entries (
    id TEXT NOT NULL,
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    source_id UUID REFERENCES sources(id),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, domain_id)
);

CREATE TABLE IF NOT EXISTS entry_sources (
    entry_id TEXT NOT NULL,
    entry_domain_id UUID NOT NULL,
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    FOREIGN KEY (entry_id, entry_domain_id) REFERENCES entries(id, domain_id) ON DELETE CASCADE,
    UNIQUE(entry_id, entry_domain_id, source_id)
);

CREATE TABLE IF NOT EXISTS summaries (
    id TEXT NOT NULL,
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    source_id UUID REFERENCES sources(id),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, domain_id)
);

CREATE TABLE IF NOT EXISTS summary_sources (
    summary_id TEXT NOT NULL,
    summary_domain_id UUID NOT NULL,
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    FOREIGN KEY (summary_id, summary_domain_id) REFERENCES summaries(id, domain_id) ON DELETE CASCADE,
    UNIQUE(summary_id, summary_domain_id, source_id)
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT NOT NULL,
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    status TEXT DEFAULT 'IN' CHECK (status IN ('IN', 'OUT', 'STALE', 'PROPOSED')),
    source TEXT,
    source_hash TEXT,
    review_status TEXT DEFAULT 'pending' CHECK (review_status IN ('pending', 'accepted', 'rejected')),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, domain_id)
);

CREATE TABLE IF NOT EXISTS nogoods (
    id TEXT NOT NULL,
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    resolution TEXT,
    claim_ids JSONB,
    discovered_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    PRIMARY KEY (id, domain_id)
);

CREATE TABLE IF NOT EXISTS assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    assessment_type TEXT NOT NULL CHECK (assessment_type IN ('exam', 'coverage')),
    input_data JSONB,
    results JSONB NOT NULL,
    score JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    graph_name TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    status TEXT DEFAULT 'running' CHECK (status IN ('running', 'paused', 'completed', 'failed')),
    progress JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error TEXT
);

CREATE TABLE IF NOT EXISTS embeddings (
    id SERIAL PRIMARY KEY,
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    label TEXT,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- RMS (Reason Maintenance System) tables
CREATE TABLE IF NOT EXISTS rms_nodes (
    id TEXT NOT NULL,
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    truth_value TEXT NOT NULL DEFAULT 'IN' CHECK (truth_value IN ('IN', 'OUT')),
    source TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    source_hash TEXT DEFAULT '',
    date TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, domain_id)
);

CREATE TABLE IF NOT EXISTS rms_justifications (
    id SERIAL PRIMARY KEY,
    node_id TEXT NOT NULL,
    domain_id UUID NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('SL', 'CP')),
    antecedents JSONB NOT NULL DEFAULT '[]',
    outlist JSONB NOT NULL DEFAULT '[]',
    label TEXT DEFAULT '',
    FOREIGN KEY (node_id, domain_id) REFERENCES rms_nodes(id, domain_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rms_nogoods (
    id TEXT NOT NULL,
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    nodes JSONB NOT NULL DEFAULT '[]',
    discovered TEXT DEFAULT '',
    resolution TEXT DEFAULT '',
    PRIMARY KEY (id, domain_id)
);

CREATE TABLE IF NOT EXISTS rms_propagation_log (
    id SERIAL PRIMARY KEY,
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rms_network_meta (
    key TEXT NOT NULL,
    domain_id UUID NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (key, domain_id)
);

-- MCP OAuth token persistence
CREATE TABLE IF NOT EXISTS mcp_clients (
    client_id TEXT PRIMARY KEY,
    client_data JSONB NOT NULL,
    is_open BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mcp_access_tokens (
    token TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes JSONB DEFAULT '[]',
    expires_at INT,
    resource TEXT,
    subject TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_mcp_access_tokens_client_subject
    ON mcp_access_tokens(client_id, subject);

CREATE TABLE IF NOT EXISTS mcp_refresh_tokens (
    token TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes JSONB DEFAULT '[]',
    expires_at INT,
    subject TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Source document chunks for FTS RAG
CREATE TABLE IF NOT EXISTS source_chunks (
    id SERIAL PRIMARY KEY,
    domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    section TEXT DEFAULT '',
    text TEXT NOT NULL,
    UNIQUE(source_id, chunk_index)
);

-- Full-text search indexes
CREATE INDEX IF NOT EXISTS idx_entries_fts ON entries
    USING gin(to_tsvector('english', coalesce(title, '') || ' ' || content));
CREATE INDEX IF NOT EXISTS idx_claims_fts ON claims
    USING gin(to_tsvector('english', text));
CREATE INDEX IF NOT EXISTS idx_rms_nodes_fts ON rms_nodes
    USING gin(to_tsvector('english', text));

CREATE INDEX IF NOT EXISTS idx_source_chunks_domain ON source_chunks(domain_id);
CREATE INDEX IF NOT EXISTS idx_source_chunks_fts ON source_chunks
    USING gin(to_tsvector('english', text));

-- Common query indexes
CREATE INDEX IF NOT EXISTS idx_sources_domain ON sources(domain_id);
CREATE INDEX IF NOT EXISTS idx_entries_domain ON entries(domain_id);
CREATE INDEX IF NOT EXISTS idx_entries_topic ON entries(domain_id, topic);
CREATE INDEX IF NOT EXISTS idx_claims_domain ON claims(domain_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(domain_id, status);
CREATE INDEX IF NOT EXISTS idx_rms_nodes_domain ON rms_nodes(domain_id);
CREATE INDEX IF NOT EXISTS idx_rms_nodes_status ON rms_nodes(domain_id, truth_value);
CREATE INDEX IF NOT EXISTS idx_rms_justifications_node ON rms_justifications(node_id, domain_id);
CREATE INDEX IF NOT EXISTS idx_rms_nogoods_domain ON rms_nogoods(domain_id);
CREATE INDEX IF NOT EXISTS idx_rms_log_domain ON rms_propagation_log(domain_id);
CREATE INDEX IF NOT EXISTS idx_rms_justifications_antecedents ON rms_justifications USING gin(antecedents);
CREATE INDEX IF NOT EXISTS idx_rms_justifications_outlist ON rms_justifications USING gin(outlist);
CREATE INDEX IF NOT EXISTS idx_pipeline_domain ON pipeline_runs(domain_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_domain ON embeddings(domain_id);
CREATE INDEX IF NOT EXISTS idx_entry_sources_entry ON entry_sources(entry_id, entry_domain_id);
CREATE INDEX IF NOT EXISTS idx_entry_sources_source ON entry_sources(source_id);
CREATE INDEX IF NOT EXISTS idx_summaries_domain ON summaries(domain_id);
CREATE INDEX IF NOT EXISTS idx_summaries_topic ON summaries(domain_id, topic);
CREATE INDEX IF NOT EXISTS idx_summary_sources_summary ON summary_sources(summary_id, summary_domain_id);
CREATE INDEX IF NOT EXISTS idx_summary_sources_source ON summary_sources(source_id);
