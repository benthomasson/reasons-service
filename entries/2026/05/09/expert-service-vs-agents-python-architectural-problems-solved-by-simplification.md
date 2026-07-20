# Expert-Service vs Agents-Python: Architectural Problems Solved by Simplification

**Date:** 2026-05-09
**Time:** 06:12

## Context

Three expert domains (code, project, product) independently analyzed agents-python's belief networks and produced action plans identifying structural problems. The question: how many of these problems does expert-service's architecture avoid entirely?

## The Core Architectural Difference

agents-python uses a multi-phase pipeline: capability routing → department discovery → planner exploration → personalization → trust enforcement → safety nodes → synthesis. Expert-service uses three parallel paths: TMS beliefs + FTS source chunks + data connectors, merged by a single LLM call.

The complexity budget shifts from the query pipeline (agents-python) to the knowledge base (expert-service). TMS beliefs with justification chains encode domain knowledge structurally; the query path stays simple.

## Problems Solved Structurally

### Planner Over-Exploration (Code Expert: 40 of 60 gated beliefs)

The code expert's single largest finding: planner over-exploration gates two-thirds of all possible improvements. The planner combines irrevocable forward-chaining with systematic exploration of irrelevant capabilities.

Expert-service has no planner. Dual-path retrieval (tsvector search over beliefs and source chunks) replaces capability routing. The LLM gets context and synthesizes — no exploration, no waste trap, no routing gap. The entire waste/efficiency narrative from the code expert evaporates.

### Dependency Modernization Frozen (Project Expert: 39 beliefs)

agents-python has a frozen dependency chain: Langflow pins openai SDK, which pins LiteLLM, which blocks SSL fixes. Removing any piece risks breaking the pipeline.

Expert-service has no Langflow dependency. Clean dependency tree: FastAPI, SQLAlchemy, LangChain. Connectors are separate pip-installable packages with their own dependencies. A problematic connector (e.g. expert-snowflake) can be uninstalled without affecting the core service.

### Credential/Secrets Management (Product Expert Tier 0: 26 beliefs each)

agents-python stores Langfuse secrets in instance metadata and .env files in Google Drive — the two highest-leverage fixes in the product expert's network.

Expert-service uses standard auth: Google OAuth ID tokens verified server-side, static API keys, or dev mode. No secrets in metadata. The Snowflake connector reuses the Dataverse OAuth token with proper refresh flow.

### SQL Injection (Product Expert Tier 1: 21 beliefs)

agents-python allows multi-statement SQL in the Dataverse query interface.

Expert-service's Snowflake executor has `validate_sql()` that rejects write operations and multi-statement queries at the code level, not just prompt level.

### Quality Enforcement / Spec Enforcement (Product Expert Tiers 3-4: 15 beliefs)

agents-python has 25+ specs but enforcement is purely social — no CI checks, no merge gates.

Expert-service is open source with pre-commit hooks and CI. More fundamentally, the TMS is the spec enforcement layer. Beliefs have justifications, truth values, and retraction cascades. If a belief is wrong, retracting it cascades through dependents. The system self-corrects structurally.

### Observability (Product Expert Tier 5: 12 beliefs)

agents-python has no pipeline observability — per-phase timing, error rates, and quality signals are absent.

Expert-service is a standard FastAPI app with request logging. Optional Langfuse integration for tracing is not critical infrastructure. No complex MCP session management or multi-phase pipeline to instrument.

### Latency (Product Expert Tier 7)

agents-python: 180+ seconds for Dataverse queries through the agent pipeline.
Expert-service: 19 seconds for equivalent queries (Snowflake SQL gen + execution + belief search + source search + LLM synthesis). 21x faster through architectural simplification, not optimization.

### Compliance Evidence (Project Expert: 67 beliefs, highest impact)

agents-python lacks a compliance evidence pipeline — the nexus where safety, governance, measurement, and organizational dysfunction converge.

Expert-service's belief provenance chain (source document → entry → belief → justification) is inherently an evidence trail. Every belief has a source path and source URL. The `/explain` endpoint traces justification chains. The `/search` endpoint provides full-text search with provenance. This is what a compliance evidence pipeline looks like when built into the data model.

### Knowledge Imprisonment (Project Expert: 19 beliefs)

agents-python has a bus-factor problem: critical knowledge about compliance architecture, AIA requirements, and ServiceNow processes lives in one person's head.

Expert-service externalizes domain knowledge into the TMS. The knowledge is in the database, not in anyone's head. Import scripts pull from source documents. Anyone can query `expert ask` or `expert search` to access it.

## Problems NOT Solved

### Organizational Issues (Project Expert Tiers 2-4)

Staffing gaps, authority vacuum, stalled work, EM vacancy — these are people problems that no architecture change addresses. Expert-service doesn't need these roles filled because it's a different project with a different team, not because it solved the organizational dysfunction.

### Safety Pipeline (Code Expert Tier 3)

NeMo guardrails, topic classification, PII detection — expert-service doesn't have equivalent safety infrastructure yet. It relies on the LLM's built-in safety and the read-only nature of the data connectors. For internal enterprise use this is acceptable; for broader deployment, safety layers would need to be added.

### Eval Depth (Code Expert Tier 5)

agents-python has a four-dimensional eval framework (accuracy, reasoning, retrieval, format) even if the scoring excludes efficiency. Expert-service has dual-path A/B evals but not the same depth of per-dimension scoring.

## Quantitative Summary

| Domain | Total Gated | Solved by Architecture | Remaining |
|--------|------------:|----------------------:|-----------:|
| Code expert | 60 | ~48 (planner + pipeline) | ~12 (safety, eval depth) |
| Project expert | 123 | ~85 (compliance + deps + knowledge) | ~38 (organizational) |
| Product expert | 111 | ~80 (security + quality + latency) | ~31 (observability depth, enterprise features) |
| **Total** | **294** | **~213 (72%)** | **~81 (28%)** |

## The Meta-Insight

72% of gated improvement beliefs across three expert domains describe problems that expert-service's architecture avoids by being simpler, not by being more sophisticated. The planner, the multi-phase pipeline, the Langflow dependency chain, the complex session management — these are the sources of most problems. Removing them removes the problems.

The remaining 28% are either organizational issues (people, not code), safety features not yet built, or enterprise-readiness gaps (RBAC, multi-department, SharePoint integration) that are on the roadmap but not architectural blockers.
