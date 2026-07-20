# Reasons Service

Serves pre-built Reasons knowledge bases over REST API, MCP, and web UI. Knowledge bases are built with [Reasons Forge](https://github.com/benthomasson/reasonsforge) and loaded into this service for querying.

Designed for users who need access to domain knowledge bases without installing anything — connect Claude Desktop to the hosted MCP server at reasonsforge.com.

## What It Does

```
┌──────────────────┐
│  Reasons Forge   │  Build knowledge bases
│  (separate tool) │  from documentation
└────────┬─────────┘
         │ import
         ▼
┌──────────────────────────────────────────────┐
│              Reasons Service                 │
│                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │
│  │ Search  │  │  Chat   │  │ MCP Server  │  │
│  │ FTS +   │  │ LLM     │  │ Claude      │  │
│  │ vector  │  │ synthesis│  │ Desktop     │  │
│  └─────────┘  └─────────┘  └─────────────┘  │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │           PostgreSQL + pgvector      │    │
│  │  beliefs · entries · sources · topics │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

## Quick Start

```bash
# Clone and install
git clone https://github.com/benthomasson/reasons-service.git
cd reasons-service
uv venv && uv pip install -e .

# Start PostgreSQL + service
docker compose up -d

# Open web UI
open http://localhost:8000

# Import a pre-built knowledge base
python scripts/load_reasons_db.py ~/path/to/reasons.db project-name --domain "Your domain"
python scripts/build_embeddings.py --project-id <uuid>
```

## MCP Server

The MCP server at `/mcp` exposes these tools to Claude Desktop and Claude Code:

| Tool | Description |
|------|-------------|
| `deep_search` | IDF-ranked search across beliefs and source documents |
| `search` | Full-text search across beliefs, entries, and sources |
| `explain_belief` | Trace why a belief is IN or OUT |
| `what_if` | Simulate retracting or asserting a belief |
| `get_belief` | Full details for a specific belief |
| `list_beliefs` | List beliefs with optional status filter |
| `list_projects` | List available knowledge bases |
| `list_topics` | Browse topic structure of a knowledge base |
| `list_entries` | List analysis entries by topic |
| `get_entry` | Read full entry content |

Connect Claude Desktop by adding to your config:

```json
{
  "mcpServers": {
    "reasons": {
      "url": "https://reasons.reasonsforge.com/mcp"
    }
  }
}
```

## API

```bash
# Search a knowledge base
curl localhost:8000/api/projects/{id}/search?q=drug+interactions

# Deep search (IDF-ranked, dual-path retrieval)
curl localhost:8000/api/projects/{id}/deep-search?q=clinical+trials

# List beliefs
curl localhost:8000/api/projects/{id}/beliefs

# Explain a belief
curl localhost:8000/api/projects/{id}/beliefs/{node_id}/explain

# What-if analysis
curl localhost:8000/api/projects/{id}/beliefs/{node_id}/what-if?action=retract

# Browse data
curl localhost:8000/api/projects/{id}/sources
curl localhost:8000/api/projects/{id}/entries
curl localhost:8000/api/projects/{id}/topics
```

## Architecture

```
reasons-service/
├── reasons_service/
│   ├── app.py                  # FastAPI app + web UI routes
│   ├── config.py               # Settings (DB, API keys, model)
│   ├── mcp.py                  # MCP server (streamable HTTP)
│   ├── api/                    # REST API routes
│   │   ├── projects.py         #   Project CRUD + import
│   │   ├── data.py             #   Sources, entries, beliefs, search
│   │   └── ask.py              #   FTS-only ask (no LLM)
│   ├── db/                     # PostgreSQL + pgvector
│   │   ├── schema.sql          #   Tables + FTS indexes
│   │   ├── models.py           #   SQLAlchemy models
│   │   └── connection.py       #   Async + sync engines
│   ├── rms/                    # Reason Maintenance System
│   │   └── api.py              #   Belief network operations
│   ├── embeddings.py           # fastembed + pgvector
│   └── templates/              # Jinja2 + HTMX + Pico CSS
├── scripts/
│   ├── load_reasons_db.py      # Import from reasons.db (SQLite)
│   ├── import_expert.py        # Import from file-based repos
│   ├── build_embeddings.py     # Build vector embeddings
│   └── manage_users.py         # User management
├── docker-compose.yml          # PostgreSQL + service
└── Dockerfile
```

## Database

| Table | Purpose |
|-------|---------|
| `projects` | Multi-project knowledge base isolation |
| `sources` | Imported documentation chunks |
| `entries` | Analysis entries and summaries |
| `claims` | Beliefs with IN/OUT truth values |
| `nogoods` | Recorded contradictions |
| `topics` | Topic structure for browsing |

Full-text search via PostgreSQL GIN indexes. Vector similarity via pgvector.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://...localhost.../reasons_service` | Async DB connection |
| `DATABASE_URL_SYNC` | `postgresql+psycopg://...localhost.../reasons_service` | Sync DB |
| `GOOGLE_CLOUD_PROJECT` | — | GCP project for Vertex AI |
| `REASONS_LLM` | `true` | Set `false` for data-only mode |
| `REASONS_SERVICE_API_KEY` | — | API key for authenticated access |
| `MCP_ISSUER_URL` | `https://reasons.reasonsforge.com/mcp` | MCP OAuth issuer |

## Related Projects

| Project | Purpose |
|---------|---------|
| [reasons-app](https://github.com/benthomasson/reasons-app) | Desktop menu bar app with local MCP server |
| [reasonsforge](https://github.com/benthomasson/reasonsforge) | CLI pipeline for building domain knowledge bases |
