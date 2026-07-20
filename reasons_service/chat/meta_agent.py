"""Meta-expert agent — routes questions across all project experts.

The meta-expert is a regular project ("meta-expert") with standard tools
(search, RMS, entries) PLUS meta tools (list_experts, ask_expert).
It uses its own RMS to learn about the other expert agents over time.
"""

import logging
from uuid import UUID

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent
from sqlalchemy import select

from reasons_service.chat.agent import get_checkpointer
from reasons_service.chat.meta_tools import make_meta_tools
from reasons_service.chat.tools import make_tools
from reasons_service.config import settings
from reasons_service.db.connection import get_sync_session
from reasons_service.db.models import Project
from reasons_service.llm.provider import get_chat_model

logger = logging.getLogger(__name__)

# Cached meta-agents keyed by model
_meta_agents: dict[str, object] = {}

META_PROJECT_NAME = "meta-expert"
META_PROJECT_DOMAIN = "Expert routing and cross-domain knowledge synthesis"


def _ensure_meta_project() -> UUID:
    """Find or create the meta-expert project. Returns its UUID."""
    with get_sync_session() as session:
        row = session.execute(
            select(Project.id).where(Project.name == META_PROJECT_NAME)
        ).scalar_one_or_none()

        if row is not None:
            return row

        project = Project(name=META_PROJECT_NAME, domain=META_PROJECT_DOMAIN)
        session.add(project)
        session.commit()
        session.refresh(project)
        logger.info("Created meta-expert project: %s", project.id)
        return project.id


def _load_experts_map(exclude_id: UUID) -> dict[str, dict]:
    """Load all projects except the meta-expert as an experts map."""
    with get_sync_session() as session:
        rows = session.execute(
            select(Project.id, Project.name, Project.domain)
            .where(Project.id != exclude_id)
            .order_by(Project.name)
        ).all()

    return {
        r.name: {"project_id": r.id, "domain": r.domain}
        for r in rows
    }


def _build_system_prompt(experts_map: dict[str, dict]) -> str:
    expert_list = "\n".join(
        f"- **{name}**: {info['domain']}"
        for name, info in experts_map.items()
    )
    return f"""You are a meta-expert that coordinates across multiple domain experts.
You do NOT have direct domain knowledge — you consult domain experts using the ask_expert tool.
You DO have your own RMS (Reason Maintenance System) to record what you learn about each expert.

Available experts:
{expert_list}

Routing rules:
1. Use list_experts to see current expert availability.
2. Use ask_expert to consult the appropriate expert for each question.
3. If a question spans multiple domains, consult each relevant expert separately.
4. If experts give contradictory information, note the contradiction explicitly.
5. If no expert is relevant, say so directly.

Answer rules:
- Synthesize the expert's answer in your own words. Do NOT repeat the expert's response verbatim — rephrase and summarize.
- Mention which expert you consulted (e.g., "The RHEL expert confirms that...").
- Preserve belief ID and entry ID citations from the expert's answer inline next to each claim, e.g. "The migration requires downtime (belief: rhel9-migration-requires-downtime)." Do NOT move citations to the end of your answer — that causes hallucinated IDs.
- Be concise and direct. One clear answer, not a duplicate.
- Do NOT narrate tool usage. No "Let me search..." — just call tools and answer.

RMS usage:
- Use your RMS tools to record what you learn about each expert's capabilities.
- Example: rms_add to record "rhel-expert knows about firewalld defaults"
- Use rms_nogood if two experts contradict each other.
- Search your own beliefs before consulting — you may already know which expert to ask."""


def invalidate_meta_cache():
    """Clear cached meta-agents. Call when projects are created/deleted."""
    _meta_agents.clear()
    logger.info("Meta-agent cache invalidated")


async def get_meta_agent(model: str):
    """Get or create the meta-expert agent for the given model."""
    model = model or settings.default_model
    if model not in _meta_agents:
        meta_project_id = _ensure_meta_project()
        experts_map = _load_experts_map(exclude_id=meta_project_id)

        # Standard tools scoped to the meta-expert's own project
        standard_tools = make_tools(meta_project_id)
        # Meta-specific tools for cross-expert routing
        meta_tools = make_meta_tools(experts_map, model)

        all_tools = standard_tools + meta_tools
        llm = get_chat_model(model)
        checkpointer = await get_checkpointer()
        prompt_text = _build_system_prompt(experts_map)

        _meta_agents[model] = create_react_agent(
            model=llm,
            tools=all_tools,
            prompt=SystemMessage(
                content=prompt_text,
                additional_kwargs={"cache_control": {"type": "ephemeral"}},
            ),
            checkpointer=checkpointer,
        )
        logger.info(
            "Created meta-agent for model=%s with %d experts, %d tools",
            model, len(experts_map), len(all_tools),
        )
    return _meta_agents[model]
