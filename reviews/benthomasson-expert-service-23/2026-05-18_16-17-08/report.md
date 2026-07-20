# Code Review Report

**Branch:** benthomasson/expert-service#23
**Models:** claude, gemini
**Gate:** [CONCERN] CONCERN

## Disagreements

The following changes have different verdicts across models:

- **expert_service/auth.py:verify_auth_or_public** [LOW]: claude: CONCERN, gemini: PASS
- **expert_service/api/chat.py:ask** [LOW]: claude: CONCERN, gemini: PASS
- **tests/test_auth.py:TestPublicProjectAccess** [LOW]: claude: CONCERN, gemini: PASS

## claude [CONCERN]

### alembic/env.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Clean Alembic setup. Correctly pulls `database_url_sync` from settings, sets `target_metadata = Base.metadata`, and filters out `rms_` tables via `include_name`. Uses `NullPool` for online migrations (correct — avoids stale connections). Note: CLAUDE.md says "Schema-first: No Alembic" — this doc should be updated now that Alembic is in play.

### alembic/versions/0001_add_project_public_column.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Migration adds `public BOOLEAN NOT NULL DEFAULT FALSE` — matches the model (`models.py`) and schema (`schema.sql`). `server_default="false"` is correct for backfill of existing rows. Downgrade drops the column cleanly.

### expert_service/auth.py:verify_auth_or_public
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The function checks public status *before* checking auth, meaning authenticated users on public projects are downgraded to `identity="public", role=Role.READER`. The test `test_public_project_with_api_key_gets_public_identity` explicitly asserts this — so it's intentional — but it means an admin hitting a public project's GET endpoint loses their admin identity. This could surprise operators debugging via API. Consider checking auth first, falling back to public only if auth fails. Additionally, the raw SQL `SELECT public FROM projects WHERE id = :pid` will return a row even for a UUID that doesn't match any project if there's a type mismatch — though `str(project_id)` should serialize correctly for PostgreSQL UUID columns.

### expert_service/app.py (router wiring)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** PARTIAL
**Integration:** WIRED

`data.router`, `chat.router`, and `ask.router` switched from `verify_auth` to `verify_auth_or_public`. The write endpoints on `data.router` (`/import/sources`, `/import/entries`, etc.) have route-level `dependencies=[Depends(verify_auth)]` which still runs and correctly blocks unauthenticated writes — FastAPI evaluates both router-level and route-level dependencies. `projects.router`, `meta_chat.router`, and `pipeline.router` remain auth-required. This is a sound layering.

### expert_service/api/data.py (route-level auth on write endpoints)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Five POST endpoints (`/import/sources`, `/import/entries`, `/import/beliefs`, `/link-entries-sources`, `/chunk-sources`) now have explicit `dependencies=[Depends(verify_auth)]` at the route level. This is the correct defense-in-depth: even though the router-level dep changed to `verify_auth_or_public`, these write endpoints independently enforce full auth. However, there are no tests verifying that unauthenticated users cannot hit these write endpoints on public projects.

### expert_service/api/chat.py:ask
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The error handler catches `(httpx.HTTPError, OSError, TimeoutError, ValueError)`. The checkpoint and entry documents describe 211K-token overflows causing `anthropic.BadRequestError` — this exception does **not** inherit from any of the caught types. LangChain may wrap it differently, but without verification, the exact error this handler was designed to catch may slip through as a 500. Also, `ValueError` is extremely broad and will catch unrelated bugs, masking them as "LLM temporarily unavailable." Additionally, `logger` is defined between two import blocks (line 19 between `single_ask` import and `get_sync_session` import) — minor style issue but disruptive to read.

