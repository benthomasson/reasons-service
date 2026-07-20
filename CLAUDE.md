# CLAUDE.md

## Project Overview

**reasons-service** is a FastAPI-based web service for building domain expert knowledge bases. It ingests documentation, extracts structured entries and beliefs, and exposes them via REST API, MCP server, and web UI.

## Architecture

- **Framework**: FastAPI
- **Database**: PostgreSQL 16 with pgvector extension
- **LLMs**: Gemini 2.5 Pro and Claude Sonnet 4.5 via Vertex AI
- **Embeddings**: fastembed with BAAI/bge-small-en-v1.5 (384 dimensions)
- **Auth**: Google Cloud ADC (Application Default Credentials)
- **Docker**: pgvector/pgvector:pg16 + python:3.12-slim

## Key Directories

```
reasons_service/
  api/           # FastAPI routers (domains, data, ask)
  core/          # Pipeline logic (fetch, summarize, extract)
  db/            # SQLAlchemy models, schema.sql, connection
  llm/           # LLM provider factory (Vertex AI)
  templates/     # Jinja2 HTML templates
  embeddings.py  # fastembed + pgvector embedding generation
scripts/
  import_expert.py      # Import from file-based expert repos
  build_embeddings.py   # Build vector embeddings per domain
```

## Common Commands

```bash
# Build and start
docker compose up -d --build service

# Full rebuild (destroys data — need reimport)
docker compose down -v && docker compose up -d --build

# Import an expert repo
uv run python scripts/import_expert.py ~/git/aap-expert \
  --name aap-expert --domain "Ansible Automation Platform 2.6"

# Build embeddings (note port 5433 for local access to Docker postgres)
DATABASE_URL_SYNC="postgresql+psycopg://expert:expert_dev@localhost:5433/reasons_service" \
  uv run python scripts/build_embeddings.py --domain-id <uuid>

# Test API
curl -s http://localhost:8000/api/domains | python3 -m json.tool

```

## Key Technical Details

- **Dual DB drivers**: asyncpg for FastAPI endpoints, psycopg3 for sync operations. Sync URL uses `postgresql+psycopg://` dialect.
- **Docker postgres port**: Mapped to 5433 (not 5432) to avoid conflicts.
- **Schema-first**: No Alembic — tables created via `schema.sql` mounted at `/docker-entrypoint-initdb.d/`.
- **pgvector SQL**: Use `CAST(:param AS vector)` not `::vector` to avoid SQLAlchemy parameter binding conflicts.
