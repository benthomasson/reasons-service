# Code Review Report

**Branch:** benthomasson/expert-service#23
**Models:** claude, gemini
**Gate:** [BLOCK] BLOCK

## claude [BLOCK]

### alembic/env.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Clean Alembic setup. Correctly pulls `database_url_sync` from settings. The `_EXCLUDED_PREFIXES = ("rms_",)` filter in `include_name` properly prevents Alembic from managing external `rms_*` tables. `NullPool` for migrations is correct — avoids connection pooling during schema changes. Note: this replaces the "Schema-first: No Alembic" approach documented in CLAUDE.md, which should be updated.

### alembic/versions/0001_add_project_public_column.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Correct migration. `server_default="false"` ensures existing rows get `FALSE` without a data backfill. `nullable=False` is consistent with the model and schema.sql. Downgrade is clean `drop_column`. Manual revision ID `"0001"` is readable and works fine.

### expert_service/db/schema.sql
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`public BOOLEAN NOT NULL DEFAULT FALSE` in schema.sql matches the Alembic migration and the SQLAlchemy model. Keeps fresh deployments (via `docker-entrypoint-initdb.d`) consistent with migrated deployments.

### expert_service/db/models.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`public = Column(Boolean, nullable=False, server_default="false")` matches schema.sql and migration. Consistent across all three definitions.

### expert_service/auth.py:verify_auth_or_public
**Verdict:** BLOCK
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

**Security issue.** This function is applied as a router-level dependency to `data.router`, `chat.router`, and `ask.router`. The data router has 5 write endpoints (`/import/sources`, `/import/entries`, `/import/beliefs`, `/link-entries-sources`, `/chunk-sources`) and **none of them have per-endpoint RBAC checks**. Although the public user gets `Role.READER`, the codebase's `require_action()` dependency is defined but **never applied to any endpoint**. This means unauthenticated users can import sources, entries, and beliefs into any project marked `public=True`. The fix is either: (a) apply `verify_auth_or_public` only to read-only routers, or (b) add `Depends(require_action(Action.MANAGE_SOURCES))` to the write endpoints in data.py, or (c) split data.router into read and write sub-routers. Additionally, this function is completely untested.

### expert_service/app.py (router wiring)
**Verdict:** BLOCK
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The `data.router` swap from `verify_auth` to `verify_auth_or_public` is the root of the security concern above. The data router has write endpoints (import, chunk, link operations) that become accessible to unauthenticated users on public projects. The `chat.router` and `ask.router` swaps are appropriate — those are read/query operations.

### expert_service/api/projects.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`public` field correctly threaded through `ProjectCreate`, `ProjectResponse`, and all three response-building sites (`create_project`, `list_projects`, `get_project`). Default `False` in Pydantic models matches the DB default. Projects router stays behind `verify_auth` — correct.

### expert_service/app.py:_open_fds
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Dual fallback (`/dev/fd` for macOS, `/proc/{pid}/fd` for Linux) with graceful `-1` on failure. `resource.getrlimit` for limits. Minor: imports inside function body — fine for a utility that runs infrequently on health checks.

### expert_service/api/chat.py:ask
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Two issues: (1) **Logger placement** — `logger = logging.getLogger(__name__)` is placed between import blocks (line 13, between stdlib and local imports). Cosmetic but unusual. (2) **`single` mode skips connector restrictions** — `single_ask` doesn't receive `allowed_connectors`, but `single_ask` also doesn't query connectors, so this is functionally consistent, not a bug. (3) **`mode` field has no validation** — any string other than `"single"` silently falls through to dual mode. A `Literal["dual", "single"]` type would be safer. (4) **Bare `except Exception`** catches programming errors (TypeError, AttributeError) and returns 502, masking bugs. Consider catching more specific LLM exceptions. (5) No tests for the 502 path or single mode routing.

### expert_service/chat/loop.py (context budgets)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Moving constants to module level is clean. The belief budget in `_quick_belief_search` correctly breaks out of the loop when `MAX_BELIEF_CONTEXT_CHARS` is exceeded and rebuilds `belief_rows` to match what was actually included (line `belief_rows = included_rows`). Tool result truncation happens at both capture and render time — double truncation is harmless (already-truncated strings stay truncated). The `\n[...truncated]` suffix is a nice touch for debugging. This directly addresses the 211K token overflow.

### expert_service/chat/loop.py:single_ask
**Verdict:** CONCERN
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Implementation is solid — mirrors the dual retrieval pattern with a single LLM call. Correctly applies `_strip_hallucinated_refs` and `_build_sources_section`. Two minor concerns: (1) No connector/Snowflake support by design, but this isn't documented in the API (callers don't know single mode silently drops connector queries). (2) The `SINGLE_PASS_PROMPT` is well-structured but there are no tests verifying the retrieval → prompt → response pipeline, even at the unit level.

### expert_service/db/connection.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`pool_size=5, max_overflow=5` on both engines caps total connections at 10 per engine, 20 total. Applied only in the non-SQLite path. This is reasonable for a service with ~50 FDs per concurrent user. Combined with `ulimit -n 10240`, this provides good defense in depth.

### pyproject.toml / uv.lock
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`alembic>=1.13` added to dependencies, lock file updated with alembic 1.18.4 and its transitive dep `mako`. Clean.

### Self-Review
**Limitations:** Could not verify whether `require_action` is intentionally deferred for a future PR or just forgotten — if RBAC enforcement is planned as a separate change and public projects are internal-only for now, the BLOCK severity may be lower. Could not see the full `_check_llm_ready` function to verify it handles the single-pass model parameter correctly. Did not verify whether the health endpoint is intentionally public (no auth dependency) since the FD info is low-risk but still worth confirming.

### Feature Requests
- Include the existing test files that cover modified source files so I can verify whether existing tests break due to signature/behavior changes
- Show the full RBAC model (rbac.py) alongside auth changes to assess authorization impact
- Flag when a router-level dependency change affects endpoints with different security requirements (read vs. write)

## gemini [BLOCK]

### ERROR
**Verdict:** BLOCK

Model invocation failed: Model gemini failed: [31mGemini CLI is not running in a trusted directory. To proceed, either use `--skip-trust`, set the `GEMINI_CLI_TRUST_WORKSPACE=true` environment variable, or trust this directory in interactive mode. For more details, see https://geminicli.com/docs/cli/trusted-folders/#headless-and-automated-environments[0m

