# Context Window Overflow — 211K Tokens Exceeds 200K Limit in Iterative TMS

**Date:** 2026-05-13
**Time:** 13:55

## Summary

Expert-service is hitting Anthropic's 200K token context limit during iterative TMS answering. A prompt with 211,845 tokens was sent, causing a 400 BadRequestError. The root cause is unbounded context accumulation across iterative search rounds.

## Error

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'prompt is too long: 211845 tokens > 200000 maximum'}}
```

## Root Cause

Source chunks have a context budget (`MAX_CONTEXT_CHARS = 30000`, ~7.5K tokens), but beliefs and tool history have **no budget**. The iterative TMS loop (`_tms_answer_iterative`) accumulates context across up to 3 rounds:

- **Round 1**: initial beliefs (up to 20, no char limit) + prompt template
- **Round 2**: new beliefs + round 1 tool history + prompt
- **Round 3**: new beliefs + rounds 1+2 tool history + prompt

Each round appends full search results and Snowflake query responses to `tool_history` without truncation. A single `query_data` Snowflake result can return an enormous table, and belief text has no per-item or total character cap.

## Asymmetry

| Context source | Budget | Truncation |
|----------------|--------|------------|
| Source chunks | 30,000 chars (~7.5K tokens) | Per-chunk (2000 chars) + total cap |
| Beliefs | None | Only count-limited (20 items) |
| Tool history | None | Full text from all prior rounds |
| Snowflake results | None | Raw query output |

## Fix (not yet implemented)

1. Add `MAX_BELIEF_CONTEXT_CHARS` budget to `_quick_belief_search`, matching the source chunk pattern
2. Truncate individual `tool_history` entries (e.g., 5000 chars each)
3. Cap total prompt size before sending to LLM — measure token count and trim oldest tool history first
4. The 502 error handler added earlier today ensures the user gets a clean error message instead of a 500 traceback

## Context

This surfaced during 4000-question eval stress testing against the Red Hat expert knowledge base, which has large Snowflake connector results and verbose beliefs. Smaller knowledge bases are unlikely to hit this limit.
