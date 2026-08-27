# Checkpoint

**Saved:** 2026-08-06
**Project:** /Users/ben/git/reasons-service

## Task

Multiple features added: RBAC reviewer role, belief proposals system, MCP review tools, proposal review web UI. Also fixed import_expert.py, manage_users.py SQLite support, pinned mcp<2.

## Status

### Completed (prior sessions)
- [x] Updated import_expert.py: removed beliefs import, added summaries support
- [x] Fixed manage_users.py to work with SQLite (`--db` flag)
- [x] Added RBAC reviewer role and belief proposals system (Issue #41)
- [x] Fixed proposal endpoints: proper HTTP errors and input validation
- [x] Added modify proposal validation and CHAT to reviewer role
- [x] Pinned mcp[cli]<2 to avoid breaking import changes
- [x] Added MCP review tools: accept_proposal, reject_proposal, get_proposal (Issue #42)
- [x] Added review_notes field to proposals
- [x] Fixed proposal route ordering: `/beliefs/propose` and `/beliefs/proposed` before `/beliefs/{node_id}`
- [x] Added proposal review web UI: list page, detail page, domain stats (Issue #43)

### Not yet done
- [ ] Bump version (currently 0.6.9, needs bump for deploy)
- [ ] Build wheel (`uv build`)
- [ ] Update deploy script WHEEL path
- [ ] Deploy to server

## Key Files

- `reasons_service/rbac.py` — REVIEWER role, PROPOSE_BELIEFS and REVIEW_PROPOSALS actions
- `reasons_service/db/models.py` — Proposal model with review_notes
- `reasons_service/db/schema.sql` — proposals table DDL
- `reasons_service/api/data.py` — Proposal REST endpoints (must be before `{node_id}` routes)
- `reasons_service/mcp.py` — 6 proposal MCP tools (Tier 4)
- `reasons_service/app.py` — Web routes for proposals list/detail, proposals count in domain stats
- `reasons_service/templates/proposals/list.html` — Proposals list with status filter tabs
- `reasons_service/templates/proposals/detail.html` — Proposal detail with accept/reject form

## Commands

```bash
# Build wheel
cd /Users/ben/git/reasons-service && uv build

# Deploy
cd /Users/ben/git/ftl2-deployments/reasons-service && source ../.env-reasonsforge.com && ./deploy.py redeploy

# Manual install on server
ssh admin@34.162.111.227 "sudo su - reasons -c '/home/reasons/.local/bin/uv pip install --no-cache --reinstall-package reasons-service --python /home/reasons/.venv/bin/python /home/reasons/reasons_service-<VERSION>-py3-none-any.whl'"
ssh admin@34.162.111.227 "sudo systemctl restart reasons-service"
```

## Next Step

Bump version, commit, push, build wheel, and deploy. The deploy script at `ftl2-deployments/reasons-service/deploy.py` needs the WHEEL path updated to match the new version.

## Context

- Version is 0.6.9, all features committed but wheel not rebuilt since version bump
- Latest commit: `0090e65` (proposal review UI)
- Route ordering is critical: proposal endpoints must be registered before `{node_id}` routes in `data.py`
- Proposals are staging-only — reasons-service stores them but doesn't apply them to live beliefs
- mcp pinned to <2 because mcp 2.0 has breaking import path changes
- **DO NOT rename** `google_cloud_project` / `GOOGLE_CLOUD_PROJECT` — GCP/Vertex AI references
- **Server**: 34.162.111.227, user `admin`, service user `reasons`, SQLite at `/home/reasons/data/reasons.db`
- **Deploy script**: `~/git/ftl2-deployments/reasons-service/deploy.py`
