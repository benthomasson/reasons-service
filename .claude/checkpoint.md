# Checkpoint

**Saved:** 2026-10-26 15:45
**Project:** /Users/ai/git/reasons-service

## Task

Porting the reasons-service UI to PatternFly React 6 SPA, scaffolding the app, fixing backend compatibility, and importing test data.

## Status

- [x] Created `feature-patternfly-ui` branch
- [x] Scaffolded Vite + React 19 + TypeScript + PatternFly v6 SPA in `ui/` (15 files, ~1800 lines)
- [x] Added `/api/auth/me` endpoint for SPA auth
- [x] Added SPA fallback serving at `/app/*`
- [x] Fixed Python 3.12 / asyncpg / onnxruntime compatibility
- [x] Fixed database schema: created `tenants`, `tenant_members`, `topics` tables; added `tenant_id` to `users` and `domains`
- [x] Dropped and recreated rms_* tables using library's own schema (fixes project_id vs domain_id mismatch)
- [x] Updated raw SQL in `rms/api.py` and `embeddings.py` to use `project_id` on rms_* tables (matching ftl-reasons library)
- [x] Fixed SPA SSE parser to match server's event format (`data: {"type": "...", "content": "..."}` not named SSE events)
- [x] Fixed `searchBeliefs` API response shape (`beliefs` not `items`)
- [x] Fixed `Justification.type` (was `jtype`)
- [x] Made `Belief` fields optional to match actual API response
- [x] Updated `BeliefsPage` search to use FTS endpoint
- [x] Imported patternfly-expert domain: 1,804 beliefs, 2 nogoods
- [x] Alembic stamped to head
- [ ] Test all SPA pages in browser against live data
- [ ] Test chat (requires OPENAI_API_KEY)
- [ ] Commit all changes

## Key Files

- `ui/src/components/ChatPage.tsx` — SSE parser fixed to match server format
- `ui/src/api.ts` — searchBeliefs response shape fixed
- `ui/src/types.ts` — Belief fields made optional, Justification.type fixed
- `ui/src/components/BeliefsPage.tsx` — uses searchBeliefs for FTS
- `reasons_service/rms/api.py` — raw SQL uses `project_id` on rms_* tables
- `reasons_service/embeddings.py` — raw SQL uses `project_id` on rms_* tables
- `reasons_service/auth.py` — `/api/auth/me` endpoint added
- `reasons_service/app.py` — SPA fallback added

## Commands

```bash
# Start FastAPI (Python 3.12 required for onnxruntime)
cd ~/git/reasons-service && DATABASE_URL="postgresql+asyncpg://expert:expert_dev@localhost:5433/reasons_service" DATABASE_URL_SYNC="postgresql+psycopg://expert:expert_dev@localhost:5433/reasons_service" uv run --python 3.12 python -m reasons_service.app

# Start Vite dev server
cd ~/git/reasons-service/ui && npm run dev

# Import a domain
curl -X POST http://localhost:8000/api/domains/import-reasons -F "name=..." -F "description=..." -F "file=@path/to/reasons.db"
```

## Next Step

Test the SPA pages in browser (http://localhost:3001/app/) — verify domains list, beliefs list with search, belief detail, domains overview. Then commit.

## Context

- `ftl-reasons` library uses `project_id` on rms_* tables; the service schema.sql used `domain_id`. Resolved by dropping rms tables and letting the library recreate them with its own schema, then updating the service's raw SQL to match.
- The Alembic migration chain is broken (migration 0001 references a `projects` table that doesn't exist). Stamped to head and did schema changes manually.
- Dev mode auth bypass: when no Google OAuth credentials, auth returns `UserInfo(identity="dev", role=Role.ADMIN)`.
- Domain imported: patternfly-expert with 1,804 beliefs.
