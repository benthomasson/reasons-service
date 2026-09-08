"""Domain CRUD API routes."""

import asyncio
import logging
import tempfile
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.auth import verify_auth
from reasons_service.config import settings
from reasons_service.db.connection import get_session
from reasons_service.db.models import Entry, Domain, DomainMember, Source, User
from reasons_service.rbac import Action, Role, require_action
from reasons_service.rms import api as rms_api

router = APIRouter(prefix="/api/domains", tags=["domains"])


class DomainCreate(BaseModel):
    name: str
    description: str
    config: dict = {}
    public: bool = False
    members_only: bool = False
    allowed_tags: list[str] = []


class DomainResponse(BaseModel):
    id: UUID
    name: str
    description: str
    config: dict
    public: bool = False
    members_only: bool = False
    allowed_tags: list[str] = []
    created_at: str
    source_count: int = 0
    entry_count: int = 0
    belief_count: int = 0

    model_config = {"from_attributes": True}


@router.post("", response_model=DomainResponse)
async def create_domain(data: DomainCreate, request: Request, session: AsyncSession = Depends(get_session)):
    domain_obj = Domain(
        name=data.name, description=data.description, config=data.config,
        public=data.public, members_only=data.members_only,
        allowed_tags=sorted(set(data.allowed_tags)),
    )
    session.add(domain_obj)
    await session.flush()
    user = request.state.user
    if user.identity not in ("api", "dev", "public"):
        session.add(DomainMember(
            domain_id=domain_obj.id,
            user_email=user.identity,
            role="admin",
        ))
    await session.commit()
    await session.refresh(domain_obj)
    return DomainResponse(
        id=domain_obj.id,
        name=domain_obj.name,
        description=domain_obj.description,
        config=domain_obj.config or {},
        public=domain_obj.public,
        members_only=domain_obj.members_only,
        allowed_tags=domain_obj.allowed_tags or [],
        created_at=domain_obj.created_at.isoformat(),
    )


async def _domain_counts(session: AsyncSession, domain_id):
    """Get source, entry, and belief counts for a domain."""
    src = await session.execute(select(func.count()).where(Source.domain_id == domain_id))
    ent = await session.execute(select(func.count()).where(Entry.domain_id == domain_id))
    blf = await asyncio.to_thread(rms_api.count_beliefs, domain_id, None)
    return src.scalar() or 0, ent.scalar() or 0, blf