### expert_service/chat/loop.py (context budget constants)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Constants moved to module top: `MAX_CHUNK_CHARS=2000`, `MAX_CONTEXT_CHARS=30000`, `MAX_BELIEF_CONTEXT_CHARS=30000`, `MAX_TOOL_RESULT_CHARS=10000`. The previous location (inside the dual-path section) had `MAX_CHUNK_CHARS` and `MAX_CONTEXT_CHARS` — those are preserved with same values. The two new constants (`MAX_BELIEF_CONTEXT_CHARS`, `MAX_TOOL_RESULT_CHARS`) directly address the context overflow issue. No tests for the truncation behavior.

### expert_service/chat/loop.py:_quick_belief_search (budget cap)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Belief context is now budget-capped at `MAX_BELIEF_CONTEXT_CHARS` (30K chars). The implementation correctly tracks `included_rows` separately so the returned `belief_rows` list only contains beliefs that were included in the context string. This ensures the sources section won't reference beliefs that were budget-trimmed. Called from 6 production locations — all benefit from the cap.

### expert_service/chat/loop.py:_tms_answer_iterative (tool result truncation)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Tool history entries are truncated to `MAX_TOOL_RESULT_CHARS` (10K) with a `[...truncated]` suffix. Applied in two places: when building the history section from `tool_history` (existing entries) and immediately after `query_data` returns (new entries). Both truncation points are correct. The `[...truncated]` marker lets the LLM know context was cut.

### expert_service/chat/loop.py:single_ask
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Clean single-pass implementation. Parallel retrieval (beliefs + chunks), single LLM call with `SINGLE_PASS_PROMPT`, standard post-processing (strip hallucinated refs, build sources). Correctly handles empty retrieval with early return. Mirrors `dual_ask` structure. The `SINGLE_PASS_PROMPT` is well-structured with clear rules and formatting. No `allowed_connectors` support (no Snowflake/connector queries) — this is fine for the "smaller model" use case but differs from `dual_ask`. No tests.

### expert_service/db/connection.py (pool caps)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Both async and sync engines now have `pool_size=5, max_overflow=5` (max 10 connections each, 20 total). Previous default was `pool_size=5, max_overflow=10` (SQLAlchemy defaults), so this tightens overflow by 5. Reasonable for a service with ~50 FDs per concurrent user. Only applied to non-SQLite engines (the conditional structure is preserved).

### expert_service/db/models.py:Project
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** PARTIAL
**Integration:** WIRED

`public = Column(Boolean, nullable=False, server_default="false")` matches the migration and schema.sql. Used in `projects.py` (create, list, get) and `auth.py` (public check via raw SQL, not ORM — could use the model instead but raw SQL is fine).

### expert_service/db/schema.sql
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`public BOOLEAN NOT NULL DEFAULT FALSE` added to projects table. Consistent with model and migration. Schema.sql is used for Docker init (`/docker-entrypoint-initdb.d/`), so new Docker builds get the column. Existing deployments need the Alembic migration.

### expert_service/api/projects.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`public` field added to `ProjectCreate` (input, default False) and `ProjectResponse` (output, default False). Threaded through `create_project`, `list_projects`, and `get_project`. All three response constructors include `public=project.public` or `public=p.public`. Clean integration.

### expert_service/app.py:_open_fds
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Counts FDs via `/dev/fd` (macOS) or `/proc/{pid}/fd` (Linux), falls back to -1. Returns soft/hard limits from `resource.getrlimit`. Exposed on `/health` (unauthenticated) — minor information disclosure but standard for internal services. The `import os` and `import resource` inside the function body is unusual but not wrong.

### tests/test_auth.py:TestPublicProjectAccess
**Verdict:** CONCERN
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** PARTIAL
**Integration:** WIRED

Four tests cover the core cases: public project allows anonymous, private project requires auth, nonexistent project requires auth, and authenticated user on public project gets public identity. The mock setup is reasonable — mocks the DB session to return controlled `public` values. However, missing tests: (1) no test for write endpoints on public projects being blocked, (2) no test for routes without `project_id` in path falling through to `verify_auth`, (3) `test_public_project_with_api_key_gets_public_identity` asserts the potentially surprising downgrade behavior without commenting on whether this is desirable.

