# Code Review Report

**Branch:** benthomasson/expert-service#22
**Models:** claude, gemini
**Gate:** [CONCERN] CONCERN

## claude [CONCERN]

### expert_service/config.py:llm_enabled
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

`llm_enabled` is a `@property` that calls `os.getenv()` on every access rather than capturing the value once at construction time. This means the value could theoretically change between accesses if something mutates `os.environ` mid-process — unlikely but inconsistent with how the other settings fields work (captured once at init via `os.getenv` defaults). More practically, every `settings.llm_enabled` check re-reads the environment, which is wasteful. Since `settings` is a module-level singleton and the conditional imports in `app.py` happen at import time, a runtime change to `EXPERT_LLM` wouldn't re-register routes anyway — so the property gives a false impression of dynamism. A plain field like `llm_enabled: bool = os.getenv("EXPERT_LLM", "true").lower() not in ("false", "0", "no")` would be more consistent with the rest of `Settings`.

### expert_service/app.py (module-level conditional imports)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The conditional import guard at module level cleanly prevents loading `langchain`/`langgraph` in no-LLM mode. The stub `invalidate_meta_cache` no-op is appropriate since the real function just clears a dict. The test `test_no_llm_deps_in_no_llm_mode` validates this via subprocess isolation.

### expert_service/app.py (route registration)
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The `/ask` route shadowing between `chat.router` and `ask.router` is acknowledged in comments and works by FastAPI's first-match semantics, but it's fragile. In LLM mode, both routers register `POST /api/projects/{project_id}/ask` — the chat version wins because it's included first. If someone reorders the `include_router` calls, the behavior silently changes. A cleaner approach would be to not register `ask.router` at all in LLM mode (since chat.router already provides `/ask`), or to conditionally exclude the `/ask` endpoint from one of the routers.

### expert_service/app.py (conditionally defined route handlers)
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Wrapping `@app.get(...)` definitions inside `if settings.llm_enabled:` blocks works correctly — the decorator registers the route at definition time, so skipping the definition skips registration. The `meta_chat_page`, `chat_page`, and `ingest_form` handlers are correctly guarded. Users hitting these URLs in no-LLM mode will get a 404 from FastAPI (method not allowed / not found), which is appropriate.

### expert_service/app.py:health
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Adding `"llm"` to the health response is a clean, non-breaking addition. Tested by `test_health_reports_llm_enabled`.

### expert_service/api/projects.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** PARTIAL
**Integration:** WIRED

Same conditional import pattern as `app.py` for `invalidate_meta_cache`. Correctly prevents loading the LLM dependency chain through `meta_agent`. The stub no-op is appropriate. No direct test of this file's conditional import specifically, but covered indirectly by the subprocess-based route/module tests.

### expert_service/templates/base.html
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Correctly hides the Meta-Expert nav link and shows "(data-only mode)" in the footer when LLM is disabled. The `llm_enabled` global is set on the Jinja2 environment in `app.py:95`.

### expert_service/templates/projects/detail.html
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Correctly gates Chat, Add Sources, and Propose Beliefs action buttons behind `llm_enabled`. Review Beliefs remains visible (it's a data operation, not LLM-dependent). The "No entries yet" empty state also correctly hides the ingest link.

### expert_service/templates/projects/list.html
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Meta-Expert button correctly gated.

### expert_service/templates/beliefs/review.html
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The "Propose beliefs" link in the empty-state message is correctly gated. Users in no-LLM mode can still review beliefs (manually imported or via API), they just can't access the LLM-powered proposal flow.

### expert_service/templates/entries/view.html
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Back-link correctly points to chat in LLM mode and to the project page in no-LLM mode. Good UX adjustment.

### expert_service/templates/reports/view.html
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Explain/What-if buttons on belief references are gated behind `llm_enabled` since those endpoints hit the LLM. The belief highlighting (`belief-ref` class, `data-belief` attribute) is still applied regardless, which is correct — it's just the interactive LLM buttons that are hidden.

### tests/test_llm_mode.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Excellent test design. Subprocess-based route tests avoid import-time caching issues that would plague in-process tests. `TestLlmEnabledProperty` covers the env var parsing thoroughly with parametrize. `test_no_llm_deps_in_no_llm_mode` verifies the core value proposition (no langchain/langgraph loaded). The only minor gap is that template rendering is not tested (templates are UNTESTED), but that's reasonable for a unit test suite.

### Self-Review
**Limitations:** Could not verify whether the Explain/What-if buttons in `reports/view.html` actually call LLM-dependent API endpoints (only saw the JS template guard, not the full JS). Template rendering tests are absent — I verified the Jinja2 global is wired but can't confirm rendering correctness without running the app. Did not check whether other importers of `expert_service.chat` modules exist outside of the files touched in this diff (the explore agent found none, but there could be scripts or tests).

### Feature Requests
- Include the full content of template files (not just diff hunks) — templates often have JS at the bottom that references gated features
- Show the callers graph for functions whose signatures or import paths change (e.g., who imports `invalidate_meta_cache`)
- Include existing test files that test modified source files, to catch breakage from changed return types or route registrations

## gemini [PASS]

### expert_service/config.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The `llm_enabled` property correctly implements the environment variable toggle. The parsing logic is robust, handling various truthy/falsy strings and providing a sensible default of `True`.

### expert_service/api/projects.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The conditional import of `invalidate_meta_cache` prevents loading heavy LLM dependencies when they are not needed. Providing a dummy `pass` implementation ensures that any existing calls to this function in the `projects` API remain functional without complex conditional logic at every call site.

### expert_service/app.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The route registration is correctly guarded by `llm_enabled`. The order of inclusion (LLM routers before `ask.router`) allows for an elegant fallback mechanism where the LLM-powered `/ask` endpoint shadows the FTS-only version when enabled. UI routes are also appropriately partitioned.

### expert_service/templates/
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The UI changes are comprehensive, updating navigation, buttons, and interactive elements across multiple templates. Setting `llm_enabled` in the Jinja2 global environment is an efficient way to make the state available to all templates without repeating context in every route handler.

### tests/test_llm_mode.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The testing strategy is excellent. Specifically, using subprocesses to verify route presence and dependency imports ensures that the test environment isn't contaminated by previous imports, providing high confidence that "no-LLM mode" actually achieves the goal of avoiding heavy dependency loading.

### Self-Review
**Limitations:** I did not have visibility into `expert_service/api/ask.py` to verify it is truly free of LLM dependencies. However, the `test_no_llm_deps_in_no_llm_mode` test empirically confirms that importing the application with `EXPERT_LLM=false` does not load `langchain` or `langgraph`, which validates the architectural goal regardless of the internal implementation of individual modules.

### Feature Requests
- Include a list of all endpoints (routes) in the observation context when reviewing changes to API routers to help verify shadowing/precedence behavior.
