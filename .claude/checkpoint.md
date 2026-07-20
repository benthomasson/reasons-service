# Checkpoint

**Saved:** 2026-05-14 10:30
**Project:** /Users/ben/git/expert-service

## Task

Production hardening of expert-service: FD exhaustion fix, context window overflow fix, error handling, architecture documentation, and sd-architect diagram.

## Status

### Completed this session
- [x] Diagnosed FD exhaustion — macOS default 256 soft limit was the bottleneck, not rate limiting or DNS
- [x] Added `ulimit -n 10240` to `scripts/start.local.sh`
- [x] Added `pool_size=5, max_overflow=5` to both async and sync engines in `db/connection.py`
- [x] Added `/health` endpoint FD monitoring: `_open_fds()` returns `{open, limit_soft, limit_hard}`
- [x] Added try/except on `/ask` endpoint — returns 502 JSON instead of 500 traceback
- [x] Diagnosed context window overflow — 211K tokens > 200K limit from unbounded beliefs + tool history
- [x] Added context budgets: `MAX_BELIEF_CONTEXT_CHARS=30000`, `MAX_TOOL_RESULT_CHARS=10000` (constants moved to top of loop.py)
- [x] Confirmed FD fix working under load: 366 FDs at peak with 4 concurrent users (was crashing at 256)
- [x] Filed benthomasson/expert#1 — Plugin system for expert CLI
- [x] Filed benthomasson/expert#2 — Rename package to ftl-expert for PyPI
- [x] Written entries: FD exhaustion fix, context window overflow, architecture overview
- [x] Created `architecture.json` for sd-architect visualization
- [ ] Context budget changes not yet deployed (need restart)

## Key Files

- `expert_service/db/connection.py` — Added pool_size/max_overflow caps on both engines
- `expert_service/chat/loop.py` — Added MAX_BELIEF_CONTEXT_CHARS, MAX_TOOL_RESULT_CHARS at top; belief search now budget-capped; tool history results truncated at 10K chars
- `expert_service/api/chat.py` — Added try/except returning 502 JSON on LLM failures
- `expert_service/app.py` — Added `_open_fds()` helper and FD info to `/health` endpoint
- `scripts/start.local.sh` — Added `ulimit -n 10240`
- `architecture.json` — sd-architect diagram (13 components, 12 connections)
- `entries/2026/05/13/file-descriptor-exhaustion-fix-*.md` — FD fix writeup
- `entries/2026/05/13/context-window-overflow-*.md` — Context overflow writeup
- `entries/2026/05/14/expert-service-architecture-*.md` — Full architecture doc

## Commands

```bash
# Check FD usage on running service
curl localhost:8000/health | jq .fds

# Start with FD fix
./scripts/start.local.sh

# Visualize architecture
python ~/git/sd-architect/demos/sd_demo.py architecture.json

# Gemma3 single-pass mode via API
curl -X POST localhost:8000/api/projects/{id}/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"test","model":"ollama:gemma3:27b","mode":"single"}'
```

## Next Step

Restart expert-service to deploy the context budget changes (MAX_BELIEF_CONTEXT_CHARS, MAX_TOOL_RESULT_CHARS). Then verify 211K token errors stop occurring. The code is ready, just needs a process restart.

## Context

- **FD root cause confirmed**: 4 concurrent users peaked at 366 FDs; old 256 limit would crash. ~50 FDs per concurrent user.
- **Context overflow**: Beliefs had no char budget (source chunks had 30K). Tool history (especially Snowflake results) accumulated unbounded across 3 iterative rounds. Fixed with per-source budgets.
- **502 error handler working**: Saw `502 Bad Gateway` in logs instead of 500 traceback — confirms api/chat.py fix is live.
- **Architecture decisions discussed**: Read-only stateless deployment on OpenShift, SQLite KB baked into container images, no chat logs needed (stateless is a feature).
- **4000-question eval runs** are the stress test that exposed both FD and context issues.
- **Pending from previous session**: Attribution prompt improvement (missing inline citations), auto-detect single mode for ollama models, fix langfuse in agents-python.