### Self-Review
**Limitations:** - Could not verify whether `anthropic.BadRequestError` or LangChain-wrapped equivalents inherit from any of the caught exception types in the `/ask` handler — this affects the correctness assessment of the error handling
- Did not have access to the full `loop.py` to verify the constant move didn't break any intermediate references
- Could not verify whether the `data.router` read endpoints (GET) expose any sensitive data that shouldn't be public
- Test file was only partially visible — could not verify the test runner configuration or whether existing tests still pass with the model changes

### Feature Requests
- Include the exception hierarchy for key exception types when they appear in catch clauses (e.g., show that `anthropic.BadRequestError` does/doesn't inherit from `httpx.HTTPError`)
- When auth/permission changes are made, automatically enumerate all endpoints affected and their effective auth requirements (the composition of router-level + route-level dependencies)

## gemini [PASS]

### .claude/checkpoint.md
VERDICT: PASS
CORRECTNESS: VALID
SPEC_COMPLIANCE: N/A
ISSUE_COMPLIANCE: ADDRESSES
BELIEF_COMPLIANCE: CONSISTENT
TEST_COVERAGE: N/A
INTEGRATION: WIRED
REASONING: The checkpoint correctly reflects the shift from feature development to production hardening, accurately summarizing the completed and pending tasks.
---

### alembic.ini & alembic/
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Standard Alembic setup for SQLAlchemy. The `include_name` filter in `env.py` is a prudent addition to prevent migrations from interfering with legacy `rms_` tables during transition.

### expert_service/db/models.py:Project & schema.sql
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The `public` column is correctly added to both the SQLAlchemy model and the raw SQL schema. The migration `0001` provides the necessary upgrade path.

### expert_service/db/connection.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Capping `pool_size` and `max_overflow` to 5 is a direct and effective fix for the file descriptor exhaustion reported in the entries. It ensures database connections don't scale unbounded with concurrent requests.

### expert_service/auth.py:verify_auth_or_public
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The logic for bypassing authentication for public projects is sound. It uses a targeted SQL query to check the `public` flag, minimizing overhead. The fallback to `verify_auth` ensures private projects remain protected.

### expert_service/api/data.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Hardening POST endpoints with an explicit `verify_auth` dependency is critical. While the router allows public GET access, this change correctly restricts write operations to authenticated users regardless of project visibility.

### expert_service/chat/loop.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** PARTIAL
**Integration:** WIRED

1. **Context Budgets**: The introduction of `MAX_BELIEF_CONTEXT_CHARS` and `MAX_TOOL_RESULT_CHARS` successfully mitigates the 211k token overflow issue. 2. **single_ask**: Implements a robust single-pass synthesis mode, useful for smaller or local models (like Gemma3) that struggle with iterative dual-path patterns. 3. **Truncation**: Iterative tool history is now safely truncated per result.

### expert_service/api/chat.py:ask
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The addition of a 502 error handler for LLM-related exceptions (HTTP errors, timeouts, FD exhaustion) provides much better production resilience than allowing a 500 traceback.

### expert_service/app.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Integrating `verify_auth_or_public` at the router level and adding FD monitoring to the `/health` endpoint are excellent observability and security improvements.

### tests/test_auth.py:TestPublicProjectAccess
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Comprehensive test cases for the new public access logic, covering anonymous access, private project rejection, and the priority of the public flag over API keys.

### Self-Review
**Limitations:** Review was conducted primarily based on diffs and provided observation results. While full function bodies for some critical functions were available, some integration points in the RBAC system (`rbac.py`) were not fully visible.

### Feature Requests
- Include the content of `scripts/` files when they are modified or referenced as "fixes" (e.g., the `ulimit` change in `start.local.sh`).
- Show the `RBAC` role definitions when authentication/authorization logic is modified to verify permissions flow.
