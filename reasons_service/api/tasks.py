"""Tasks API — create, list, and manage background tasks."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.auth import verify_auth
from reasons_service.db.connection import get_session
from reasons_service.db.models import Task
from reasons_service.dispatcher import dispatch_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    domain_id: str
    type: str
    config: dict = {}


class TaskProgress(BaseModel):
    progress: dict = {}


class TaskComplete(BaseModel):
    result: dict | None = None
    error: str | None = None


def _task_dict(t: Task) -> dict:
    return {
        "id": str(t.id),
        "domain_id": str(t.domain_id),
        "type": t.type,
        "status": t.status,
        "config": t.config,
        "progress": t.progress,
        "result": t.result,
        "error": t.error,
        "created_by": t.created_by,
        "job_name": t.job_name,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }


@router.get("")
async def list_tasks(
    domain_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    q = select(Task).order_by(Task.created_at.desc()).limit(limit)
    if domain_id:
        q = q.where(Task.domain_id == UUID(domain_id))
    if status:
        q = q.where(Task.status == status)
    result = await session.execute(q)
    return {"items": [_task_dict(t) for t in result.scalars().all()]}


@router.get("/{task_id}")
async def get_task(task_id: UUID, session: AsyncSession = Depends(get_session)):
    t = (await session.execute(
        select(Task).where(Task.id == task_id)
    )).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_dict(t)


@router.post("", status_code=201)
async def create_task(
    data: TaskCreate,
    session: AsyncSession = Depends(get_session),
):
    t = Task(
        domain_id=UUID(data.domain_id),
        type=data.type,
        config=data.config,
        status="pending",
    )
    session.add(t)
    await session.flush()

    dispatch_result = await dispatch_task(
        task_id=t.id,
        domain_id=t.domain_id,
        task_type=data.type,
        config=data.config,
    )

    if "job_name" in dispatch_result:
        t.job_name = dispatch_result["job_name"]
    if "error" in dispatch_result:
        t.error = dispatch_result["error"]
        t.status = "failed"

    await session.commit()
    return _task_dict(t)


@router.post("/{task_id}/progress")
async def update_progress(
    task_id: UUID,
    data: TaskProgress,
    session: AsyncSession = Depends(get_session),
):
    t = (await session.execute(
        select(Task).where(Task.id == task_id)
    )).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    t.progress = data.progress
    await session.commit()
    return _task_dict(t)


@router.post("/{task_id}/complete")
async def complete_task(
    task_id: UUID,
    data: TaskComplete,
    session: AsyncSession = Depends(get_session),
):
    t = (await session.execute(
        select(Task).where(Task.id == task_id)
    )).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    t.completed_at = datetime.now(timezone.utc)
    if data.error:
        t.status = "failed"
        t.error = data.error
    else:
        t.status = "completed"
        t.result = data.result

    await session.commit()
    return _task_dict(t)


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    t = (await session.execute(
        select(Task).where(Task.id == task_id)
    )).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.status in ("completed", "failed"):
        raise HTTPException(status_code=409, detail=f"Task already {t.status}")

    t.status = "cancelled"
    t.completed_at = datetime.now(timezone.utc)
    await session.commit()
    return _task_dict(t)
