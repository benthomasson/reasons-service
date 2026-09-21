"""Audit log query API — admin-only read access to the append-only audit trail."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.auth import verify_auth
from reasons_service.db.connection import get_session
from reasons_service.db.models import AuditLog
from reasons_service.rbac import Action, require_action

router = APIRouter(
    prefix="/api/audit",
    tags=["audit"],
    dependencies=[Depends(verify_auth), Depends(require_action(Action.ADMIN))],
)


@router.get("")
async def list_audit_logs(
    domain_id: UUID | None = None,
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    base = select(AuditLog)
    if domain_id is not None:
        base = base.where(AuditLog.domain_id == domain_id)
    if actor is not None:
        base = base.where(AuditLog.actor == actor)
    if action is not None:
        base = base.where(AuditLog.action == action)
    if resource_type is not None:
        base = base.where(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        base = base.where(AuditLog.resource_id == resource_id)
    if since is not None:
        base = base.where(AuditLog.timestamp >= since)
    if until is not None:
        base = base.where(AuditLog.timestamp <= until)

    total_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0

    result = await session.execute(
        base.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
    )
    items = [
        {
            "id": str(row.id),
            "timestamp": row.timestamp.isoformat(),
            "actor": row.actor,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "domain_id": str(row.domain_id) if row.domain_id else None,
            "before_state": row.before_state,
            "after_state": row.after_state,
            "metadata": row.metadata_,
        }
        for row in result.scalars().all()
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}
