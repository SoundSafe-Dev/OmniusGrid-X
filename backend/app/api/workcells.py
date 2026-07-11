"""Workcell and Organization read endpoints (FS-18).

The web client's assetsApi.workcellsApi / organizationsApi called
/api/v1/workcells and /api/v1/organizations, which had no router. These serve
the read paths those clients need, tenant-scoped to the caller's organization.
Responses are snake_case; the client camel-cases them via transform.ts.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.middleware.tenant_isolation import get_tenant_org_id, get_tenant_db
from app.db.models import Workcell, Organization

workcells_router = APIRouter(dependencies=[Depends(get_current_active_user)])
organizations_router = APIRouter(dependencies=[Depends(get_current_active_user)])


def _workcell_out(w: Workcell) -> dict:
    return {
        "id": str(w.id),
        "organization_id": str(w.organization_id) if w.organization_id else None,
        "name": w.name,
        "description": w.description,
        "location": w.location,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


def _org_out(o: Organization) -> dict:
    return {
        "id": str(o.id),
        "name": o.name,
        "slug": o.slug,
        "settings": o.settings or {},
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


@workcells_router.get("/")
async def list_workcells(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    # Always scoped to the caller's organization (any client-sent organization_id
    # is ignored — a user can only see their own org's workcells).
    rows = (await db.execute(
        select(Workcell).where(Workcell.organization_id == org_id).order_by(Workcell.name.asc())
    )).scalars().all()
    return [_workcell_out(w) for w in rows]


@workcells_router.get("/{workcell_id}")
async def get_workcell(
    workcell_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    w = (await db.execute(
        select(Workcell).where(Workcell.id == workcell_id, Workcell.organization_id == org_id)
    )).scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="workcell not found")
    return _workcell_out(w)


@organizations_router.get("/")
async def list_organizations(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    # A user sees only their own organization.
    o = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    return [_org_out(o)] if o else []


@organizations_router.get("/{organization_id}")
async def get_organization(
    organization_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    if str(organization_id) != str(org_id):
        raise HTTPException(status_code=404, detail="organization not found")
    o = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if o is None:
        raise HTTPException(status_code=404, detail="organization not found")
    return _org_out(o)
