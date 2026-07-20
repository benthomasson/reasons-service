# Code Review Report

**Branch:** benthomasson/expert-service#18
**Models:** claude, gemini
**Gate:** [CONCERN] CONCERN

## claude [CONCERN]

### expert_service/api/ask.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Good defensive hardening. The `try/except` with `logger.exception` catches search failures and returns a generic 500 (no detail leakage). The `.get()` calls with defaults prevent `KeyError` on malformed result dicts. `count` falls back to `len(results)` when missing. All changes are covered by thorough tests in `tests/test_ask.py`.

### tests/test_ask.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Comprehensive test suite covering happy path, error handling (multiple exception types), defensive `.get()` defaults, input validation (missing fields, invalid UUID, empty question), and logging verification. Tests correctly mock `rms_api.search` and use FastAPI's `TestClient`. The `test_ask_error_does_not_leak_details` test is a good security-oriented check. One note: the test for `test_ask_returns_beliefs` includes an `OUT` belief in mock results — this is fine since the `/ask` endpoint queries via `rms_api.search` which may or may not filter by truth_value (separate from the `data.py` and `tools.py` filtering changes).

### tests/conftest.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Clean fixture setup. The `ask_app` fixture creates a standalone FastAPI instance with just the ask router — good isolation. `VALID_PROJECT_ID` as a module-level constant is appropriate.

### expert_service/api/data.py (belief filtering)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Adding `AND truth_value = 'IN'` to the FTS search query is correct — OUT beliefs are retracted and shouldn't appear in search results. The filter is applied at the SQL level (efficient) and uses a parameterized constant. Consistent with the same change in `tools.py` and `loop.py`. No tests for this specific endpoint in the diff.

### expert_service/chat/tools.py (belief filtering)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Both `search_knowledge` and `grep_content` now filter `truth_value = 'IN'`. Correct and consistent with the overall belief filtering theme. The ILIKE query in `grep_content` correctly places the new condition before the existing `AND text ILIKE` clause.

### expert_service/chat/loop.py:_compute_idf (extra_where parameter)
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The `extra_where` parameter is string-interpolated into raw SQL via f-strings (`f"SELECT count(*) FROM {table} {where}"`). While the only current caller passes a hardcoded literal `"AND truth_value = 'IN'"`, this is a latent SQL injection surface — any future caller passing user input would be exploitable. The `table` parameter already has this same risk, but `extra_where` widens it. Consider using parameterized conditions instead (e.g., pass a dict of column=value conditions rather than raw SQL fragments). This is a **design concern**, not an active vulnerability.

### expert_service/chat/loop.py:_quick_belief_search (belief filtering + internal URLs)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The `truth_value = 'IN'` filter is applied both in the IDF computation (`extra_where`) and the main query. Internal URL generation (`/projects/{project_id}/source/{r.source}`) correctly matches the `source_view` route pattern in `app.py`. The `"/" in r.source` guard is sensible — entries have paths like `entries/2026/04/23/topic.md` while derived beliefs don't contain slashes.

### expert_service/chat/loop.py:_build_sources_section (return type change)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Return type changed from `str` to `tuple[str, dict[str, int]]`. Both callers (`dual_ask` at line 715 and `dual_chat_stream` at line 793) already destructure as `sources_section, cite_map = ...` and `sources_section, _cite_map = ...` respectively. The empty case returns `("", {})` which is correct — `cite_map` is empty when there are no sources.

### expert_service/chat/loop.py:_search_source_chunks (internal URLs)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Same internal URL pattern as `_quick_belief_search`. Uses `r.slug` which maps to the source slug — the `source_view` endpoint extracts `Path(path).stem` which would match a slug like `scan-ftl-reasons`. The fallback logic (generate URL only when `r.url` is empty) is correct.

### expert_service/app.py:source_view
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** PARTIAL

The endpoint extracts `topic = Path(path).stem` to look up entries. This works for paths like `entries/2026/04/23/scan-ftl-reasons.md` → topic `scan-ftl-reasons`. However, if two entries share the same topic slug (from different `--entries-dir` paths), `.limit(1)` returns an arbitrary one with no ordering guarantee. Also, the query uses `Entry.topic == topic` without any index hint — on large tables this could be slow. The `{path:path}` catch-all route parameter accepts any path, which is fine for FastAPI routing but means the endpoint silently 404s for non-entry paths without distinguishing "bad path format" from "entry not found."

### expert_service/app.py:entry_view
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Straightforward entry viewer by ID. Uses composite key lookup `(project_id, entry_id)` which matches the Entry model's composite primary key. Returns the same template and context as `source_view`. No issues.

### expert_service/templates/entries/view.html
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The template correctly uses `json.dumps()` (server-side) + `{{ content_json | safe }}` to inject markdown as a JS string literal — safe because `json.dumps` escapes `</script>`, quotes, and backslashes. The `marked.js` link renderer blocks `javascript:` and `data:` protocols via the regex check, and escapes all output via `escapeHtml()`. One minor note: the link sanitizer is duplicated between this template and `chat.html` — consider extracting to a shared JS partial.

### expert_service/templates/chat/chat.html (link sanitizer)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The XSS fix for `marked.js` link rendering is correct. The regex `!/^https?:\/\//i.test(href) && !href.startsWith('/')` correctly allows only `http://`, `https://`, and root-relative URLs. All output is escaped via `escapeHtml()`. Matches the fix referenced in commit `498bbc9`.

### scripts/load_reasons_db.py
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Several concerns:

