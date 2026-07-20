# Langfuse Cost Data — Full Eval Costs Across Four Model Tiers

**Date:** 2026-05-12
**Time:** 15:12

## Summary

First complete cost picture from langfuse for expert-service evals. Four model tiers from $0 to $21.61 for a 50-question eval, with 15-60x token reduction vs agents-python's 300k tokens/query.

## Eval Cost Data (from langfuse, 50 questions each)

| Model | Tokens | Cost | A-Grade | Cost/Query | Cost per A |
|-------|--------|------|---------|------------|------------|
| Opus 4.6 | 933k | $21.61 | 88% (44) | $0.43 | $0.49 |
| Sonnet 4.6 | 849k | $4.20 | 72% (36) | $0.08 | $0.12 |
| Haiku 4.5 | 723k | $1.01 | 64% (32) | $0.02 | $0.03 |
| Gemma3 27B | 501k | $0.00 | 44% (22) | $0.00 | $0.00 |

Gemma3 total includes both dual (30% A) and single-pass (44% A) eval runs.

## Token Usage Per Query

| Model | Mode | Tokens/Query | LLM Calls |
|-------|------|-------------|-----------|
| Opus | dual | ~18k | 3 (TMS + RAG + merge) |
| Sonnet | dual | ~17k | 3-5 (extra iterative rounds) |
| Haiku | dual | ~14k | 3 |
| Gemma3 | single | ~5k | 1 |
| Gemma3 | dual | ~6k | 3 |

## Comparison to agents-python

agents-python uses ~300k tokens per query because the LLM drives the entire retrieval loop with tool calls. expert-service does retrieval in code (FTS + IDF re-ranking), then hands pre-ranked context to the LLM for synthesis only.

| System | Tokens/Query | Reduction |
|--------|-------------|-----------|
| agents-python | ~300k | baseline |
| expert-service (Opus dual) | ~18k | 17x |
| expert-service (Gemma3 single) | ~5k | 60x |

## Value Analysis

**Sonnet is the value pick.** It delivers 82% of Opus's quality (72% vs 88% A-grade) at 19% of the cost ($4.20 vs $21.61). For a production Q&A service handling thousands of queries, the 5x cost difference adds up fast.

**Haiku is the volume tier.** 73% of Opus quality at 5% of the cost, and 2.5x faster (119s vs 296s for 50 questions). At $0.02/query, cost is negligible even at scale.

**Gemma3 is the air-gapped tier.** Zero marginal cost, runs on local hardware, no data leaves the network. 44% A-grade with single-pass is acceptable for internal use where speed and privacy matter more than polish.

**Cost per correct answer** is the metric that matters for production: Opus $0.49, Sonnet $0.12, Haiku $0.03, Gemma3 $0.00. A service that routes easy questions to Haiku and hard ones to Opus could average under $0.10 per correct answer.
