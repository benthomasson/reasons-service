"""Tenant management API."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reasons_service.auth import verify_auth
from reasons_service.audit import audit_log, fire_audit
from reasons_service.db.connection import get_session
from reasons_service.db.models import Tenant, TenantMember, User
from reasons_service.rbac import Action, UserInfo, has_permission

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


class CreateTenantRequest(BaseModel):
    name: str
    display_name: str | None = None
    public: bool = False


class UpsertMemberRequest(BaseModel):
    role: str = "reader"


@router.get("")
async def list_tenants(
    user: UserInfo = Depends(verify_auth),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Tenant)
        .join(TenantMember, TenantMember.tenant_id == Tenant.id)
        .where(TenantMember.user_email == user.identity)
    )
    tenants = result.scalars().all()
    return {
        "items": [
            {
                "id": t.id,
                "name": t.name,
                "display_name": t.display_name,
                "type": t.type,
                "public": t.public,
            }
            for t in tenants
        ]
    }


@router.post("", status_code=201)
async def create_tenant(
    body: CreateTenantRequest,
    user: UserInfo = Depends(verify_auth),
    session: AsyncSession = Depends(get_session),
):
    if not has_permission(user.role, Action.MANAGE_SOURCES):
        raise HTTPException(status_code=403, detail="Editor role or higher required to create tenants")

    tenant = Tenant(
        id=str(uuid4()),
        name=body.name,
        display_name=body.display_name or body.name,
        type="organization",
        public=body.public,
    )
    session.add(tenant)
    await session.flush()

    membership = TenantMember(
        id=uuid4(),
        tenant_id=tenant.id,
        user_email=user.identity,
        role="tenant_admin",
    )
    session.add(membership)
    await session.commit()

    fire_audit(audit_log(
        actor=user.identity,
        action="tenant.create",
        resource_type="tenant",
        resource_id=tenant.id,
    ))

    return {
        "id": tenant.id,
        "name": tenant.name,
        "display_name": tenant.display_name,
        "type": tenant.type,
        "public": tenant.public,
    }


@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    user: UserInfo = Depends(verify_auth),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    membership = await session.execute(
        select(TenantMember.role).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_email == user.identity,
        )
    )
    member = membership.scalar_one_or_none()

    if not member and not tenant.public and user.role != "admin":
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "id": tenant.id,
        "name": tenant.name,
        "display_name": tenant.display_name,
        "type": tenant.type,
        "public": tenant.public,
        "your_role": member or ("admin" if user.role == "admin" else "reader"),
    }


@router.get("/{tenant_id}/members")
async def list_members(
    tenant_id: str,
    user: UserInfo = Depends(verify_auth),
    session: AsyncSession = Depends(get_session),
):
    membership = await session.execute(
        select(TenantMember.role).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_email == user.identity,
        )
    )
    if not membership.scalar_one_or_none() and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not a member of this tenant")

    result = await session.execute(
        select(TenantMember, User.display_name)
        .join(User, TenantMember.user_email == User.email, isouter=True)
        .where(TenantMember.tenant_id == tenant_id)
        .order_by(TenantMember.created_at)
    )
    rows = result.all()
    return {
        "items": [
            {
                "email": m.user_email,
                "role": m.role,
                "display_name": dn,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m, dn in rows
        ]
    }


@router.put("/{tenant_id}/members/{email}")
async def upsert_member(
    tenant_id: str,
    email: str,
    body: UpsertMemberRequest,
    user: UserInfo = Depends(verify_auth),
    session: AsyncSession = Depends(get_session),
):
    membership = await session.execute(
        select(TenantMember.role).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_email == user.identity,
        )
    )
    caller_role = membership.scalar_one_or_none()
    if user.role != "admin" and caller_role != "tenant_admin":
        raise HTTPException(status_code=403, detail="Tenant admin required")

    valid_roles = ["tenant_admin", "editor", "reviewer", "reader"]
    if body.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}")

    result = await session.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_email == email,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.role = body.role
    else:
        session.add(TenantMember(id=uuid4(), tenant_id=tenant_id, user_email=email, role=body.role))

    await session.commit()

    fire_audit(audit_log(
        actor=user.identity,
        action="tenant_member.upsert",
        resource_type="tenant_member",
        resource_id=email,
        metadata={"tenant_id": tenant_id, "role": body.role},
    ))

    return {"email": email, "role": body.role, "tenant_id": tenant_id}


@router.delete("/{tenant_id}/members/{email}")
async def remove_member(
    tenant_id: str,
    email: str,
    user: UserInfo = Depends(verify_auth),
    session: AsyncSession = Depends(get_session),
):
    membership = await session.execute(
        select(TenantMember.role).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_email == user.identity,
        )
    )
    caller_role = membership.scalar_one_or_none()
    if user.role != "admin" and caller_role != "tenant_admin":
        raise HTTPException(status_code=403, detail="Tenant admin required")

    result = await session.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_email == email,
        )
    )
    member = result.scalar_one_or_none()
    if member:
        await session.delete(member)
        await session.commit()

    fire_audit(audit_log(
        actor=user.identity,
        action="tenant_member.remove",
        resource_type="tenant_member",
        resource_id=email,
        metadata={"tenant_id": tenant_id},
    ))

    return {"status": "removed", "email": email, "tenant_id": tenant_id}
