# Code Review Report

**Branch:** benthomasson/expert-service#23
**Models:** claude, gemini
**Gate:** [CONCERN] CONCERN

## Disagreements

The following changes have different verdicts across models:

- **expert_service/auth.py:verify_auth_or_public** [LOW]: claude: CONCERN, gemini: PASS

## claude [CONCERN]

### expert_service/auth.py:verify_auth_or_public
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The function works correctly for the happy path — it checks the project's `public` flag via raw SQL and short-circuits auth for public projects. However, two concerns:

1. **No `project_id` fallthrough**: When `project_id` is missing from path params (shouldn't happen given the router prefix, but defensive code matters for auth), it falls through to `verify_auth`, which is correct.

2. **Non-existent project returns None row, falls through to `verify_auth`** — correct behavior.

3. **No tests exist** for `verify_auth_or_public`. Given this is a security-critical function that controls unauthenticated access to data, this is the most important gap in the PR. Tests should cover: public project bypasses auth, non-public project requires auth, non-existent project requires auth, missing `project_id` requires auth.

### expert_service/app.py (router wiring)
**Verdict:** CONCERN
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`data.router`, `chat.router`, and `ask.router` use `verify_auth_or_public` at the router level. The data router's write endpoints (`/import/sources`, `/import/entries`, etc.) have their own `Depends(verify_auth)` at the endpoint level, so they remain protected. Read endpoints on public projects become accessible without auth, which appears intentional.

However, `data.router` GET endpoints have no RBAC checks via `require_action` — the only protection is the router-level dependency. This means a public project exposes all data read endpoints (beliefs, sources, entries, search, deep-search, what-if) to anonymous users. If that's intentional, fine; if some should remain private even for public projects, this is a gap.

### expert_service/api/data.py (write endpoint auth hardening)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

All five write endpoints (`/import/sources`, `/import/entries`, `/import/beliefs`, `/link-entries-sources`, `/chunk-sources`) now have explicit `Depends(verify_auth)` at the endpoint level. This ensures they require authentication even though the router-level dependency was relaxed to `verify_auth_or_public`. This is the correct defense-in-depth pattern. When both router-level and endpoint-level dependencies run, FastAPI executes both — if the endpoint-level `verify_auth` fails, the request is rejected regardless of the router-level result.

### expert_service/api/chat.py:ask
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The bare `except Exception` catches everything — programming errors, `KeyError`, `TypeError`, validation bugs — and masks them all as 502 "LLM temporarily unavailable." While `logger.exception` preserves the actual error in logs, the 502 status code is semantically incorrect for non-LLM failures and will mislead debugging efforts. Consider catching a narrower set of exceptions (e.g., `anthropic.APIError`, `httpx.HTTPError`, LLM-specific errors) or at minimum re-raising certain error types.

Also: `logger = logging.getLogger(__name__)` is placed before the `from expert_service.chat.loop import ...` line with no blank line separation, which reads oddly (though it works).

Also: `single_ask` doesn't call `_get_project_connectors`, so it skips connector-based data sources (e.g., Snowflake). This may be intentional for "smaller models" but isn't documented at the API level — a caller using `mode=single` silently loses connector access.

### expert_service/chat/loop.py (context budget constants + belief truncation)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Constants moved from mid-file to module top — cleaner. `MAX_BELIEF_CONTEXT_CHARS = 30000` is enforced in `_quick_belief_search` with a correct accumulator pattern that updates `belief_rows` to match what was actually included. Tool result truncation at 10K chars is applied in two places in `_tms_answer_iterative`: when building the history section (line ~669) and when receiving new `query_data` results (line ~710). Both truncation points add `[...truncated]` markers. The simple `[:MAX_TOOL_RESULT_CHARS]` slice could split a multi-byte character, but for this use case (context for an LLM) that's acceptable.

### expert_service/chat/loop.py:single_ask
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Clean implementation. Parallel retrieval via `asyncio.gather`, single LLM call, then post-processing with `_strip_hallucinated_refs` and `_build_sources_section`. Correctly reuses existing retrieval functions. The prompt is well-structured with clear instructions for citation format.

### expert_service/db/models.py + schema.sql + alembic migration
**Verdict:** CONCERN
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The `public` column is consistently added across three places: SQLAlchemy model (`server_default="false"`), `schema.sql` (`DEFAULT FALSE`), and Alembic migration (`server_default="false"`). The Alembic migration uses a human-readable revision ID `"0001"` instead of an auto-generated hash — works fine but could confuse future `alembic revision --autogenerate` runs.

**Important**: CLAUDE.md states "**Schema-first**: No Alembic — tables created via `schema.sql`" but this PR introduces Alembic. CLAUDE.md should be updated to reflect this dual approach, otherwise future contributors will be confused.

### alembic/env.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Standard Alembic env.py. Uses `settings.database_url_sync` correctly. The `_EXCLUDED_PREFIXES = ("rms_",)` filter in `include_name` prevents Alembic from managing RMS tables, which is appropriate. Both offline and online migration modes are implemented.

### expert_service/db/connection.py (pool caps)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`pool_size=5, max_overflow=5` on both async and sync engines caps total connections at 10 each (20 total). This is a sensible default that prevents FD exhaustion while still allowing concurrency. The caps only apply to PostgreSQL engines (not SQLite), which is correct — the SQLite branch is unchanged.

### expert_service/app.py:_open_fds
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Defensive with platform fallbacks (macOS `/dev/fd`, Linux `/proc/self/fd`, -1 fallback). Uses `resource.getrlimit` for limits. Imported inside the function body rather than at module top, but this is a helper for a non-critical health endpoint. Wired to `/health` which now returns FD info.

### expert_service/api/projects.py (public field)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

`public` field added to `ProjectCreate` (default `False`), `ProjectResponse`, and create/list/get endpoints. Consistent across all three response paths. Default `False` ensures existing projects remain private.

### Self-Review
**Limitations:** Could not verify whether FastAPI correctly runs both router-level and endpoint-level dependencies when both are present (relied on FastAPI documentation knowledge). Could not see the full `loop.py` file to verify no other callers of the moved constants. No test runner output to confirm existing tests still pass with the model changes.

### Feature Requests
- Include existing test files in the diff when source files they test are modified, to verify test assertions still match
- Flag when CLAUDE.md/README instructions contradict the changes being made
- Show RBAC enforcement points (or lack thereof) when auth dependencies are modified

## gemini [CONCERN]

### .claude/checkpoint.md
VERDICT: PASS
CORRECTNESS: VALID
SPEC_COMPLIANCE: N/A
ISSUE_COMPLIANCE: N/A
BELIEF_COMPLIANCE: N/A
TEST_COVERAGE: N/A
INTEGRATION: WIRED
REASONING: Updated to reflect the current state of the project, specifically documenting the FD exhaustion and context window fixes.
---

### alembic/
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Standard Alembic initialization and a migration for the `public` column. The `include_name` filter in `env.py` is a good practice to prevent Alembic from attempting to manage tables prefixed with `rms_` (likely managed by the `ftl-reasons` library).

### expert_service/api/chat.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The `/ask` endpoint now supports a `single` pass mode (useful for smaller/local models) and includes a `try/except` block to return a 502 status code instead of a 500 traceback upon LLM failure, which improves production stability.

### expert_service/api/projects.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Correctly exposes the new `public` field in project creation and retrieval APIs.

### expert_service/app.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

- Added a useful `_open_fds` helper to the `/health` endpoint for monitoring file descriptor usage.
- Updated router dependencies to use `verify_auth_or_public`, enabling the "public project" feature across chat and data APIs.

### expert_service/auth.py:verify_auth_or_public
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Implementation is sound; it checks the database for project publicity before falling back to standard authentication. Note: This adds a database query to every authenticated request on these routes, but for the current scale, this is an acceptable trade-off for simplicity.

### expert_service/chat/loop.py
**Verdict:** CONCERN
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

- **Production Hardening**: The addition of `MAX_BELIEF_CONTEXT_CHARS` and `MAX_TOOL_RESULT_CHARS` directly addresses the context window overflow issue reported in the entries.
- **Single Pass Mode**: `single_ask` provides a streamlined path for models that struggle with the dual-path merge logic.
- **CONCERN**: No automated tests were added for the `single_ask` logic or the new truncation behavior in `_quick_belief_search` and `_tms_answer_iterative`. While the implementation looks correct, these are critical paths for reliability.

### expert_service/db/connection.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Capping `pool_size` and `max_overflow` to 5/5 is the correct architectural fix for the file descriptor exhaustion issue (Errno 24) identified during load testing.

### Self-Review
**Limitations:** - I could not verify if `Role.READER` is correctly defined as an Enum value in `expert_service/rbac.py` as that file was not in the diff, though usage in `auth.py` implies it exists.
- I assumed `_strip_hallucinated_refs` and `_build_sources_section` are correctly implemented elsewhere as they are used but not defined in the provided diff (except for their usage in the new `single_ask` function).
