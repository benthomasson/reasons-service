# Langfuse Token Tracking — Expert-Service Cost Per Query

**Date:** 2026-05-12
**Time:** 10:21

## Summary

Added langfuse integration to expert-service's dual-path (/ask) endpoint to track token usage and cost per query. First concrete measurements of what each model costs per query.

## Results

Three models tested on the same expert-service instance (localhost), same knowledge base (openshift-expert, ~1500 beliefs), same dual-path retrieval pipeline (TMS iterative + FTS RAG + merge).

| Model | Total Tokens | Cost/Query | Notes |
|-------|-------------|------------|-------|
| Claude Opus 4.6 | ~10k | ~$0.36 | 3 LLM calls (TMS, RAG, merge) |
| Claude Sonnet 4.6 | ~12k | ~$0.07 | 5 LLM calls (extra iterative rounds) |
| Gemma3 27B (Ollama) | ~5.4k | $0.00 | Self-hosted on threadripper2, 3 calls |

## Key Findings

**Expert-service uses 10-12k tokens per query, not 300k.** The agents-python pipeline uses ~300k tokens because the LLM drives the entire retrieval loop with tool calls. Expert-service's dual-path architecture does retrieval in code (FTS + IDF re-ranking), then hands pre-ranked context to the LLM for synthesis only. The LLM sees ~3k tokens of context per call, not the entire knowledge base.

**Opus is 5x more expensive than Sonnet for roughly equivalent answers.** Both produce good answers from the same retrieval results. Sonnet sometimes does more iterative search rounds (5 calls vs 3), but each call is cheaper. For a Q&A service, Sonnet is the clear default.

**Gemma3 is free and competitive.** Running on a local Threadripper with GPU, Gemma3 27B produces usable answers at zero marginal cost. Quality is slightly lower (more hallucinated references, which post-processing strips), but for internal use the price/quality tradeoff is excellent.

**The 3-call pattern is consistent.** The dual-path always does: (1) TMS belief synthesis, (2) FTS source RAG, (3) merge. Sometimes TMS does extra iterative rounds if the LLM requests more searches, but the base cost is 3 LLM calls.

## Architecture That Makes This Possible

The cost reduction vs agents-python comes from moving retrieval out of the LLM loop:

```
agents-python: LLM drives search → 10-20 tool calls → 300k tokens
expert-service: Code does FTS+IDF → 3 synthesis calls → 10k tokens
```

All the expensive reasoning (source analysis, belief derivation, contradiction resolution) happens once at build time. Query time is just lookup + synthesis.

## Implementation

Added `_langfuse_config()` helper to `chat/loop.py` that returns a LangChain callbacks config when `LANGFUSE_SECRET_KEY` is set. Wired into all 6 `llm.ainvoke()` / `llm.astream()` calls in the dual-path functions. Zero overhead when langfuse is not configured.

Langfuse runs locally via docker-compose from agents-python's infra. Model costs configured via API for Opus ($15/$75 per M), Sonnet ($3/$15 per M), Haiku ($1/$5 per M), Gemini 2.5 Pro ($1.25/$10 per M), and Gemma3 ($0/$0).
