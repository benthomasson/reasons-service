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
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.auth import security, verify_auth, _resolve_member_visible_tags
from reasons_service.ratelimit import check_rate_limit
from reasons_service.config import settings
from reasons_service.db.connection import get_session
from reasons_service.db.models import ChatConversation, ChatMessage as ChatMessageModel, Domain, DomainMember, TenantMember
from reasons_service.rbac import Role, UserInfo
from reasons_service.db.search import quick_belief_search, search_source_chunks
from reasons_service.rms import api as rms_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_beliefs",
            "description": "Search beliefs and source documents with IDF-ranked results. Returns pre-ranked context from both the belief network and source document chunks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The question or search terms"},
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
    {
        "type": "function",
        "function": {
            "name": "list_topics",
            "description": "List the main topics in the domain knowledge base, ranked by frequency. Use this to understand what the domain covers before searching.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

SYSTEM_PROMPT = """You are a knowledgeable assistant with access to a structured domain knowledge base.
The knowledge base contains beliefs (justified propositions with dependency chains) and source documents.
Each belief has an ID, text, truth value (IN = believed, OUT = not believed), and may have justifications linking it to other beliefs.

When answering questions:
1. Search the knowledge base first — the search tool retrieves both beliefs and source document context
2. Use show_belief and explain_belief to drill into specific beliefs
3. Ground your answers in what you find — cite belief IDs and source material when relevant
4. If the knowledge base doesn't have relevant information, say so clearly
5. Be concise and direct

Formatting (the response renders markdown):
- Start with a 1-2 sentence summary answering the question
- Use a bullet list for supporting evidence, one belief per bullet: `belief-id` — description (IN/OUT)
- Group related beliefs under **bold headings** when there are more than 5
- Never write paragraphs longer than 2 sentences — break into bullets or add a heading
- End with a brief "Sources" section listing source documents if available

Do not make up belief IDs or claim beliefs exist without searching first."""


class ChatRequest(BaseModel):
    message: str
    domain_id: str
    conversation_id: str | None = None
    history: list[dict] | None = None


def _execute_tool(tool_name: str, args: dict, domain_id: UUID, visible_to: list[str] | None) -> str:
    try:
        if tool_name == "search_beliefs":
            belief_ctx, belief_sources = quick_belief_search(domain_id, args["query"], 20)
            chunk_ctx, chunk_sources = search_source_chunks(domain_id, args["query"], 10)
            if not belief_ctx and not chunk_ctx:
                return json.dumps({"results": [], "message": "No results found. Try different keywords."})
            result = {}
            if belief_ctx:
                result["belief_context"] = belief_ctx
            if chunk_ctx:
                result["source_context"] = chunk_ctx
            return json.dumps(result)
        elif tool_name == "show_belief":
            result = rms_api.show_node(domain_id, args["belief_id"], visible_to=visible_to)
            return json.dumps(result)
        elif tool_name == "explain_belief":
            result = rms_api.explain_node(domain_id, args["belief_id"], visible_to=visible_to)
            return json.dumps(result)
        elif tool_name == "list_topics":
            result = rms_api.topics(domain_id, limit=20)
            return json.dumps(result)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        logger.exception("Tool %s failed: %s", tool_name, e)
        return json.dumps({"error": f"Tool '{tool_name}' failed: {type(e).__name__}"})


async def _save_messages(
    conversation_id: UUID | None,
    domain_id: UUID,
    user_email: str,
    user_message: str,
    assistant_message: str,
) -> UUID:
    """Persist user and assistant messages. Creates conversation if needed."""
    from reasons_service.db.connection import async_session
    async with async_session() as session:
        if not conversation_id:
            conv = ChatConversation(
                domain_id=domain_id,
                user_email=user_email,
                title=user_message[:100].strip(),
            )
            session.add(conv)
            await session.flush()
            conversation_id = conv.id
        else:
            await session.execute(
                update(ChatConversation)
                .where(ChatConversation.id == conversation_id)
                .values(updated_at=func.now())
            )
            has_title = (await session.execute(
                select(ChatConversation.title).where(ChatConversation.id == conversation_id)
            )).scalar()
            if not has_title:
                await session.execute(
                    update(ChatConversation)
                    .where(ChatConversation.id == conversation_id)
                    .values(title=user_message[:100].strip())
                )
        session.add(ChatMessageModel(conversation_id=conversation_id, role="user", content=user_message))
        session.add(ChatMessageModel(conversation_id=conversation_id, role="assistant", content=assistant_message))
        await session.commit()
    return conversation_id


async def _chat_stream(req: ChatRequest, user: UserInfo, conversation_id: UUID | None = None):
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

    t0 = time.monotonic()
    total_prompt_tokens = 0
    total_completion_tokens = 0
    tool_call_count = 0

    for turn in range(10):
        try:
            response = await asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model=settings.openai_model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    reasoning_effort="none",
                )
            )
        except Exception as e:
            logger.exception("LLM API error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'content': 'LLM request failed. Check server logs for details.'})}\n\n"
            return

        if response.usage:
            total_prompt_tokens += response.usage.prompt_tokens
            total_completion_tokens += response.usage.completion_tokens

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

                tool_call_count += 1
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
        lines = content.split("\n")
        for i, line in enumerate(lines):
            token = line + ("\n" if i < len(lines) - 1 else "")
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        if content and user.identity != "public":
            try:
                conversation_id = await _save_messages(
                    conversation_id, domain_id, user.identity, req.message, content,
                )
            except Exception:
                logger.exception("Failed to save chat messages")

        duration = time.monotonic() - t0
        stats = f"{duration:.1f}s · {total_prompt_tokens + total_completion_tokens} tokens ({total_prompt_tokens} in, {total_completion_tokens} out) · {tool_call_count} tool calls"
        yield f"data: {json.dumps({'type': 'stats', 'content': stats})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': str(conversation_id) if conversation_id else None})}\n\n"
        return

    duration = time.monotonic() - t0
    stats = f"{duration:.1f}s · {total_prompt_tokens + total_completion_tokens} tokens ({total_prompt_tokens} in, {total_completion_tokens} out) · {tool_call_count} tool calls"
    yield f"data: {json.dumps({'type': 'stats', 'content': stats})}\n\n"
    yield f"data: {json.dumps({'type': 'error', 'content': 'Max tool turns reached'})}\n\n"


async def _resolve_chat_user(domain_id: UUID, user: UserInfo | None, session: AsyncSession) -> UserInfo:
    """Verify domain access and resolve domain-scoped tags.

    If user is None (unauthenticated), only public domains are allowed.
    """
    result = await session.execute(
        select(Domain.public, Domain.members_only, Domain.tenant_id).where(Domain.id == domain_id)
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
            tenant_id=user.tenant_id,
        )
    if row.tenant_id:
        tenant_member = await session.execute(
            select(TenantMember).where(
                TenantMember.tenant_id == row.tenant_id,
                TenantMember.user_email == user.identity,
            )
        )
        if tenant_member.scalar_one_or_none():
            return user
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

    conversation_id = UUID(req.conversation_id) if req.conversation_id else None

    return StreamingResponse(
        _chat_stream(req, effective_user, conversation_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/conversations")
async def list_conversations(
    request: Request,
    domain_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
):
    user = await verify_auth(request, credentials, session)
    q = select(ChatConversation).where(
        ChatConversation.user_email == user.identity
    ).order_by(ChatConversation.updated_at.desc()).limit(50)
    if domain_id:
        q = q.where(ChatConversation.domain_id == UUID(domain_id))
    result = await session.execute(q)
    convs = result.scalars().all()
    return {"items": [
        {
            "id": str(c.id),
            "domain_id": str(c.domain_id),
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in convs
    ]}


@router.get("/chat/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
):
    user = await verify_auth(request, credentials, session)
    conv = (await session.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_email == user.identity,
        )
    )).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = (await session.execute(
        select(ChatMessageModel).where(
            ChatMessageModel.conversation_id == conversation_id
        ).order_by(ChatMessageModel.created_at)
    )).scalars().all()
    return {
        "id": str(conv.id),
        "domain_id": str(conv.domain_id),
        "title": conv.title,
        "messages": [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in msgs
        ],
    }


@router.delete("/chat/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
):
    user = await verify_auth(request, credentials, session)
    conv = (await session.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_email == user.identity,
        )
    )).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await session.delete(conv)
    await session.commit()
    return {"ok": True}
