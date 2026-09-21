"""Fire-and-forget audit logging."""

import asyncio
import logging
from uuid import UUID

from reasons_service.db.connection import async_session
from reasons_service.db.models import AuditLog

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


async def audit_log(
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    domain_id: UUID | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    metadata: dict | None = None,
) -> None:
    try:
        async with async_session() as session:
            session.add(AuditLog(
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                domain_id=domain_id,
                before_state=before_state,
                after_state=after_state,
                metadata_=metadata,
            ))
            await session.commit()
    except Exception:
        logger.exception("Failed to write audit log: %s %s", action, resource_id)


def fire_audit(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def drain() -> None:
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
