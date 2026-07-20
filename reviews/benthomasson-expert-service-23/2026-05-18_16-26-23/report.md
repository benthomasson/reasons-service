# Code Review Report

**Branch:** benthomasson/expert-service#23
**Models:** claude, gemini
**Gate:** [CONCERN] CONCERN

## Disagreements

The following changes have different verdicts across models:

- **expert_service/auth.py:verify_auth_or_public** [LOW]: claude: CONCERN, gemini: PASS
- **alembic/versions/0001_add_project_public_column.py** [LOW]: claude: CONCERN, gemini: PASS

## claude [CONCERN]

### expert_service/api/chat.py
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Two issues. (1) **Import ordering bug at line 17-18**: `logger = logging.getLogger(__name__)` is placed between two `from` import blocks — the `from expert_service.db.connection import get_sync_session` line appears after `logger =`. This works but is a code smell that suggests a hasty edit. (2) **`single_ask` doesn't pass `allowed_connectors`**: `dual_ask` reads `_get_project_connectors(project_id)` and forwards it, but `single_ask` at line 83 receives no connector whitelist. The `single_ask` function itself doesn't use connectors (it's a single-pass with no iterative tool calls), so this is functionally correct but worth noting if connectors become relevant to single mode later. (3) The `except` clause at line 87 catches `OSError` broadly — this would catch filesystem errors, unrelated `errno` values, etc. A more targeted catch like `ConnectionError` would be safer, though OSError does cover the FD exhaustion case that motivated it. (4) No tests for the `/ask` endpoint error handling path or the new `mode` parameter.

### expert_service/auth.py:verify_auth_or_public
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The function works correctly for the happy paths (tests cover public=True, public=False, nonexistent project, and authenticated-on-public). Two concerns: (1) **Raw SQL instead of ORM query** — uses `sa_text("SELECT public FROM projects WHERE id = :pid")` with `str(project_id)`. If `project_id` is a valid UUID from path params this is fine, but it bypasses SQLAlchemy's type system. The `Project` model is imported elsewhere and available; using `select(Project.public).where(Project.id == project_id)` would be more consistent with the codebase. (2) **Session reuse after `verify_auth` failure** — `verify_auth` may have used `session` for a `SELECT` on the `users` table before raising HTTPException. The same session object is then reused for the `SELECT public` query. This should be fine with async sessions (no rollback needed on a SELECT), but it's worth verifying there's no dirty state. (3) The `Role.READER` assignment for public users is the correct security choice — minimal privilege.

### expert_service/app.py (data.router auth change)
**Verdict:** CONCERN
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** PARTIAL
**Integration:** WIRED

`data.router` is changed from `verify_auth` to `verify_auth_or_public` at the router level (line 111), which opens **all** data.router GET endpoints to public/anonymous access for public projects. This includes `/sources`, `/entries`, `/beliefs`, `/search`, `/deep-search`, `/issues`, individual belief explain/what-if endpoints — a broad read surface. The **write endpoints** (`/import/sources`, `/import/entries`, `/import/beliefs`, `/link-entries-sources`, `/chunk-sources`) correctly have their own `Depends(verify_auth)` decorators, so they remain protected. This is a defensible design (public = read-only), but the router-level override means any new GET endpoint added to `data.router` in the future will be publicly accessible by default, which is easy to miss. A comment on line 111 noting this would help.

### expert_service/app.py:_open_fds
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Correctly tries `/dev/fd` (macOS) then `/proc/{pid}/fd` (Linux) with fallback to -1. Uses `resource.getrlimit` for limits. Imports are inside the function body which is slightly unusual but fine for a health check helper. Wired into `/health` endpoint. No tests but low risk — it's an observability helper.

### expert_service/chat/loop.py (context budget constants + belief truncation)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Constants moved from mid-file to module top (lines 26-30), which is cleaner. `_quick_belief_search` now enforces `MAX_BELIEF_CONTEXT_CHARS` budget with a clean break-on-overflow loop. The `included_rows` list correctly tracks which rows were actually included, ensuring `belief_rows` (used for source refs) stays in sync with the truncated context string. Tool history truncation in `_tms_answer_iterative` (lines 666-670, 710-711) is correctly applied both when building `history_section` and when first capturing `query_data` results. The `[...truncated]` marker is a nice touch for LLM awareness.

### expert_service/chat/loop.py:single_ask
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Clean single-pass implementation. Parallel retrieval via `asyncio.gather`, consistent use of `_strip_hallucinated_refs` and `_build_sources_section` matching `dual_ask`'s post-processing. The prompt template `SINGLE_PASS_PROMPT` is well-structured. Correctly handles the no-results edge case. Return dict shape (`answer`, `tms_chars`, `rag_chars`) matches `dual_ask`. No tests, but the function is straightforward and reuses well-tested building blocks.

### expert_service/db/models.py (Project.public column)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** PARTIAL
**Integration:** WIRED

`public = Column(Boolean, nullable=False, server_default="false")` matches the migration and schema.sql. Consistent across all three sources of truth (ORM model, schema.sql, Alembic migration).

### expert_service/db/schema.sql
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** PARTIAL
**Integration:** WIRED

`public BOOLEAN NOT NULL DEFAULT FALSE` added to projects table. Consistent with the ORM model and migration.

### expert_service/api/projects.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`public` field added to `ProjectCreate` (input) and `ProjectResponse` (output), defaulting to `False`. Constructor call updated. All three response paths (create, list, get) include `public=project.public`. Clean and complete.

### expert_service/db/connection.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`pool_size=5, max_overflow=5` caps total connections at 10 per engine. This is defense-in-depth for the FD exhaustion fix. Values are reasonable for a single-instance service. Only applies to non-SQLite backends (the `else` branch), which is correct.

### alembic/env.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Standard Alembic env.py. Gets the sync URL from `settings.database_url_sync`. `_EXCLUDED_PREFIXES = ("rms_",)` is a nice touch to prevent Alembic from trying to manage the `rms_*` tables. `include_name` correctly filters by table type. `NullPool` for online migrations is the right choice (single-use connection).

### alembic/versions/0001_add_project_public_column.py
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The migration uses a hardcoded `revision: str = "0001"` instead of the standard auto-generated hash. This works but means future migrations must manually sequence. More importantly, this is the first migration for an existing database — there's no baseline migration capturing the existing schema. This means `alembic upgrade head` on a fresh database would add the `public` column to a table that doesn't exist yet (the `schema.sql` init script handles table creation). The project currently uses `schema.sql` for fresh installs and this migration for upgrades, which is a dual-path that can diverge. This is a known pattern but worth flagging. The `server_default="false"` is correct for backfilling existing rows.

### expert_service/api/data.py (auth on write endpoints)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

All five POST endpoints (`/import/sources`, `/import/entries`, `/import/beliefs`, `/link-entries-sources`, `/chunk-sources`) now have endpoint-level `dependencies=[Depends(verify_auth)]`, which overrides the router-level `verify_auth_or_public`. This correctly ensures write operations require authentication even for public projects. The layering (router-level public for reads, endpoint-level strict for writes) is sound.

### tests/test_auth.py:TestPublicProjectAccess
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Four test cases covering the key scenarios: anonymous on public project (200, identity="public", role="reader"), anonymous on private project (401), anonymous on nonexistent project (401), and authenticated user on public project preserves real identity (200, identity="api", role="admin"). The mock setup correctly simulates the DB query. The `_make_public_app` helper creates isolated test apps with `dependency_overrides`, which is the right pattern for FastAPI unit tests.

### Self-Review
**Limitations:** - Could not verify whether the `verify_auth` function leaves the async session in a clean state when it raises HTTPException at line 196, which matters for session reuse in `verify_auth_or_public`
- Did not see the full `_strip_hallucinated_refs` and `_build_sources_section` functions to verify `single_ask` integration is complete
- No test runner output — cannot confirm existing tests still pass with the changed imports and module-level constant relocation
- Could not verify that the `data.router` endpoint-level `Depends(verify_auth)` actually takes precedence over router-level `Depends(verify_auth_or_public)` in FastAPI's dependency resolution (it should based on FastAPI docs, but worth confirming)

## gemini [PASS]

### alembic.ini
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Standard Alembic configuration file. Required for database migrations mentioned in the production hardening task.

### alembic/env.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Standard Alembic environment setup. Correctly excludes `rms_` prefixed tables (likely legacy or managed externally). Uses project settings for database URL.

### alembic/versions/0001_add_project_public_column.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Migration script correctly adds the `public` column to the `projects` table. Matches the model and schema updates.

### expert_service/api/chat.py:ask
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Added support for `single` pass mode and improved error handling for LLM failures (502 response instead of 500). The specific exception list is appropriate for the service dependencies (Anthropic, Google, HTTPX).

### expert_service/api/data.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Explicitly added `verify_auth` to destructive/administrative endpoints (`/import/*`, `/link-entries-sources`, `/chunk-sources`). This is critical because the router-level dependency was relaxed to `verify_auth_or_public`.

### expert_service/app.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** PARTIAL
**Integration:** WIRED

Added FD monitoring to `/health` which directly supports diagnosing the FD exhaustion issue reported. Relaxed auth on RAG endpoints to allow public project access, while sensitive data management endpoints remain protected via explicit overrides in `data.py`.

### expert_service/auth.py:verify_auth_or_public
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Correct implementation of the public project fallback. It maintains the user's real identity if they are authenticated but grants `READER` access if the project is marked public. Logic is verified by new tests in `test_auth.py`.

### expert_service/chat/loop.py:single_ask
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Implements a single-pass retrieval and synthesis flow. This is a useful alternative for models that struggle with multi-round TMS logic (like Gemma3). Reuses existing retrieval primitives correctly.

### expert_service/chat/loop.py:_quick_belief_search
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Implements context budgeting for belief results. Correctly returns only the rows that fit within the budget to ensure consistency between the context string and the source references.

### expert_service/chat/loop.py:_tms_answer_iterative
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Adds truncation for tool results (like Snowflake query data). This prevents context window overflow during multi-round iterations, addressing the 211K token error described in the entries.

### expert_service/db/connection.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Added connection pool limits (`pool_size=5, max_overflow=5`). This is a key part of the fix for file descriptor exhaustion under heavy load.

### expert_service/db/models.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Added `public` boolean column to `Project` model. Used by the new public access logic.

### expert_service/db/schema.sql
VERDICT: PASS
CORRECTNESS: VALID
SPEC_COMPLIANCE: N/A
ISSUE_COMPLIANCE: ADDRESSES
BELIEF_COMPLIANCE: CONSISTENT
TEST_COVERAGE: N/A
INTEGRATION: WIRED
REASONING: SQL schema updated to match the model.
---

### tests/test_auth.py:TestPublicProjectAccess
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Comprehensive tests for the new public project access logic, covering various auth states and project configurations.

### Self-Review
**Limitations:** No unit tests were added for the new `single_ask` function or the truncation logic in `loop.py`, although they were manually verified according to the checkpoint entries. I could not verify the exact token count reduction without running the code against an LLM provider.

### Feature Requests
- Automatically detect and highlight potential circular dependencies introduced by local imports (e.g., in `auth.py`).
- Provide token count estimates for prompts generated in RAG loops.
