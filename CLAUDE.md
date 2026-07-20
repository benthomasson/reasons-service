# CLAUDE.md

## Project Overview

**reasons-service** is a LangGraph-based web service for building domain expert knowledge bases. It ingests documentation, extracts structured entries and beliefs, and provides a chat interface where LLMs can search and answer questions using the knowledge base.

## Architecture

- **Framework**: FastAPI + LangGraph
- **Database**: PostgreSQL 16 with pgvector extension
- **LLMs**: Gemini 2.5 Pro and Claude Sonnet 4.5 via Vertex AI
- **Embeddings**: fastembed with BAAI/bge-small-en-v1.5 (384 dimensions)
- **Auth**: Google Cloud ADC (Application Default Credentials)
- **Docker**: pgvector/pgvector:pg16 + python:3.12-slim

## Key Directories

```
reasons_service/
  api/           # FastAPI routers (projects, data, chat)
  chat/          # Chat tools and streaming loop
  core/          # Pipeline logic (fetch, summarize, extract)
  db/            # SQLAlchemy models, schema.sql, connection
  graphs/        # LangGraph pipeline definitions
  llm/           # LLM provider factory (Vertex AI)
  templates/     # Jinja2 HTML templates
  embeddings.py  # fastembed + pgvector embedding generation
scripts/
  import_expert.py      # Import from file-based expert repos
  build_embeddings.py   # Build vector embeddings per project
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
  uv run python scripts/build_embeddings.py --project-id <uuid>

# Test API
curl -s http://localhost:8000/api/projects | python3 -m json.tool

# Test chat
curl -s -N -X POST http://localhost:8000/api/projects/<project-id>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is EDA?", "model": "gemini-2.5-pro", "thread_id": "test1"}'
```

## Key Technical Details

- **Dual DB drivers**: asyncpg for FastAPI endpoints, psycopg3 for LangGraph nodes and tools. Sync URL uses `postgresql+psycopg://` dialect.
- **Docker postgres port**: Mapped to 5433 (not 5432) to avoid conflicts.
- **ChatVertexAI vs ChatAnthropicVertex**: ChatVertexAI routes through `publishers/google/` — does NOT work for Claude. Must use `ChatAnthropicVertex` from `langchain_google_vertexai.model_garden` for Claude models.
- **Claude model ID**: `claude-sonnet-4-5@20250929` on Vertex AI. Claude location: `us-east5`.
- **Schema-first**: No Alembic — tables created via `schema.sql` mounted at `/docker-entrypoint-initdb.d/`.
- **pgvector SQL**: Use `CAST(:param AS vector)` not `::vector` to avoid SQLAlchemy parameter binding conflicts.
- **Chat tools**: Project-scoped via closures in `make_tools(project_id)`. LLM never sees the project UUID.
- **Streaming**: Intermediate tool-calling rounds buffer text. Only the final round streams tokens to SSE.
- **Prompt caching**: Claude uses `cache_control` on SystemMessage. Gemini uses `create_context_cache` with graceful fallback (32K token minimum).

## Chat Search Tools

Three search channels available to the LLM:
1. `search_knowledge` — FTS keyword search (default)
2. `grep_content` — ILIKE exact text match
3. `semantic_search` — pgvector cosine similarity
