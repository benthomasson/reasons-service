# LangGraph React Agent Conversion

**Date:** 2026-03-06
**Time:** 09:14

## Overview

Converted the expert-service chat interface from a hand-rolled tool-calling loop to a LangGraph `create_react_agent` with PostgreSQL conversation persistence.

## What Changed

Three files modified, one new:

- **`chat/agent.py`** (new) — Agent factory that creates and caches react agents per (project_id, model). Uses `AsyncPostgresSaver` with `AsyncConnectionPool` for conversation checkpointing.
- **`chat/loop.py`** (rewritten) — Replaced manual tool-calling loop with `agent.astream(inputs, config, stream_mode=["messages", "updates"])`. Translates LangGraph streaming events into the existing SSE protocol (token, tool_call, tool_result, done).
- **`api/chat.py`** (simplified) — Removed in-memory `_conversations` dict, `SYSTEM_PROMPT`, and `SystemMessage`/`HumanMessage` imports. Now just passes message string + thread_id to `chat_stream()`.
- **`pyproject.toml`** — Added `psycopg-pool>=3.1` dependency.

## What Was Removed

- `_conversations` in-memory dict — replaced by PostgreSQL checkpointing
- Manual tool-calling loop with `MAX_TOOL_ROUNDS` — replaced by `create_react_agent` (default 25 steps)
- Gemini context cache management — can be added back via `pre_model_hook` if needed

## Key Technical Decisions

**Async checkpointer required**: The sync `PostgresSaver` raises `NotImplementedError` on `aget_tuple` when used with `agent.astream()`. Switched to `AsyncPostgresSaver` from `langgraph.checkpoint.postgres.aio` with `AsyncConnectionPool` from `psycopg_pool`.

**`create_react_agent` not `create_agent`**: The newer `create_agent` from `langchain` package is not installed. `create_react_agent` from `langgraph.prebuilt` is what's available in langgraph v1.0.10. The deprecation is forward-looking.

**Streaming translation pattern**: Buffer token chunks from "messages" mode, check "updates" from "agent" node — if tool_calls present, discard buffer and emit tool indicators; if no tool_calls, flush buffer as tokens. This preserves the existing UX where intermediate narration is suppressed and only the final response streams.

**Agent caching**: Agents are cached per `(project_id, model)` since tools are project-scoped via closures. The checkpointer is shared across all agents.

## Benefits

- Conversations persist across Docker restarts via PostgreSQL checkpointing
- LangGraph manages tool execution, retries, and state — less custom code
- Same SSE protocol means no frontend changes needed
- Net code change: 125 insertions, 124 deletions (roughly neutral)

## Verification

Tested with two sequential requests on the same thread_id. The follow-up message ("Tell me more about rulebooks") correctly referenced context from the prior EDA question, confirming conversation persistence works.
