"""Chat API endpoint with SSE streaming."""

import json
import logging
from uuid import UUID, uuid4

import anthropic
import httpx
from fastapi import APIRouter
from google.api_core import exceptions as google_exceptions
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, text as sa_text

from reasons_service.chat.loop import chat_stream, dual_ask, dual_chat_stream, single_ask
from reasons_service.config import settings

logger = logging.getLogger(__name__)
from reasons_service.db.connection import get_sync_session

router = APIRouter(prefix="/api/projects/{project_id}", tags=["chat"])


def _get_project_connectors(project_id: UUID) -> list[str] | None:
    """Read the project's connector whitelist from config."""
    with get_sync_session() as session:
        row = session.execute(
            sa_text("SELECT config FROM projects WHERE id = :pid"),
            {"pid": str(project_id)},
        ).first()
    if not row or not row.config:
        return None
    config = row.config
    # SQLite returns JSON as string; PostgreSQL returns dict
    if isinstance(config, str):
        config = json.loads(config)
    if isinstance(config, dict):
        connectors = config.get("connectors")
        if isinstance(connectors, list) and connectors:
            return connectors
    return None


class ChatRequest(BaseModel):
    message: str
    model: str = "claude-sonnet-4-6"
    thread_id: str | None = None
    dual: bool = True


@router.post("/chat")
async def chat(project_id: UUID, data: ChatRequest):
    thread_id = data.thread_id or str(uuid4())
    allowed = _get_project_connectors(project_id)

    if data.dual:
        stream = dual_chat_stream(project_id, data.model, data.message, thread_id,
                                  allowed_connectors=allowed)
    else:
        stream = chat_stream(project_id, data.model, data.message, thread_id)

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-Id": thread_id,
        },
    )


class AskRequest(BaseModel):
    question: str
    model: str = "claude-sonnet-4-6"
    mode: str = "dual"  # "dual" (3-call merge) or "single" (1-call synthesis)


@router.post("/ask")
async def ask(project_id: UUID, data: AskRequest):
    """Non-streaming answer. Mode: 'dual' (3-call merge) or 'single' (1-call synthesis)."""
    model = data.model or settings.default_model
    logger.info("ask project=%s model=%s mode=%s", project_id, model, data.mode)
    try:
        if data.mode == "single":
            return await single_ask(project_id, data.model, data.question)
        allowed = _get_project_connectors(project_id)
        return await dual_ask(project_id, data.model, data.question,
                              allowed_connectors=allowed)
    except (httpx.HTTPError, anthropic.APIError, google_exceptions.GoogleAPIError, OSError, TimeoutError) as exc:
        detail = f"model={model}"
        if model.startswith("ollama:"):
            detail += f" host={settings.ollama_host}"
        logger.exception("LLM call failed for project %s (%s)", project_id, detail)
        return JSONResponse(
            status_code=502,
            content={"error": f"The language model is temporarily unavailable ({detail}). Please try again."},
        )