@router.get("")
async def list_domains(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Domain).order_by(Domain.created_at.desc()))
    domains = result.scalars().all()
    user = request.state.user
    responses = []
    for d in domains:
        if d.members_only and user.role != Role.ADMIN and user.identity not in ("api", "dev"):
            member = await session.execute(
                select(DomainMember).where(
                    DomainMember.domain_id == d.id,
                    DomainMember.user_email == user.identity,
                )
            )
            if not member.scalar_one_or_none():
                continue
        sc, ec, cc = await _domain_counts(session, d.id)
        responses.append(DomainResponse(
            id=d.id,
            name=d.name,
            description=d.description,
            config=d.config or {},
            public=d.public,
            members_only=d.members_only,
            allowed_tags=d.allowed_tags or [],
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
        members_only=domain_obj.members_only,
        allowed_tags=domain_obj.allowed_tags or [],
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
    members_only: bool | None = None


@router.patch("/{domain_id}", response_model=DomainResponse,
              dependencies=[Depends(require_action(Action.MANAGE_DOMAINS))])
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
    sc, ec, cc = await _domain_counts(session, domain_obj.id)
    return DomainResponse(
        id=domain_obj.id,
        name=domain_obj.name,
        description=domain_obj.description,
        config=domain_obj.config or {},
        public=domain_obj.public,
        members_only=domain_obj.members_only,
        allowed_tags=domain_obj.allowed_tags or [],
        created_at=domain_obj.created_at.isoformat(),
        source_count=sc,
        entry_count=ec,
        belief_count=cc,
    )


@router.delete("/{domain_id}",
               dependencies=[Depends(require_action(Action.MANAGE_DOMAINS))])
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

        result = await asyncio.to_thread(
            rms_api.upsert_network, domain_id, network
        )

        return {
            "domain_id": str(domain_id),
            "added": result["added"],
            "updated": result["updated"],
            "total_in_file": result["total"],
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


# --- Domain membership management ---


class MemberCreate(BaseModel):
    email: str
    role: str = "reader"
    visible_tags: list[str] = []
    writable_tags: list[str] = []


class MemberUpdate(BaseModel):
    role: str | None = None
    visible_tags: list[str] | None = None
    writable_tags: list[str] | None = None


class MemberResponse(BaseModel):
    email: str
    role: str
    display_name: str | None = None
    visible_tags: list[str] = []
    writable_tags: list[str] = []
    created_at: str


_VALID_ROLES = {"admin", "reviewer", "editor", "reader"}


@router.get("/{domain_id}/members",
            dependencies=[Depends(require_action(Action.MANAGE_DOMAINS))])
async def list_members(domain_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(DomainMember, User.display_name)
        .join(User, DomainMember.user_email == User.email)
        .where(DomainMember.domain_id == domain_id)
        .order_by(DomainMember.created_at)
    )
    return [
        MemberResponse(
            email=row.DomainMember.user_email,
            role=row.DomainMember.role,
            display_name=row.display_name,
            visible_tags=row.DomainMember.visible_tags or [],
            writable_tags=row.DomainMember.writable_tags or [],
            created_at=row.DomainMember.created_at.isoformat(),
        )
        for row in result.all()
    ]


@router.post("/{domain_id}/members",
             dependencies=[Depends(require_action(Action.MANAGE_DOMAINS))])
async def add_member(
    domain_id: UUID,
    data: MemberCreate,
    session: AsyncSession = Depends(get_session),
):
    if data.role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {data.role}")
    email = data.email.strip().lower()
    user = await session.execute(select(User).where(User.email == email))
    if not user.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"User not found: {email}")
    domain = await session.execute(select(Domain).where(Domain.id == domain_id))
    if not domain.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Domain not found")
    existing = await session.execute(
        select(DomainMember).where(
            DomainMember.domain_id == domain_id,
            DomainMember.user_email == email,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"User {email} is already a member")
    member = DomainMember(
        domain_id=domain_id,
        user_email=email,
        role=data.role,
        visible_tags=sorted(set(data.visible_tags)),
        writable_tags=sorted(set(data.writable_tags)),
    )
    session.add(member)
    await session.commit()
    return {"email": data.email, "role": data.role, "domain_id": str(domain_id)}


@router.patch("/{domain_id}/members/{email}",
              dependencies=[Depends(require_action(Action.MANAGE_DOMAINS))])
async def update_member(
    domain_id: UUID,
    email: str,
    data: MemberUpdate,
    session: AsyncSession = Depends(get_session),
):
    email = email.strip().lower()
    result = await session.execute(
        select(DomainMember).where(
            DomainMember.domain_id == domain_id,
            DomainMember.user_email == email,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if data.role is not None:
        if data.role not in _VALID_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role: {data.role}")
        member.role = data.role
    if data.visible_tags is not None:
        member.visible_tags = sorted(set(data.visible_tags))
    if data.writable_tags is not None:
        member.writable_tags = sorted(set(data.writable_tags))
    member.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"email": email, "role": member.role, "domain_id": str(domain_id)}


@router.delete("/{domain_id}/members/{email}",
               dependencies=[Depends(require_action(Action.MANAGE_DOMAINS))])
async def remove_member(
    domain_id: UUID,
    email: str,
    session: AsyncSession = Depends(get_session),
):
    email = email.strip().lower()
    result = await session.execute(
        select(DomainMember).where(
            DomainMember.domain_id == domain_id,
            DomainMember.user_email == email,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await session.delete(member)
    await session.commit()
    return {"status": "removed", "email": email}


@router.get("/{domain_id}/members/me")
async def get_my_membership(
    domain_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user = request.state.user
    result = await session.execute(
        select(DomainMember).where(
            DomainMember.domain_id == domain_id,
            DomainMember.user_email == user.identity,
        )
    )
    member = result.scalar_one_or_none()
    return {
        "email": user.identity,
        "effective_role": user.role,
        "is_member": member is not None,
        "domain_role": member.role if member else None,
    }
