# Reasons Service

Web service for building domain expert knowledge bases, powered by LangGraph.

Takes the CLI-based [Reasons Forge](https://github.com/benthomasson/reasonsforge) pipeline and delivers it as a deployed service with REST API and web UI — accessible to non-developers who can't work in a git repo with Claude Code.

## What It Does

```
Documentation URL
       │
       ▼
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  1. Ingest  │────▶│  2. Beliefs  │────▶│  3. Assessment │
│             │     │              │     │                │
│ Fetch docs  │     │ Propose via  │     │ Cert coverage  │
│ HTML → MD   │     │ LLM extract  │     │ Practice exams │
│ Summarize   │     │ Human review │     │ Nogood capture │
│ via LLM     │     │ Accept/reject│     │                │
└─────────────┘     └──────────────┘     └────────────────┘
       │                   │                     │
       ▼                   ▼                     ▼
   sources table      claims table       assessments table
   entries table                          nogoods table
                    ┌──────────┐
                    │ PostgreSQL│
                    └──────────┘
```

Each stage is a separate [LangGraph](https://langchain-ai.github.io/langgraph/) graph with its own state, checkpointing, and lifecycle. The beliefs graph uses `interrupt()` for human-in-the-loop review.

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
```

## API

```bash
# Create a project
curl -X POST localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "aap-expert", "domain": "Ansible Automation Platform 2.6"}'

# Ingest documentation
curl -X POST localhost:8000/api/projects/{id}/ingest \
  -d '{"url": "https://docs.example.com/", "depth": 2}'

# Propose beliefs from entries
curl -X POST localhost:8000/api/projects/{id}/beliefs/propose

# Review proposed beliefs (or use the web UI)
curl localhost:8000/api/projects/{id}/beliefs/proposed

# Submit review decisions
curl -X POST localhost:8000/api/projects/{id}/beliefs/review \
  -d '{"decisions": {"belief-id-1": "accept", "belief-id-2": "reject"}}'

# Run certification coverage analysis
curl -X POST localhost:8000/api/projects/{id}/assess/coverage \
  -d '{"objectives": [{"id": "OBJ-001", "domain": "Install", "text": "..."}]}'

# Run practice exam
curl -X POST localhost:8000/api/projects/{id}/assess/exam \
  -d '{"questions": [{"id": "Q1", "text": "...", "choices": {"a": "...", "b": "..."}, "correct": "b"}]}'

# Check pipeline status
curl localhost:8000/api/projects/{id}/pipeline/{run_id}

# Search entries
curl localhost:8000/api/projects/{id}/search?q=ansible+tower

# List all data
curl localhost:8000/api/projects/{id}/sources
curl localhost:8000/api/projects/{id}/entries
curl localhost:8000/api/projects/{id}/claims
curl localhost:8000/api/projects/{id}/nogoods
```

## Architecture

```
reasons-service/
├── reasons_service/
│   ├── app.py                  # FastAPI app + web UI routes
│   ├── config.py               # Settings (DB, API keys, model)
│   ├── core/                   # Business logic (ported from expert-build)
│   │   ├── fetch.py            #   HTML → markdown, URL crawling
│   │   ├── summarize.py        #   Batch LLM summarization
│   │   ├── propose.py          #   Belief extraction from entries
│   │   ├── coverage.py         #   Cert objective matching
│   │   └── exam.py             #   Practice exam + nogood discovery
│   ├── graphs/                 # LangGraph state machines
│   │   ├── ingest.py           #   fetch → summarize (batch loop)
│   │   ├── beliefs.py          #   propose → interrupt() → accept
│   │   └── assessment.py       #   load_beliefs → coverage | exam
│   ├── api/                    # REST API routes
│   │   ├── projects.py         #   CRUD
│   │   ├── pipeline.py         #   Pipeline triggers + status
│   │   └── data.py             #   Sources, entries, claims, search
│   ├── db/                     # PostgreSQL
│   │   ├── schema.sql          #   7 tables + FTS indexes
│   │   ├── models.py           #   SQLAlchemy models
│   │   └── connection.py       #   Async + sync engines
│   ├── llm/                    # LLM integration
│   │   ├── provider.py         #   ChatModel factory (Vertex AI)
│   │   └── prompts.py          #   Prompt templates
│   └── templates/              # Jinja2 + HTMX + Pico CSS
├── langgraph.json              # LangGraph Platform deployment
├── docker-compose.yml          # PostgreSQL + service
└── Dockerfile
```

## Three Graphs, Three Lifecycles

| Graph | Duration | Key Feature | Nodes |
|-------|----------|-------------|-------|
| **Ingest** | Minutes | Batch checkpointing | init → fetch → summarize (loop) |
| **Beliefs** | Hours/days | `interrupt()` for human review | propose → review → accept |
| **Assessment** | Minutes | Routing (coverage vs exam) | load_beliefs → coverage \| exam |

They are separate graphs because their lifecycles differ — fetching takes minutes, belief review takes days, exams are on-demand. Each graph has its own state type and can run independently.

## Database

PostgreSQL replaces the file-based storage from expert-build:

| expert-build | reasons-service | Purpose |
|-------------|----------------|---------|
| `sources/*.md` | `sources` table | Fetched documentation |
| `entries/YYYY/MM/DD/*.md` | `entries` table | LLM summaries |
| `beliefs.md` | `claims` table | Factual claims (IN/OUT/PROPOSED) |
| `nogoods.md` | `nogoods` table | Contradictions from exams |
| — | `assessments` table | Coverage + exam results |
| — | `projects` table | Multi-project support |
| — | `pipeline_runs` table | Pipeline execution tracking |

Full-text search via PostgreSQL GIN indexes on entries and claims.

## Configuration

Uses **Vertex AI** for all LLM access (same credentials as agents-python). Authenticate with:

```bash
gcloud auth application-default login
```

Environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GOOGLE_CLOUD_PROJECT` | — | GCP project for Vertex AI |
| `GOOGLE_CLOUD_LOCATION` | `global` | Vertex AI region (Gemini) |
| `DEFAULT_MODEL` | `gemini-2.5-pro` | Default LLM |
| `DATABASE_URL` | `postgresql+asyncpg://...localhost.../reasons_service` | Async DB connection |
| `DATABASE_URL_SYNC` | `postgresql://...localhost.../reasons_service` | Sync DB (graphs + checkpointer) |

Claude models automatically use `us-east5` (Anthropic on Vertex AI).

## Related Projects

| Project | Purpose |
|---------|---------|
| [expert-agent-builder](https://github.com/benthomasson/expert-agent-builder) | CLI pipeline (what this service ports) |
| [aap-expert](https://github.com/benthomasson/aap-expert) | AAP domain expert (built with expert-build) |
| [beliefs](https://github.com/benthomasson/beliefs) | Belief registry CLI |
| [shared-enterprise](https://github.com/benthomasson/shared-enterprise) | SQLite knowledge base indexer |
