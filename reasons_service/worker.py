"""Background task worker — runs forge pipeline stages.

When launched as a K8s Job, reads config from environment variables.
When called in-process, receives arguments directly.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.db.connection import async_session, init_db
from reasons_service.db.models import Task

log = logging.getLogger(__name__)


async def _update_task(task_id: str, **kwargs):
    async with async_session() as session:
        await session.execute(
            update(Task).where(Task.id == UUID(task_id)).values(**kwargs)
        )
        await session.commit()


async def run_task(task_id: str, domain_id: str, task_type: str, config: dict):
    log.info("Starting task %s type=%s domain=%s", task_id, task_type, domain_id)

    await _update_task(
        task_id,
        status="running",
        started_at=datetime.now(timezone.utc),
    )

    try:
        if task_type == "echo":
            await _run_echo(task_id, config)
        else:
            raise ValueError(f"Unknown task type: {task_type}")

        await _update_task(
            task_id,
            status="completed",
            completed_at=datetime.now(timezone.utc),
            result={"message": f"Task {task_type} completed"},
        )
        log.info("Task %s completed", task_id)

    except Exception as e:
        log.exception("Task %s failed: %s", task_id, e)
        await _update_task(
            task_id,
            status="failed",
            completed_at=datetime.now(timezone.utc),
            error=str(e),
        )


async def _run_echo(task_id: str, config: dict):
    """Simple test task — logs a message and updates progress."""
    message = config.get("message", "Hello from worker!")
    steps = config.get("steps", 3)
    delay = config.get("delay", 2)

    for i in range(1, steps + 1):
        await asyncio.sleep(delay)
        progress = {"step": i, "total": steps, "message": f"Step {i}/{steps}: {message}"}
        await _update_task(task_id, progress=progress)
        log.info("Task %s progress: %s", task_id, progress)


async def _main():
    """Entry point for K8s Job execution."""
    task_id = os.environ["TASK_ID"]
    domain_id = os.environ["DOMAIN_ID"]
    task_type = os.environ["TASK_TYPE"]
    config = json.loads(os.environ.get("TASK_CONFIG", "{}"))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    init_db()
    await run_task(task_id, domain_id, task_type, config)


if __name__ == "__main__":
    asyncio.run(_main())
