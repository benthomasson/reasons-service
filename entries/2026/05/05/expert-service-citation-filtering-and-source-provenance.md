# Expert Service Citation Filtering and Source Provenance

**Date:** 2026-05-05
**Time:** 10:48

## Summary

Expert-service now filters cited sources to only what the LLM actually referenced, replaces raw belief IDs with numbered references, and provides clickable "Why?" buttons that trigger full LLM-narrated explanations of any belief. Source URL backfill achieved 97.6% coverage on beliefs and 97% on FTS source documents.

## Architecture

The system has three retrieval paths that run in parallel:

1. **TMS Beliefs (Primary)** — 5,465 structured beliefs with justification chains, searched via PostgreSQL tsvector with IDF re-ranking
2. **FTS Source Chunks (Supporting)** — 108,788 document chunks from original source files, full-text searched and linked to Google Drive URLs
3. **Snowflake Connectors (Data)** — Live queries for current numbers, employee directory lookups, and temporal data

Each path produces `SourceRef` objects with a `cite_key` field. After the LLM generates its merged response, `_extract_cited_keys()` scans for `[belief-id]` and `[slug]` markers. Only sources the LLM actually cited appear in the output.

## Citation Flow

1. LLM receives beliefs as `[IN] engineering:belief-name — text` and cites them as `[engineering:belief-name]`
2. LLM receives FTS chunks as `### [1] dept/filename > section` and cites them as `[dept/filename]`
3. `_extract_cited_keys()` extracts all `[...]` markers from the merged response
4. `_build_sources_section()` filters to only cited sources, builds numbered list
5. `_replace_inline_citations()` replaces raw `[belief-id]` with `[N]` refs
6. Output splits into `## Sources` (with clickable URLs) and `## Beliefs` (with Why? buttons)

This mirrors agents-python's `_filter_referenced_citations` pattern but without needing a second LLM call — the filtering is deterministic regex over the response the LLM already produced.

## Source URL Backfill

Three normalization fixes were needed to match belief source paths to manifest entries:

| Fix | Before | After |
|-----|--------|-------|
| Scan all file types in manifests | 75.9% | 85.2% |
| Normalize belief slugs with filename_to_slug() | 85.2% | 89.9% |
| Compressed fallback (strip hyphens) | 89.9% | 97.6% |

The `sources` table (backing FTS chunks) was also backfilled: 604/619 sources (97%) now have clickable Google Drive URLs.

## Why? Explain Buttons

Derived beliefs (cross-domain conclusions without source documents) appear in a separate `## Beliefs` section. Each has a "Why?" button that sends `explain {belief-id}` as a chat message, triggering the full dual-path pipeline. The LLM produces a rich explanation with strategic context, related beliefs, and proper source citations — treating the TMS justification chain as input rather than output.

This validates a key architectural insight: raw TMS output (justification chains, truth values, antecedent lists) is machine-readable but not human-readable. The LLM is the presentation layer that Doyle's 1979 RMS was missing.

## Results

- Source citations went from 10 irrelevant dump to only what the LLM used
- Every source links back to the original Google Drive document (97%+ coverage)
- Belief explanations produce 500-1000 word contextualized analyses in ~15-30s
- The system functions as an internal search engine across all Red Hat knowledge with full provenance
