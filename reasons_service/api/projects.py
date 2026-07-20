"""Project CRUD API routes."""

import asyncio
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.config import settings
from reasons_service.db.connection import get_session
from reasons_service.db.models import Entry, Project, Source
from reasons_service.rms import api as rms_api

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    domain: str
    config: dict = {}
    public: bool = False


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    domain: str
    config: dict
    public: bool = False
    created_at: str
    source_count: int = 0
    entry_count: int = 0
    belief_count: int = 0

    model_config = {"from_attributes": True}


@router.post("", response_model=ProjectResponse)
async def create_project(data: ProjectCreate, session: AsyncSession = Depends(get_session)):
    project = Project(name=data.name, domain=data.domain, config=data.config, public=data.public)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        domain=project.domain,
        config=project.config or {},
        public=project.public,
        created_at=project.created_at.isoformat(),
    )


async def _project_counts(session: AsyncSession, project_id):
    """Get source, entry, and belief counts for a project."""
    src = await session.execute(select(func.count()).where(Source.project_id == project_id))
    ent = await session.execute(select(func.count()).where(Entry.project_id == project_id))
    blf = await asyncio.to_thread(rms_api.count_beliefs, project_id, None)
    return src.scalar() or 0, ent.scalar() or 0, blf


@router.get("")
async def list_projects(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    responses = []
    for p in projects:
        sc, ec, cc = await _project_counts(session, p.id)
        responses.append(ProjectResponse(
            id=p.id,
            name=p.name,
            domain=p.domain,
            config=p.config or {},
            public=p.public,
            created_at=p.created_at.isoformat(),
            source_count=sc,
            entry_count=ec,
            belief_count=cc,
        ))
    return responses


@router.get("/{project_id}")
async def get_project(project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    sc, ec, cc = await _project_counts(session, project.id)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        domain=project.domain,
        config=project.config or {},
        public=project.public,
        created_at=project.created_at.isoformat(),
        source_count=sc,
        entry_count=ec,
        belief_count=cc,
    )


class ProjectUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    config: dict | None = None
    public: bool | None = None


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: UUID, data: ProjectUpdate, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(project, field, value)
    await session.commit()
    await session.refresh(project)
    if "name" in update_fields or "domain" in update_fields:
        sc, ec, cc = await _project_counts(session, project.id)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        domain=project.domain,
        config=project.config or {},
        public=project.public,
        created_at=project.created_at.isoformat(),
        source_count=sc,
        entry_count=ec,
        belief_count=cc,
    )


@router.delete("/{project_id}")
async def delete_project(project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await session.delete(project)
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


@router.post("/{project_id}/import-reasons")
async def upsert_reasons(
    project_id: UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Upsert beliefs from a reasons.db or network.json file into an existing project.

    Nodes that already exist are skipped (preserving API-added beliefs).
    New nodes and their justifications are added.
    """
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    content = await file.read()
    try:
        network = _load_network_from_upload(content, file.filename or "")

        added = 0
        updated = 0

        def _do_upsert():
            nonlocal added, updated
            for node in network.nodes.values():
                meta = getattr(node, "metadata", {}) or {}
                try:
                    rms_api.add_node(
                        project_id, node.id, node.text,
                        source=node.source or "",
                        example=meta.get("example"),
                    )
                    added += 1
                except ValueError:
                    rms_api.update_node(
                        project_id, node.id,
                        text=node.text,
                        source=node.source or "",
                        example=meta.get("example"),
                    )
                    updated += 1
                if node.truth_value == "OUT":
                    rms_api.retract_node(project_id, node.id)
                else:
                    rms_api.assert_node(project_id, node.id)

        await asyncio.to_thread(_do_upsert)
    
        return {
            "project_id": str(project_id),
            "added": added,
            "updated": updated,
            "total_in_file": len(network.nodes),
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Invalid file: {e}")


@router.post("/import-reasons")
async def import_reasons(
    name: str = Form(...),
    domain: str = Form(""),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Import a reasons.db file to create a new project with beliefs.

    Creates the project, then imports the network via rms_api.import_network.
    """
    # Save upload to temp file for validation and import
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        tmp.write(content)

    try:
        # Verify it's a valid reasons_lib database
        from reasons_lib.storage import Storage
        store = Storage(str(tmp_path))
        network = store.load()
        store.close()

        # Create the project
        project = Project(name=name, domain=domain)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        # Import via public API
        result = await asyncio.to_thread(
            rms_api.import_network, project.id, network
        )
    
        return {
            "project_id": str(project.id),
            "name": project.name,
            "beliefs": result["node_count"],
            "nogoods": result["nogood_count"],
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Invalid reasons.db: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)
