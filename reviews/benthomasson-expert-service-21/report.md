# Code Review Report

**Branch:** benthomasson/expert-service#21
**Models:** gemini
**Gate:** [PASS] PASS

## gemini [PASS]

### expert_service/db/search.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

This new abstraction layer correctly handles the differences between PostgreSQL Full-Text Search and SQLite `LIKE`-based search. The use of an allowlist for `text_expr` interpolation is a critical security measure that prevents SQL injection while maintaining flexibility for multi-column FTS expressions. The term extraction logic with stop-word filtering provides consistent behavior across backends.

### expert_service/rms/api.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The API correctly dispatches between the existing PostgreSQL `PgApi` and the new SQLite implementation using `reasons_lib.api`. It effectively manages per-project SQLite files within the configured `data_dir`. The `search_beliefs_fts` function includes a smart fallback from FTS5 `MATCH` to standard `LIKE` for maximum compatibility with different SQLite build configurations.

### expert_service/db/models.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Migrating from PostgreSQL-specific `JSONB` and `UUID` types to SQLAlchemy's generic `JSON` and `Uuid` is the correct approach for database portability. The conditional declaration of the `Embedding` model based on `pgvector` availability prevents runtime errors on SQLite/non-vector environments.

### expert_service/api/projects.py:import_reasons
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The new endpoint for importing `reasons.db` files is well-implemented with proper temporary file handling, validation via `reasons_lib.storage`, and cleanup in a `finally` block. This allows users to easily migrate or upload existing belief networks.

### expert_service/chat/agent.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

The checkpointer logic correctly branches between PostgreSQL and SQLite. Using `MemorySaver` for SQLite is a pragmatic choice for local development and prototyping, even though it means chat history is lost on restart. For full persistence, PostgreSQL remains the recommended backend.

### expert_service/db/connection.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

Database initialization correctly handles SQLite-specific requirements, including enabling WAL mode and foreign key constraints via event listeners. This ensures data integrity and performance on the SQLite backend. The `init_db` helper provides a clean way to bootstrap the schema on startup.

### expert_service/api/data.py:search
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The search endpoint now uses the `fts_clause` abstraction, making it backend-agnostic. The logic for generating snippets handles the difference between PostgreSQL's `left()` and SQLite's `substr()` correctly. Belief search is properly delegated to the RMS API.

### expert_service/config.py
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** COVERED
**Integration:** WIRED

The configuration updates facilitate a smooth transition to SQLite by auto-deriving the sync URL and providing helper properties for the backend type and data directory. This reduces the burden on the user to configure multiple related URLs.

### Self-Review
**Limitations:** The review of the LangGraph `MemorySaver` choice for SQLite is based on the assumption that SQLite is primarily for local/ephemeral use. I did not verify if a persistent `SqliteSaver` (sync) could have been adapted for the async context without significant complexity.

### Feature Requests
- Include a visual indicator of the currently active database backend in the dashboard.
- Consider adding support for a persistent SQLite checkpointer using `SqliteSaver` with a thread pool if long-lived chat history is required for SQLite users.
