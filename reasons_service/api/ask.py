"""Lightweight belief-search endpoint — no LLM, just FTS."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from reasons_service.rms import api as rms_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["ask"])


class AskRequest(BaseModel):
    question: str


@router.post("/ask")
async def ask(project_id: UUID, data: AskRequest):
    try:
        result = rms_api.search(project_id, data.question)
        results = result.get("results", [])
        count = result.get("count", len(results))
    except Exception:
        logger.exception("Search failed for project %s", project_id)
        raise HTTPException(status_code=500, detail="Search failed")
    compact = "\n".join(
        f"[{r.get('truth_value', 'UNKNOWN')}] {r.get('id', '?')} — {r.get('text', '')}"
        for r in results
    )
    return {
        "question": data.question,
        "beliefs": results,
        "count": count,
        "compact": compact,
    }
