"""Domain CRUD API routes."""

import asyncio
import logging
import tempfile
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.config import settings
from reasons_service.db.connection import get_session
from reasons_service.db.models import Entry, Domain, Source
from reasons_service.rms import api as rms_api

router = APIRouter(prefix="/api/domains", tags=["domains"])


class DomainCreate(BaseModel):
    name: str
    description: str
    config: dict = {}
    public: bool = False


class DomainResponse(BaseModel):
    id: UUID
    name: str
    description: str
    config: dict
    public: bool = False
    created_at: str
    source_count: int = 0
    entry_count: int = 0
    belief_count: int = 0

    model_config = {"from_attributes": True}


@router.post("", response_model=DomainResponse)
async def create_domain(data: DomainCreate, session: AsyncSession = Depends(get_session)):
    domain_obj = Domain(name=data.name, description=data.description, config=data.config, public=data.public)
    session.add(domain_obj)
    await session.commit()
    await session.refresh(domain_obj)
    return DomainResponse(
        id=domain_obj.id,
        name=domain_obj.name,
        description=domain_obj.description,
        config=domain_obj.config or {},
        public=domain_obj.public,
        created_at=domain_obj.created_at.isoformat(),
    )


async def _domain_counts(session: AsyncSession, domain_id):
    """Get source, entry, and belief counts for a domain."""
    src = await session.execute(select(func.count()).where(Source.domain_id == domain_id))
    ent = await session.execute(select(func.count()).where(Entry.domain_id == domain_id))
    blf = await asyncio.to_thread(rms_api.count_beliefs, domain_id, None)
    return src.scalar() or 0, ent.scalar() or 0, blf


@router.get("")
async def list_domains(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Domain).order_by(Domain.created_at.desc()))
    domains = result.scalars().all()
    responses = []
    for d in domains:
        sc, ec, cc = await _domain_counts(session, d.id)
        responses.append(DomainResponse(
            id=d.id,
            name=d.name,
            description=d.description,
            config=d.config or {},
            public=d.public,
            created_at=d.created_at.isoformat(),
            source_count=sc,
            entry_count=ec,
            belief_count=cc,
        ))
    return responses


@router.get("/{domain_id}")
async def get_domain(domain_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Domain).where(Domain.id == domain_id))
    domain_obj = result.scalar_one_or_none()
    if not domain_obj:
        raise HTTPException(status_code=404, detail="Domain not found")
    sc, ec, cc = await _domain_counts(session, domain_obj.id)
    return DomainResponse(
        id=domain_obj.id,
        name=domain_obj.name,
        description=domain_obj.description,
        config=domain_obj.config or {},
        public=domain_obj.public,
        created_at=domain_obj.created_at.isoformat(),
        source_count=sc,
        entry_count=ec,
        belief_count=cc,
    )


class DomainUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict | None = None
    public: bool | None = None


@router.patch("/{domain_id}", response_model=DomainResponse)
async def update_domain(domain_id: UUID, data: DomainUpdate, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Domain).where(Domain.id == domain_id))
    domain_obj = result.scalar_one_or_none()
    if not domain_obj:
        raise HTTPException(status_code=404, detail="Domain not found")
    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(domain_obj, field, value)
    await session.commit()
    await session.refresh(domain_obj)
    if "name" in update_fields or "description" in update_fields:
        sc, ec, cc = await _domain_counts(session, domain_obj.id)
    return DomainResponse(
        id=domain_obj.id,
        name=domain_obj.name,
        description=domain_obj.description,
        config=domain_obj.config or {},
        public=domain_obj.public,
        created_at=domain_obj.created_at.isoformat(),
        source_count=sc,
        entry_count=ec,
        belief_count=cc,
    )


@router.delete("/{domain_id}")
async def delete_domain(domain_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Domain).where(Domain.id == domain_id))
    domain_obj = result.scalar_one_or_none()
    if not domain_obj:
        raise HTTPException(status_code=404, detail="Domain not found")
    await session.delete(domain_obj)
    await session.commit()
    return {"status": "deleted"}


