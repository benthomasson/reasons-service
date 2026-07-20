# Expert Service: LangGraph ReAct Chatbot Architecture

**Date:** 2026-03-06
**Time:** 14:27

## Overview

The expert-service chatbot is a LangGraph ReAct agent that answers domain questions by searching a PostgreSQL knowledge base. It supports Gemini 2.5 Pro and Claude Sonnet via Vertex AI, streams responses over SSE, and persists conversations with PostgreSQL checkpointing.

## Request Flow

1. Client sends \`POST /api/projects/{id}/chat\` with \`{message, model, thread_id}\`
2. FastAPI returns a \`StreamingResponse\` (SSE) via \`chat_stream()\`
3. \`agent.astream()\` runs the ReAct loop: reason → tool call → observe → reason → answer
4. SSE events stream back: \`tool_call\`, \`token\`, \`tool_result\`, \`done\`

## Agent Construction

\`\`\`python
# agent.py:58-75
agent = create_react_agent(
    model=llm,              # Gemini or Claude via Vertex AI
    tools=tools,            # 7 tools scoped to project_id
    prompt=SystemMessage(content=SYSTEM_PROMPT),
    checkpointer=checkpointer,  # AsyncPostgresSaver
)
\`\`\`

Agents are cached per \`(project_id, model)\` tuple — created once, reused across requests.

## Tools (7 total, all scoped to project_id)

| Tool | Method |
|------|--------|
| \`search_knowledge\` | PostgreSQL FTS (full-text search with English stemming) |
| \`grep_content\` | Exact text search (case-insensitive ILIKE) |
| \`semantic_search\` | pgvector embeddings (bge-small-en-v1.5, threshold 0.3) |
| \`read_entry\` | Fetch full entry by ID |
| \`list_entries\` | Browse entries, filter by topic |
| \`list_beliefs\` | List claims by status (IN/OUT/STALE) |
| \`read_source\` | Fetch raw source documents (up to 8000 chars) |

Three search strategies (FTS, exact grep, vector similarity) give the agent different retrieval paths depending on the question type.

## SSE Streaming

The chat loop (\`loop.py:28-85\`) uses \`stream_mode=["messages", "updates"]\` to capture both token-level and node-level events:

- **\`tool_call\`** — emitted when agent decides to use a tool
- **\`token\`** — streamed text content (buffered during intermediate rounds)
- **\`tool_result\`** — first 200 chars of tool output
- **\`done\`** — signals stream completion

Tokens are buffered during intermediate reasoning rounds (when tools are being called). Only the final round's text gets streamed to the client.

## Conversation Persistence

- **Checkpointer**: \`AsyncPostgresSaver\` from \`langgraph.checkpoint.postgres.aio\`
- **Connection pool**: \`AsyncConnectionPool\` from \`psycopg_pool\` (autocommit mode)
- **Thread ID format**: \`"{project_id}:{thread_id}"\` — isolates conversations per project
- No explicit messages table — LangGraph's checkpointer handles all state serialization
- Each request loads prior message history from the checkpoint automatically

## LLM Configuration

Both models accessed via Vertex AI (\`llm/provider.py\`):

- **Gemini 2.5 Pro** (default) — \`ChatVertexAI\`, global location
- **Claude Sonnet 4.5** — \`ChatAnthropicVertex\`, us-east5 location

## System Prompt Design

The system prompt enforces a "search once, then answer" pattern:
- SEARCH ONCE, then answer (no duplicate searches)
- Pick ONE search tool per question
- No tool narration in responses

This controls tool call volume — without it, the agent tends to over-search.

## Key Design Decisions

1. **Per-project tool scoping**: Tools created with \`project_id\` injected via closure. The LLM never sees the UUID.
2. **Dual database engines**: Async engine (\`asyncpg\`) for FastAPI, sync engine (\`psycopg\`) for LangGraph tool execution.
3. **Agent caching**: \`(project_id, model)\` key prevents re-instantiation overhead.
4. **Lazy checkpointer init**: Pool and checkpointer created on first use, reused across requests.

## Key Files

- \`expert_service/chat/agent.py\` — Agent factory, checkpointer setup, system prompt
- \`expert_service/chat/loop.py\` — SSE streaming loop
- \`expert_service/chat/tools.py\` — 7 LangChain tools with DB queries
- \`expert_service/api/chat.py\` — FastAPI endpoint
- \`expert_service/llm/provider.py\` — Vertex AI model configuration

## Related

- [LangGraph React Agent Conversion](langgraph-react-agent-conversion.md)
- [Claude Code vs RAG Evaluation](claude-code-vs-rag-eval.md)
