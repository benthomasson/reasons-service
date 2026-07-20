# Expert Service Roadmap: Editing Workflow, RBAC, and Tag-Based Access Control

**Date:** 2026-05-05
**Time:** 16:24

## Context

Expert-service has been validated through evals and manual testing. The system works, is valuable, and is potentially viable as a product. The meta-chat successfully queries across expert domains, and the TMS belief pipeline produces accurate, well-sourced answers.

The next question is: what comes before operational deployment?

## Editing Workflow First

The original plan was: deploy to cloud VM/container, then automate KB building. But if the UI is the main driver, then belief editing and contradiction reconciliation must happen in the UI before deployment. Users can't SSH in and run `reasons challenge` from the CLI.

The editing surface needed:

- **Browse/search beliefs** — already partially supported via chat
- **Challenge a belief** — "this is wrong because..." creates challenge node, retracts target, cascades dependents OUT
- **Defend a belief** — restore a challenged belief with a counter-argument
- **Reconcile contradictions** — show nogoods, let editor pick which belief to retract
- **View staleness** — flag beliefs with hash mismatches, let editor confirm retraction or refresh

The RMS operations already exist in `expert_service/rms/api.py` via `reasons_lib.pg.PgApi`. The work is exposing them through API endpoints and building the UI controls.

## RBAC: Two Orthogonal Dimensions

Access control has two independent dimensions:

### Dimension 1: Role (what you can do)

- **Reader** — query, chat, browse beliefs
- **Editor** — challenge, retract, reconcile, defend
- **Admin** — import, derive, project config, user management

### Dimension 2: Scope (what you can see)

- **Project-level** — which expert projects you have access to
- **Tag-level** — within a project, which `access_tags` you can see

These are independent. An editor on `redhat-expert` who can only see `engineering`-tagged beliefs is different from a reader who can see everything. Role controls the verbs, scope controls the nouns.

## Tag Inheritance Through Dependency Chains

Policy decision: **beliefs inherit all tags of their dependents.** A user needs access to all tags in the dependency chain to see a belief.

This is the strict model. It prevents information laundering where someone derives a bland-sounding belief from restricted premises and the restriction gets lost. Tag propagation makes the restriction sticky through the entire chain.

Example: If belief A (tagged `engineering`) depends on belief B (tagged `finance`), then belief A effectively requires both `engineering` and `finance` access. A user with only `engineering` access cannot see it.

This is already how `trace-access-tags` works in ftl-reasons. The implication is that the derivation step should auto-compute and store inherited tags rather than tracing at query time, to avoid walking the full dependency graph on every query.

## Stale and Contradictory Beliefs

The biggest ongoing cost of a TMS is maintenance:

- **Stale beliefs** are detectable mechanically — file hashes, `reasons check-stale`, source timestamps. Automatable.
- **Contradictory beliefs** require semantic understanding and human judgment. The meta-expert surfaces these most effectively because individual experts have consistent internal views but different information horizons.

The gardening — reconciling contradictions, challenging stale beliefs, verifying cascades — is the moat. The accumulated judgment about which beliefs survived challenge and why can't be regenerated from scratch. Automating detection and queuing for review is possible; automating the decisions is not.

## Revised Roadmap

1. **Editing workflow + RBAC** — UI controls for challenge/retract/reconcile, role-based access, project and tag scoping
2. **Operational deployment** — cloud VM/container with example reasons.db
3. **Automated KB building/updating** — scheduled imports, stale detection, auto-derive, contradiction queue

## Parallelization Opportunity

LLM calls from providers cost the same regardless of parallelism (per-token pricing). Serial vs parallel only affects wall clock time. Key opportunities:

- `meta-expert derive` — partition by namespace, derive code/project/product in parallel
- `ask_expert` in meta-chat — fan out to all relevant experts simultaneously
- `check-stale` + reconcile — hash checks are instant, re-analysis LLM calls can run concurrently
- Contradiction reconciliation — nogoods with non-overlapping node sets can be resolved in parallel
