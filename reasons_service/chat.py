"""Chat API — SSE endpoint with OpenAI tool-calling agent loop."""

import asyncio
import json
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.auth import security, verify_auth, _resolve_member_visible_tags
from reasons_service.ratelimit import check_rate_limit
from reasons_service.config import settings
from reasons_service.db.connection import get_session
from reasons_service.db.models import Domain, DomainMember
from reasons_service.rbac import Role, UserInfo
from reasons_service.rms import api as rms_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_beliefs",
            "description": "Search for beliefs in the domain knowledge base. Use short keywords, not full sentences. Try single words first. If no results, try synonyms or related terms.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query — use 1-3 keywords"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_belief",
            "description": "Get full details of a specific belief by its ID, including its text, truth value, and support structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "belief_id": {"type": "string", "description": "The belief ID to look up"},
                },
                "required": ["belief_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_belief",
            "description": "Show the full justification chain for a belief — what supports it and what it supports. Use this to trace reasoning chains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "belief_id": {"type": "string", "description": "The belief ID to explain"},
                },
                "required": ["belief_id"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are a knowledgeable assistant with access to a structured domain knowledge base.
The knowledge base contains beliefs — justified propositions with dependency chains.
Each belief has an ID, text, truth value (IN = believed, OUT = not believed), and may have justifications linking it to other beliefs.

When answering questions:
1. Search the knowledge base first using short keywords (1-3 words)
2. If you find relevant beliefs, use show_belief and explain_belief to get details
3. Ground your answers in the beliefs you find — cite belief IDs when relevant
4. If the knowledge base doesn't have relevant information, say so clearly
5. Be concise and direct

Do not make up belief IDs or claim beliefs exist without searching first."""


class ChatRequest(BaseModel):
    message: str
    domain_id: str
    history: list[dict] | None = None


def _execute_tool(tool_name: str, args: dict, domain_id: UUID, visible_to: list[str] | None) -> str:
    try:
        if tool_name == "search_beliefs":
            result = rms_api.search(domain_id, args["query"], limit=20, visible_to=visible_to)
            results = result.get("results", [])
            if not results:
                return json.dumps({"results": [], "message": "No beliefs found. Try different keywords."})
            return json.dumps({"results": [
                {"id": r["id"], "text": r["text"], "truth_value": r.get("truth_value", "IN")}
                for r in results[:20]
            ]})
        elif tool_name == "show_belief":
            result = rms_api.show_node(domain_id, args["belief_id"], visible_to=visible_to)
            return json.dumps(result)
        elif tool_name == "explain_belief":
            result = rms_api.explain_node(domain_id, args["belief_id"], visible_to=visible_to)
            return json.dumps(result)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        logger.exception("Tool %s failed: %s", tool_name, e)
        return json.dumps({"error": f"Tool '{tool_name}' failed: {type(e).__name__}"})


async def _chat_stream(req: ChatRequest, user: UserInfo):
    try:
        from openai import OpenAI
    except ImportError:
        yield f"data: {json.dumps({'type': 'error', 'content': 'OpenAI package not installed. Install with: pip install reasons-service[openai]'})}\n\n"
        return

    if not settings.openai_api_key:
        yield f"data: {json.dumps({'type': 'error', 'content': 'OPENAI_API_KEY not set'})}\n\n"
        return

    client = OpenAI(api_key=settings.openai_api_key)
    domain_id = UUID(req.domain_id)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if req.history:
        for h in req.history[-10:]:
            role = h.get("role", "user")
            if role not in ("user", "assistant"):
                continue
            messages.append({"role": role, "content": h.get("content", "")})
    messages.append({"role": "user", "content": req.message})

    yield f"data: {json.dumps({'type': 'status', 'content': 'Thinking...'})}\n\n"

    for turn in range(10):
        try:
            response = await asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model=settings.openai_model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                )
            )
        except Exception as e:
            logger.exception("LLM API error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'content': 'LLM request failed. Check server logs for details.'})}\n\n"
            return

        choice = response.choices[0]
        msg = choice.message

        if msg.tool_calls:
            messages.append(msg.model_dump())
            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                yield f"data: {json.dumps({'type': 'tool_call', 'name': fn_name, 'args': fn_args})}\n\n"

                try:
                    result = await asyncio.to_thread(
                        _execute_tool, fn_name, fn_args, domain_id, user.visible_tags
                    )
                except Exception as e:
                    logger.exception("Tool execution thread failed: %s", e)
                    result = json.dumps({"error": f"Tool failed: {type(e).__name__}"})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        content = msg.content or ""
        words = content.split()
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'error', 'content': 'Max tool turns reached'})}\n\n"


async def _resolve_chat_user(domain_id: UUID, user: UserInfo | None, session: AsyncSession) -> UserInfo:
    """Verify domain access and resolve domain-scoped tags.

    If user is None (unauthenticated), only public domains are allowed.
    """
    result = await session.execute(
        select(Domain.public, Domain.members_only).where(Domain.id == domain_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Domain not found")

    if user is None:
        if row.public:
            return UserInfo(identity="public", role=Role.READER)
        raise HTTPException(status_code=401, detail="Not authenticated")

    if user.role == Role.ADMIN or user.identity in ("api", "dev"):
        return user

    member_result = await session.execute(
        select(DomainMember).where(
            DomainMember.domain_id == domain_id,
            DomainMember.user_email == user.identity,
        )
    )
    member = member_result.scalar_one_or_none()
    if member:
        return UserInfo(
            identity=user.identity,
            role=member.role,
            display_name=user.display_name,
            visible_tags=_resolve_member_visible_tags(member),
            domain_id=str(domain_id),
        )
    if row.members_only and not row.public:
        raise HTTPException(status_code=403, detail="Not a member of this domain")
    return user


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
):
    user = None
    try:
        user = await verify_auth(request, credentials, session)
    except HTTPException as e:
        if e.status_code != 401:
            raise
    await check_rate_limit(request, "chat")
    domain_id = UUID(req.domain_id)
    effective_user = await _resolve_chat_user(domain_id, user, session)
    return StreamingResponse(
        _chat_stream(req, effective_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
