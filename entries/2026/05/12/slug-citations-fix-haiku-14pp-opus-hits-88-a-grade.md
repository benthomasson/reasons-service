# Slug Citations Fix — Haiku +14pp, Opus Hits 88% A-Grade

**Date:** 2026-05-12
**Time:** 14:20

## Summary

Keeping the LLM's original `[belief-id]` citations instead of converting them to numbered `[1]` references improved eval scores across all models, with Haiku getting the biggest lift: 50% → 64% A-grade (+14pp). Opus reached 88% A-grade, the highest score recorded.

## The Change

Three commits on `keep-slug-citations` branch, merged to main:

1. **Remove numbered citation conversion.** `_build_sources_section` was assigning `[1]`, `[2]`, etc. and `_replace_inline_citations` was rewriting the LLM's `[belief-id]` refs to those numbers. Removed both — the LLM's original slugs pass through unchanged.
2. **Log stripped citations.** Added logging to `_strip_hallucinated_refs` to diagnose false positives. Result: zero false positives — everything stripped was genuinely hallucinated.
3. **Chat UI scroll links.** Updated `linkCitations` to work with slug-based refs instead of numbered ones. Collects slugs from the Sources/Beliefs footnotes and turns matching inline `[slug]` refs into clickable scroll links, scoped per message via `ref-{msgId}-{slug}`.

## Results (50 questions, seed 42)

### Before/After Citation Fix

| Model | v1 A% | v2 A% | Delta | v1 Attr | v2 Attr | Delta |
|-------|-------|-------|-------|---------|---------|-------|
| Opus | 86% | 88% | +2pp | 4.30 | 4.58 | +0.28 |
| Sonnet | 70% | 72% | +2pp | 3.96 | 3.84 | -0.12 |
| Haiku | 50% | 64% | +14pp | 3.46 | 4.00 | +0.54 |

### Full Dimensions (v2)

| Dimension | Opus | Sonnet | Haiku |
|-----------|------|--------|-------|
| Honesty | 4.90 | 4.76 | 4.70 |
| Relevance | 4.80 | 4.60 | 4.38 |
| Attribution | 4.58 | 3.84 | 4.00 |
| Accuracy | 4.58 | 4.36 | 4.42 |
| Completeness | 4.52 | 4.10 | 3.76 |

## Why Haiku Got the Biggest Lift

Haiku was the worst at maintaining citation format — it frequently used numbered refs `[5]` or dropped citations entirely. When the post-processing converted valid `[belief-id]` refs to `[1]`, those numbered refs became indistinguishable from hallucinated ones. By keeping the original slugs:

- The judge can verify each citation is a real belief ID
- Self-documenting refs like `[rh-sellers-cannot-sell-watsonx-directly]` are clearly intentional citations, not hallucinations
- The stripper only removes refs that don't match any retrieved belief/source

## Key Finding: No False Positives in Citation Stripping

The logging showed zero stripped citations that were actually valid. Every stripped ref was genuinely hallucinated. This means the "missing inline citations" problem (19 answers for Haiku, 15 for Sonnet) is purely the LLM not writing citations, not us incorrectly removing them. The next improvement is prompt engineering to demand inline citations on every factual claim.

## Remaining Attribution Issues (by frequency)

| Cause | Opus | Sonnet | Haiku |
|-------|------|--------|-------|
| Missing inline citations | 2 | 15 | 19 |
| Mixed/inconsistent format | 2 | 6 | 5 |
| Irrelevant sources cited | 1 | 3 | 10 |

## Cost and Speed Per Query

| Model | A-Grade | Cost/Query | Speed |
|-------|---------|------------|-------|
| Opus | 88% | ~$0.36 | ~6s |
| Sonnet | 72% | ~$0.07 | ~6s |
| Haiku | 64% | ~$0.02 | ~2s |
| Gemma3 27B | untested | $0.00 | ~12s |
