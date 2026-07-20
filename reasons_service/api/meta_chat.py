"""Meta-expert chat API endpoint with SSE streaming."""

from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from reasons_service.chat.meta_loop import meta_chat_stream

router = APIRouter(prefix="/api/meta", tags=["meta-chat"])


class MetaChatRequest(BaseModel):
    message: str
    model: str = "gemini-2.5-pro"
    thread_id: str | None = None


@router.post("/chat")
async def meta_chat(data: MetaChatRequest):
    thread_id = data.thread_id or str(uuid4())

    return StreamingResponse(
        meta_chat_stream(data.model, data.message, thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-Id": thread_id,
        },
    )
