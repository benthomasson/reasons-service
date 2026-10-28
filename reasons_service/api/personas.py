"""Personas API — CRUD for named domain collections."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.auth import verify_auth
from reasons_service.db.connection import get_session
from reasons_service.db.models import Domain, Persona, persona_domains

router = APIRouter(prefix="/api/personas", tags=["personas"])


class PersonaCreate(BaseModel):
    name: str
    description: str = ""
    system_prompt: str | None = None
    domain_ids: list[str] = []


class PersonaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    domain_ids: list[str] | None = None


async def _persona_dict(session: AsyncSession, p: Persona) -> dict:
    rows = (await session.execute(
        select(Domain.id, Domain.name)
        .join(persona_domains, Domain.id == persona_domains.c.domain_id)
        .where(persona_domains.c.persona_id == p.id)
    )).all()
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "system_prompt": p.system_prompt,
        "domain_ids": [str(r.id) for r in rows],
        "domains": [{"id": str(r.id), "name": r.name} for r in rows],
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
async def list_personas(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Persona).order_by(Persona.name))
    personas = result.scalars().all()
    return {"items": [await _persona_dict(session, p) for p in personas]}


@router.get("/{persona_id}")
async def get_persona(persona_id: UUID, session: AsyncSession = Depends(get_session)):
    p = (await session.execute(
        select(Persona).where(Persona.id == persona_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Persona not found")
    return await _persona_dict(session, p)


@router.post("", status_code=201)
async def create_persona(
    data: PersonaCreate,
    session: AsyncSession = Depends(get_session),
):
    existing = (await session.execute(
        select(Persona).where(Persona.name == data.name)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Persona with this name already exists")

    p = Persona(name=data.name, description=data.description, system_prompt=data.system_prompt)
    session.add(p)
    await session.flush()

    for did in data.domain_ids:
        domain = (await session.execute(
            select(Domain).where(Domain.id == UUID(did))
        )).scalar_one_or_none()
        if domain:
            await session.execute(
                insert(persona_domains).values(persona_id=p.id, domain_id=domain.id)
            )

    await session.commit()
    return await _persona_dict(session, p)


@router.put("/{persona_id}")
async def update_persona(
    persona_id: UUID,
    data: PersonaUpdate,
    session: AsyncSession = Depends(get_session),
):
    p = (await session.execute(
        select(Persona).where(Persona.id == persona_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Persona not found")

    if data.name is not None:
        p.name = data.name
    if data.description is not None:
        p.description = data.description
    if data.system_prompt is not None:
        p.system_prompt = data.system_prompt

    if data.domain_ids is not None:
        await session.execute(
            delete(persona_domains).where(persona_domains.c.persona_id == persona_id)
        )
        for did in data.domain_ids:
            domain = (await session.execute(
                select(Domain).where(Domain.id == UUID(did))
            )).scalar_one_or_none()
            if domain:
                await session.execute(
                    insert(persona_domains).values(persona_id=p.id, domain_id=domain.id)
                )

    await session.commit()
    return await _persona_dict(session, p)


@router.delete("/{persona_id}", status_code=204)
async def delete_persona(
    persona_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    p = (await session.execute(
        select(Persona).where(Persona.id == persona_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Persona not found")
    await session.delete(p)
    await session.commit()
