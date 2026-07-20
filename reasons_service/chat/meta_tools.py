"""Meta-expert tools — list_experts and ask_expert for cross-domain routing."""

import json
import logging
from uuid import UUID, uuid4

from langchain_core.tools import tool

from reasons_service.chat.loop import _extract_text

logger = logging.getLogger(__name__)


def make_meta_tools(experts_map: dict[str, dict], model: str) -> list:
    """Create meta-expert tools.

    Args:
        experts_map: {name: {"project_id": UUID, "domain": str}}
        model: LLM model name to use for sub-agent invocations.
    """

    @tool
    def list_experts() -> str:
        """List all available domain experts with their areas of expertise."""
        return json.dumps(
            [
                {"name": name, "domain": info["domain"]}
                for name, info in experts_map.items()
            ],
            indent=2,
        )

    @tool
    async def ask_expert(expert_name: str, question: str) -> str:
        """Ask a domain expert a question. The expert will search its knowledge
        base (entries, beliefs, sources) and return an answer with citations.

        Args:
            expert_name: Name of the expert to consult (use list_experts to see available experts)
            question: The question to ask the expert
        """
        expert = experts_map.get(expert_name)
        if not expert:
            available = ", ".join(experts_map.keys())
            return f"Unknown expert '{expert_name}'. Available experts: {available}"

        # Import here to avoid circular import (agent.py -> tools.py -> meta_tools.py)
        from reasons_service.chat.agent import get_agent

        project_id = expert["project_id"]
        try:
            agent = await get_agent(project_id, model)
            ephemeral_thread = f"{project_id}:{uuid4()}"
            config = {"configurable": {"thread_id": ephemeral_thread}}

            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": question}]},
                config,
            )

            ai_msg = result["messages"][-1]
            answer_text = _extract_text(ai_msg.content)

            return json.dumps(
                {
                    "expert": expert_name,
                    "domain": expert["domain"],
                    "answer": answer_text,
                }
            )
        except Exception as e:
            logger.exception("Error consulting expert %s", expert_name)
            return json.dumps(
                {
                    "expert": expert_name,
                    "error": str(e),
                }
            )

    return [list_experts, ask_expert]