def _load_network_from_upload(content: bytes, filename: str):
    """Load a reasons_lib Network from an uploaded file (reasons.db or network.json)."""
    import json

    if filename.endswith(".json"):
        data = json.loads(content)
        nodes = data.get("nodes", {})
        from types import SimpleNamespace
        network_nodes = {}
        for node_id, node_data in nodes.items():
            network_nodes[node_id] = SimpleNamespace(
                id=node_id,
                text=node_data.get("text", ""),
                truth_value=node_data.get("truth_value", "IN"),
                source=node_data.get("source", ""),
                justifications=node_data.get("justifications", []),
                metadata=node_data.get("metadata", {}),
            )
        return SimpleNamespace(nodes=network_nodes)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(content)
    try:
        from reasons_lib.storage import Storage
        store = Storage(str(tmp_path))
        network = store.load()
        store.close()
        return network
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/{domain_id}/import-reasons")
async def upsert_reasons(
    domain_id: UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Upsert beliefs from a reasons.db or network.json file into an existing domain.

    Nodes that already exist are skipped (preserving API-added beliefs).
    New nodes and their justifications are added.
    """
    result = await session.execute(select(Domain).where(Domain.id == domain_id))
    domain_obj = result.scalar_one_or_none()
    if not domain_obj:
        raise HTTPException(status_code=404, detail="Domain not found")

    content = await file.read()
    try:
        logger.info("import-reasons: loading file %s (%d bytes) for domain %s",
                     file.filename, len(content), domain_id)
        network = _load_network_from_upload(content, file.filename or "")
        total = len(network.nodes)
        logger.info("import-reasons: parsed %d nodes from %s", total, file.filename)

        added = 0
        updated = 0

        def _do_upsert():
            nonlocal added, updated
            for i, node in enumerate(network.nodes.values(), 1):
                meta = getattr(node, "metadata", {}) or {}
                try:
                    rms_api.add_node(
                        domain_id, node.id, node.text,
                        source=node.source or "",
                        example=meta.get("example"),
                    )
                    added += 1
                except ValueError:
                    rms_api.update_node(
                        domain_id, node.id,
                        text=node.text,
                        source=node.source or "",
                        example=meta.get("example"),
                    )
                    updated += 1
                if node.truth_value == "OUT":
                    rms_api.retract_node(domain_id, node.id)
                else:
                    rms_api.assert_node(domain_id, node.id)
                if i % 500 == 0:
                    logger.info("import-reasons: %d/%d nodes processed (%d added, %d updated)",
                                i, total, added, updated)

        await asyncio.to_thread(_do_upsert)

        logger.info("import-reasons: complete — %d added, %d updated, %d total",
                     added, updated, total)
        return {
            "domain_id": str(domain_id),
            "added": added,
            "updated": updated,
            "total_in_file": total,
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.exception("import-reasons: failed for domain %s", domain_id)
        raise HTTPException(status_code=400, detail=f"Invalid file: {e}")


@router.post("/import-reasons")
async def import_reasons(
    name: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Import a reasons.db file to create a new domain with beliefs.

    Creates the domain, then imports the network via rms_api.import_network.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        tmp.write(content)

    try:
        logger.info("import-reasons: loading %s (%d bytes) for new domain '%s'",
                     file.filename, len(content), name)
        from reasons_lib.storage import Storage
        store = Storage(str(tmp_path))
        network = store.load()
        store.close()
        logger.info("import-reasons: parsed %d nodes from %s", len(network.nodes), file.filename)

        domain_obj = Domain(name=name, description=description)
        session.add(domain_obj)
        await session.commit()
        await session.refresh(domain_obj)
        logger.info("import-reasons: created domain '%s' (%s)", name, domain_obj.id)

        result = await asyncio.to_thread(
            rms_api.import_network, domain_obj.id, network
        )

        logger.info("import-reasons: complete — %d beliefs, %d nogoods imported into '%s'",
                     result["node_count"], result["nogood_count"], name)
        return {
            "domain_id": str(domain_obj.id),
            "name": domain_obj.name,
            "beliefs": result["node_count"],
            "nogoods": result["nogood_count"],
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.exception("import-reasons: failed for new domain '%s'", name)
        raise HTTPException(status_code=400, detail=f"Invalid reasons.db: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)
