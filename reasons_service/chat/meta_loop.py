"""Meta-expert SSE streaming loop.

Mirrors loop.py but uses the meta-agent instead of project-scoped agents.
Same SSE protocol: token, tool_call, tool_result, done.

After the main answer, a reflection step invokes the agent again on the same
thread to record beliefs about the experts' capabilities via rms_add.
"""

import json
import logging
from collections.abc import AsyncGenerator

from reasons_service.chat.loop import _extract_text, _langfuse_config
from reasons_service.chat.meta_agent import get_meta_agent
from reasons_service.config import settings

logger = logging.getLogger(__name__)

REFLECTION_PROMPT = (
    "Reflect on the conversation above. For each expert you consulted, "
    "record what you learned about that expert's knowledge using rms_add. "
    "Use descriptive node IDs like 'rhel-expert-knows-firewalld-defaults'. "
    "First use rms_search to check if you already have a belief about this topic — if so, skip it. "
    "Do NOT produce any text output — only call rms_add or rms_search tools. "
    "If you learned nothing new, do nothing.\n\n"
    "CRITICAL RULES:\n"
    "1. Only record POSITIVE knowledge — what an expert demonstrably knows.\n"
    "2. Only record knowledge that was CITED — the expert must have referenced specific "
    "belief IDs, entry IDs, or source documents in its answer. "
    "If the expert said 'I don't have specific documentation' or gave an answer from "
    "general knowledge without citations, do NOT record it. "
    "Uncited answers are from the LLM's training data, not the expert's knowledge base.\n"
    "3. NEVER record negative or transient states:\n"
    "   - NOT 'expert-is-unavailable' (transient error)\n"
    "   - NOT 'expert-lacks-X' (absence of evidence is not evidence of absence)\n"
    "   - NOT anything about errors, timeouts, or connection failures\n"
    "4. Only record: '<expert>-knows-<topic>' when the expert cited specific sources."
)


async def meta_chat_stream(
    model: str,
    message: str,
    thread_id: str,
) -> AsyncGenerator[str, None]:
    """Stream a meta-expert chat response via SSE."""
    agent = await get_meta_agent(model)
    config = {"configurable": {"thread_id": f"meta:{thread_id}"}}
    config.update(_langfuse_config())

    inputs = {"messages": [{"role": "user", "content": message}]}
    buffered_tokens: list[str] = []
    # Track whether we're in a tool-calling phase (suppress token streaming
    # until all tool results come back and the agent produces its final synthesis)
    awaiting_tools = False

    async for mode, data in agent.astream(
        inputs, config, stream_mode=["messages", "updates"]
    ):
        if mode == "messages":
            chunk, metadata = data
            # Only stream tokens from the agent node, and only when we're NOT
            # waiting for tool results (i.e., this is the final synthesis pass)
            if metadata.get("langgraph_node") == "agent" and not awaiting_tools:
                text = _extract_text(chunk.content) if chunk.content else ""
                if text:
                    buffered_tokens.append(text)

        elif mode == "updates":
            if "agent" in data:
                msg = data["agent"]["messages"][-1]
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    # Agent is calling tools — suppress streaming until results arrive
                    awaiting_tools = True
                    buffered_tokens.clear()
                    for tc in msg.tool_calls:
                        yield (
                            f"event: tool_call\n"
                            f"data: {json.dumps({'name': tc['name'], 'args': tc['args']})}\n\n"
                        )
                else:
                    # Agent produced a final text response (no tool calls) — stream it
                    awaiting_tools = False
                    for text in buffered_tokens:
                        yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
                    buffered_tokens.clear()

            elif "tools" in data:
                # Tool results arrived — stop suppressing, next agent pass is synthesis
                awaiting_tools = False
                for msg in data["tools"]["messages"]:
                    summary = str(msg.content)[:200]
                    name = getattr(msg, "name", "tool")
                    yield (
                        f"event: tool_result\n"
                        f"data: {json.dumps({'name': name, 'summary': summary})}\n\n"
                    )

    # Send done before reflection so the UI renders the answer immediately
    yield "event: done\ndata: {}\n\n"

    # --- Reflection step: record beliefs about expert capabilities ---
    try:
        reflection_input = {"messages": [{"role": "user", "content": REFLECTION_PROMPT}]}
        async for mode, data in agent.astream(
            reflection_input, config, stream_mode=["messages", "updates"]
        ):
            if mode == "updates":
                if "agent" in data:
                    msg = data["agent"]["messages"][-1]
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            if tc["name"].startswith("rms_"):
                                yield (
                                    f"event: reflection\n"
                                    f"data: {json.dumps({'name': tc['name'], 'args': tc['args']})}\n\n"
                                )
    except Exception:
        logger.exception("Meta-expert reflection step failed")
