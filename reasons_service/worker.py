"""Background task worker — runs forge pipeline stages.

When launched as a K8s Job, reads config from environment variables.
When called in-process, receives arguments directly.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
from sqlalchemy import update

from reasons_service.db.connection import async_session, init_db
from reasons_service.db.models import Task

log = logging.getLogger(__name__)


def _service_url() -> str:
    return os.environ.get("REASONS_SERVICE_URL", "http://reasons-service:8000")


def _service_token() -> str:
    return os.environ.get("REASONS_SERVICE_API_KEY", os.environ.get("API_KEY", ""))


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
        elif task_type == "document_forge":
            await _run_document_forge(task_id, domain_id, config)
        elif task_type == "derive_review_repair":
            await _run_derive_review_repair(task_id, domain_id, config)
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
    message = config.get("message", "Hello from worker!")
    steps = config.get("steps", 3)
    delay = config.get("delay", 2)

    for i in range(1, steps + 1):
        await asyncio.sleep(delay)
        progress = {"step": i, "total": steps, "message": f"Step {i}/{steps}: {message}"}
        await _update_task(task_id, progress=progress)
        log.info("Task %s progress: %s", task_id, progress)


async def _build_reasons_db(db_path: Path, domain_id: str, base_url: str, headers: dict):
    """Build a reasons.db from domain beliefs fetched via the API."""
    from reasonsforge.network import Network
    from reasonsforge.storage import Storage

    network = Network()

    async with httpx.AsyncClient(timeout=120) as client:
        offset = 0
        limit = 500
        total = 0
        while True:
            resp = await client.get(
                f"{base_url}/api/domains/{domain_id}/beliefs",
                headers=headers,
                params={"offset": offset, "limit": limit},
            )
            if resp.status_code != 200:
                log.warning("Failed to fetch beliefs (offset=%d): %d", offset, resp.status_code)
                break
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                if item["id"] not in network.nodes:
                    network.add_node(
                        id=item["id"],
                        text=item.get("text", ""),
                        source=item.get("source", ""),
                        source_hash=item.get("source_hash", ""),
                    )
            total += len(items)
            offset += limit
            if len(items) < limit:
                break

    storage = Storage(str(db_path))
    storage.save(network)
    storage.close()

    log.info("Built reasons.db with %d beliefs from domain %s", total, domain_id)


async def _run_document_forge(task_id: str, domain_id: str, config: dict):
    work_dir = Path(tempfile.mkdtemp(prefix=f"forge-{task_id[:8]}-"))
    try:
        await _do_document_forge(task_id, domain_id, config, work_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def _do_document_forge(task_id: str, domain_id: str, config: dict, work_dir: Path):
    base_url = _service_url()
    token = _service_token()
    headers = {"Authorization": f"Bearer {token}"}

    sources_dir = work_dir / "sources"
    sources_dir.mkdir()

    await _update_task(task_id, progress={"stage": "downloading", "percent": 5})

    source_slugs = config.get("source_slugs", [])
    async with httpx.AsyncClient(timeout=120) as client:
        for slug in source_slugs:
            resp = await client.get(
                f"{base_url}/api/domains/{domain_id}/sources/{slug}",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                (sources_dir / f"{slug}.md").write_text(data.get("content", ""), encoding="utf-8")
                log.info("Downloaded source: %s", slug)

    db_path = work_dir / "reasons.db"
    try:
        from reasonsforge.storage import Storage
        Storage(str(db_path))
        log.info("Initialized empty reasons.db")
    except Exception as e:
        log.warning("Could not init reasons.db: %s", e)

    model = config.get("model", "openai:gpt-5.6-luna")
    domain = config.get("domain", "")
    rounds = config.get("rounds", 1)
    max_derive = config.get("max_derive_rounds", 10)

    orig_dir = os.getcwd()
    os.chdir(str(work_dir))

    try:
        await _update_task(task_id, progress={"stage": "forging", "percent": 15})

        from reasonsforge.forge.pipeline import cmd_pipeline
        args = SimpleNamespace(
            sources_dir=str(sources_dir),
            pdf=None,
            model=model,
            rounds=rounds,
            max_derive_rounds=max_derive,
            search_rounds=0,
            no_auto_accept=False,
            timeout=600,
            domain=domain,
            parallel=1,
            recursive=False,
            resume=False,
            namespace=None,
            mode=None,
            num_ctx=None,
            index_db=str(work_dir / "rag_fts.db"),
        )

        await asyncio.to_thread(cmd_pipeline, args)

        await _update_task(task_id, progress={"stage": "uploading", "percent": 90})

        if db_path.exists():
            async with httpx.AsyncClient(timeout=300) as client:
                with open(db_path, "rb") as f:
                    resp = await client.post(
                        f"{base_url}/api/domains/{domain_id}/import-reasons",
                        headers=headers,
                        files={"file": ("reasons.db", f, "application/octet-stream")},
                    )
                if resp.status_code == 200:
                    log.info("Uploaded reasons.db (%d bytes)", db_path.stat().st_size)
                else:
                    log.error("Upload failed: %d %s", resp.status_code, resp.text[:200])
    finally:
        os.chdir(orig_dir)


async def _run_derive_review_repair(task_id: str, domain_id: str, config: dict):
    work_dir = Path(tempfile.mkdtemp(prefix=f"derive-{task_id[:8]}-"))
    try:
        await _do_derive_review_repair(task_id, domain_id, config, work_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def _do_derive_review_repair(task_id: str, domain_id: str, config: dict, work_dir: Path):
    base_url = _service_url()
    token = _service_token()
    headers = {"Authorization": f"Bearer {token}"}

    db_path = work_dir / "reasons.db"

    await _update_task(task_id, progress={"stage": "downloading", "percent": 5})

    await _build_reasons_db(db_path, domain_id, base_url, headers)

    model = config.get("model", "openai:gpt-5.6-luna")
    rounds = config.get("rounds", 3)
    max_derive = config.get("max_derive_rounds", 10)
    domain = config.get("domain", "")

    orig_dir = os.getcwd()
    os.chdir(str(work_dir))

    try:
        import reasonsforge.forge as forge
        forge.REASONS_DB = "reasons.db"
        import reasonsforge.forge.pipeline as pipeline_mod
        pipeline_mod.REASONS_DB = "reasons.db"

        await _update_task(task_id, progress={"stage": "deriving", "percent": 20})

        from reasonsforge.forge.pipeline import cmd_derive_review_repair
        args = SimpleNamespace(
            model=model,
            rounds=rounds,
            max_derive_rounds=max_derive,
            search_rounds=0,
            timeout=600,
            domain=domain,
            namespace=None,
            verify_dedup=True,
        )

        log.info("Running derive-review-repair (rounds=%d, model=%s)", rounds, model)
        await asyncio.to_thread(cmd_derive_review_repair, args)

        await _update_task(task_id, progress={"stage": "uploading", "percent": 90})

        if db_path.exists():
            async with httpx.AsyncClient(timeout=300) as client:
                with open(db_path, "rb") as f:
                    resp = await client.post(
                        f"{base_url}/api/domains/{domain_id}/import-reasons",
                        headers=headers,
                        files={"file": ("reasons.db", f, "application/octet-stream")},
                    )
                if resp.status_code == 200:
                    log.info("Uploaded reasons.db (%d bytes)", db_path.stat().st_size)
                else:
                    log.error("Upload failed: %d %s", resp.status_code, resp.text[:200])
    finally:
        os.chdir(orig_dir)


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
