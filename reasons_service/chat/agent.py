"""LangGraph react agent factory — creates and caches agents per (project, model)."""

import logging
from uuid import UUID

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from reasons_service.chat.tools import make_tools
from reasons_service.config import settings
from reasons_service.llm.provider import get_chat_model

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert assistant for a domain knowledge base.
You have tools to search and read entries, beliefs, and source documents.
You also have RMS (Reason Maintenance System) tools for formal belief tracking with justification chains.

Tool usage rules:
- SEARCH ONCE, then answer. Do not call search_knowledge or grep_content more than once per question.
- If search returns matching beliefs, cite them directly (belief ID + text) — do NOT call read_entry just to restate what a belief already says. Beliefs are authoritative.
- Only use read_entry when you need more detail from an entry beyond what the search snippet provides.
- NEVER call the same tool twice or call two search tools. Pick ONE: search_knowledge, grep_content, or semantic_search.
- search_knowledge: keyword/concept search (default). grep_content: exact strings (commands, filenames). semantic_search: meaning-based when keywords fail.
- Do NOT narrate tool usage. No "Let me search..." — just call tools and answer.

RMS tools:
- rms_status: see all beliefs with truth values (IN/OUT)
- rms_add: add a belief (premise or with dependencies via sl/unless)
- rms_retract/rms_assert: retract or assert a belief with automatic cascade
- rms_explain: trace why a belief is IN or OUT
- rms_show: full details including justifications and dependents
- rms_search: search beliefs by text or ID
- rms_trace: find all premises a belief rests on
- rms_challenge/rms_defend: dialectical argumentation
- rms_nogood: record contradictions with automatic backtracking resolution
- rms_compact: token-budgeted belief network summary
- rms_find_issues: find blocked beliefs (gated by active problems) and beliefs describing problems/risks
- rms_what_if: simulate retract/assert to see cascade impact without modifying the database

Answer rules:
- Cite belief IDs inline next to the claim they support, e.g. "The migration requires downtime (belief: rhel9-migration-requires-downtime)." Do NOT collect citations at the end of your answer — that causes hallucinated IDs.
- When information is partial, share what you found and note what's missing.
- Be concise and direct."""

# Cached agents keyed by (project_id, model)
_agents: dict[tuple, object] = {}

# Checkpointer (lazy-initialized)
_pool = None
_checkpointer = None


async def get_checkpointer():
    """Get or create the LangGraph checkpointer.

    PostgreSQL: AsyncPostgresSaver with connection pool.
    SQLite: MemorySaver (in-memory, ephemeral — chat history lost on restart).
    """
    global _pool, _checkpointer
    if _checkpointer is None:
        if settings.db_backend == "sqlite":
            from langgraph.checkpoint.memory import MemorySaver
            _checkpointer = MemorySaver()
            logger.info("MemorySaver checkpointer initialized (SQLite mode)")
        else:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool import AsyncConnectionPool
            conn_string = settings.database_url_sync.replace("postgresql+psycopg://", "postgresql://")
            _pool = AsyncConnectionPool(
                conn_string,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
            await _pool.open()
            _checkpointer = AsyncPostgresSaver(_pool)
            await _checkpointer.setup()
            logger.info("Async PostgreSQL checkpointer initialized")
    return _checkpointer


async def get_agent(project_id: UUID, model: str):
    """Get or create a LangGraph react agent for the given project and model."""
    key = (project_id, model)
    if key not in _agents:
        tools = make_tools(project_id)
        llm = get_chat_model(model)
        checkpointer = await get_checkpointer()
        _agents[key] = create_react_agent(
            model=llm,
            tools=tools,
            prompt=SystemMessage(
                content=SYSTEM_PROMPT,
                additional_kwargs={"cache_control": {"type": "ephemeral"}},
            ),
            checkpointer=checkpointer,
        )
        logger.info("Created agent for project=%s model=%s", project_id, model)
    return _agents[key]
