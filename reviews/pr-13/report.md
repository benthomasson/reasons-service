# Code Review Report

**Branch:** benthomasson/expert-service#13
**Models:** claude, gemini
**Gate:** [CONCERN] CONCERN

## claude [CONCERN]

### Feature Requests
- Include the full function body for any function whose signature changed, not just the diff hunks — the compact format builder in `ask.py` is small enough to see, but `_build_sources_section` in `loop.py` is 70+ lines and only 4 lines of diff were shown
- Flag unrelated changes automatically (changes in the diff that don't map to the issue description) so reviewers can assess scope creep

## gemini [PASS]

### expert_service/api/ask.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** MEETS
**Test Coverage:** COVERED
**Integration:** WIRED

The implementation now correctly wraps the search call in a try/except block, logs failures server-side, and returns a clean 500 error to the client. It also uses `.get()` for all result fields, preventing KeyErrors when the RMS API returns incomplete data.

### expert_service/chat/loop.py:_build_sources_section
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

This change refactors the sources section builder to return a citation map for inline replacement. While unrelated to the /ask error handling task, the change is internally consistent; all callers in `loop.py` (L705, L783) have been updated to handle the new tuple return type.

### tests/test_ask.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** MEETS
**Test Coverage:** COVERED
**Integration:** WIRED

Provides thorough coverage for both happy paths and edge cases, including DB connection failures, internal KeyErrors, and missing fields in result dictionaries. It ensures that sensitive details (like DB URLs) do not leak in error responses.

### Self-Review
**Limitations:** I verified all callers of `_build_sources_section` in `loop.py` but the provided diff for that file was partial (it omitted the updated return statement at the bottom of the function, which I verified via `read_file`). I also confirmed the return type contract of `rms_api.search` to ensure the defensive `.get()` calls were appropriately placed.