1. **Entry ID generation**: Uses `sha256(f"{topic}:{content[:200]}")[:12]` — if two entries across different `--entries-dir` paths have the same topic and similar first 200 chars, they'll collide. The `ON CONFLICT DO NOTHING` means the second one is silently dropped.

2. **Source deletion ordering**: When both `--sources-dir` and `--entries-dir` are provided, sources are deleted and reimported first, then entries also insert into `sources` table. But entries use `ON CONFLICT ... DO UPDATE`, so they'll overwrite any source with the same slug. This is probably intentional but the interaction between `DELETE FROM sources` (line ~197) and the entries loop inserting new sources (line ~240) could be confusing.

3. **`_parse_arg_multi`** returns raw strings without validation — passing `--entries-dir` with no paths silently returns `[]`, which is fine, but `--entries-dir --domain foo` would treat `--domain` as not starting with `--` ... wait, no, it does check `startswith("--")` so that's correct.

4. **`source_id` variable reuse**: `source_id` is generated as a UUID string, then reassigned from `cur.fetchone()[0]` (the RETURNING clause). On conflict (DO UPDATE), this returns the existing row's ID, not the new UUID — correct behavior but the variable reuse is subtle.

5. **No rollback on partial failure**: If the script fails mid-import (e.g., one entry has invalid data), committed sources/entries from before the failure persist while later ones don't. The `pg.commit()` is only at the end, so actually this is fine — failure before commit means nothing is saved.

### Self-Review
**Limitations:** - Could not verify the `rms_api.search` implementation in `reasons_lib` to confirm whether it already filters by `truth_value` (the `/ask` endpoint delegates to it without the `IN` filter that was added to `data.py` and `tools.py` — potential inconsistency)
- No test files exist for `data.py`, `tools.py`, `loop.py`, `app.py` endpoints, or `load_reasons_db.py` — cannot assess if existing tests break
- Could not verify the `sources` and `source_chunks` table schemas to confirm the INSERT columns match
- Did not check if `entry_sources` junction table is affected by the cascade deletes in `load_reasons_db.py`

### Feature Requests
- Include the database schema (`schema.sql`) alongside changes that modify SQL queries, to verify column names and constraints
- Show existing tests for modified files so I can check for test breakage from return type or behavior changes
- Flag when a return type change is made and automatically show all callers in the diff context

## gemini [PASS]

### expert_service/api/ask.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** MEETS
**Test Coverage:** COVERED
**Integration:** WIRED

Added robust error handling with proper logging and generic 500 responses to prevent leaking sensitive details. Implemented defensive dictionary access for search results, ensuring the endpoint remains stable even if result schemas vary slightly.

### expert_service/api/data.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** MEETS
**Test Coverage:** UNTESTED
**Integration:** WIRED

Correctly added the `truth_value = 'IN'` filter to the SQL query. This aligns with the architectural requirement to only expose active beliefs in search results.

### expert_service/app.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** MEETS
**Test Coverage:** UNTESTED
**Integration:** WIRED

Successfully added `source_view` and `entry_view` endpoints. The use of `Path(path).stem` correctly maps arbitrary source paths to entry topics as defined in the ingestion process. Proper 404 handling is included.

### expert_service/chat/loop.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** MEETS
**Test Coverage:** PARTIAL
**Integration:** WIRED

Retrieval logic was updated to filter for `IN` beliefs consistently. The generation of internal URLs for sources provides a fallback when external links are missing, improving the user experience. The return type update for `_build_sources_section` is correctly integrated with its callers.

### expert_service/chat/tools.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** MEETS
**Test Coverage:** UNTESTED
**Integration:** WIRED

Applied the `truth_value = 'IN'` filter to `search_knowledge` and `grep_content` tools, ensuring consistency across all search-based chat tools.

### expert_service/templates/chat/chat.html
VERDICT: PASS
CORRECTNESS: VALID
SPEC_COMPLIANCE: MEETS
ISSUE_COMPLIANCE: N/A
BELIEF_COMPLIANCE: CONSISTENT
TEST_COVERAGE: N/A
INTEGRATION: WIRED
REASONING: Implemented a safe Markdown link renderer that blocks dangerous protocols like `javascript:` and `data:`. This is a significant security improvement for rendered chat content.

---

### expert_service/templates/entries/view.html
VERDICT: PASS
CORRECTNESS: VALID
SPEC_COMPLIANCE: MEETS
ISSUE_COMPLIANCE: N/A
BELIEF_COMPLIANCE: CONSISTENT
TEST_COVERAGE: N/A
INTEGRATION: WIRED
REASONING: New template for viewing source entries is well-structured and also utilizes the safe Markdown renderer.

---

### scripts/load_reasons_db.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** MEETS
**Test Coverage:** UNTESTED
**Integration:** WIRED

The ingestion script was greatly enhanced to support multi-directory entry imports, source tracking, and markdown chunking for FTS. The use of PostgreSQL's `ON CONFLICT` and `RETURNING` clauses ensures efficient and idempotent data loading.

### tests/test_ask.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** MEETS
**Test Coverage:** COVERED
**Integration:** WIRED

This is a comprehensive test suite that covers not only the happy path but also detailed edge cases like partial result dictionaries and various error conditions (DB timeouts, connection errors).

### Self-Review
**Limitations:** I verified the integration of `_build_sources_section` by reading the full context of `expert_service/chat/loop.py` since the provided diff hunk was partial. The `truth_value = 'IN'` filter consistency was verified across multiple files to ensure it met architectural intent.
