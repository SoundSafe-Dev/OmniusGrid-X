"""Workcell and Organization read endpoints (FS-18).

The web client's assetsApi.workcellsApi / organizationsApi called
/api/v1/workcells and /api/v1/organizations, which had no router. These serve
the read paths those clients need, tenant-scoped to the caller's organization.
Responses are snake_case; the client camel-cases them via transform.ts.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.pagination import MAX_OFFSET, PaginatedResponse, paginate
from app.middleware.rbac import require_admin
from app.middleware.tenant_isolation import get_tenant_org_id, get_tenant_db
from app.db.models import Workcell, Organization

workcells_router = APIRouter(dependencies=[Depends(get_current_active_user)])
organizations_router = APIRouter(dependencies=[Depends(get_current_active_user)])


# ---- Response schemas (FS-100). Same shapes _workcell_out/_org_out already emit.

class WorkcellOut(BaseModel):
    id: str
    organization_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    location: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class OrganizationOut(BaseModel):
    id: str
    name: str
    slug: Optional[str] = None
    settings: Dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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


@workcells_router.get("/", response_model=PaginatedResponse[WorkcellOut])
async def list_workcells(
    skip: int = Query(0, ge=0, le=MAX_OFFSET),
    limit: int = Query(100, ge=1, le=1000),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    # Always scoped to the caller's organization (any client-sent organization_id
    # is ignored — a user can only see their own org's workcells).
    # FS-99: returns the {items, meta} pagination envelope with a real total.
    base = select(Workcell).where(Workcell.organization_id == org_id)
    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (await db.execute(
        base.order_by(Workcell.name.asc()).offset(skip).limit(limit)
    )).scalars().all()
    return paginate([_workcell_out(w) for w in rows], total,
                    SimpleNamespace(skip=skip, limit=limit))


@workcells_router.get("/{workcell_id}", response_model=WorkcellOut)
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


@organizations_router.get("/", response_model=List[OrganizationOut])
async def list_organizations(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    # A user sees only their own organization.
    o = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    return [_org_out(o)] if o else []


@organizations_router.get("/{organization_id}", response_model=OrganizationOut)
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


# Only these keys are readable/writable through the settings endpoints — an
# open blob merge would let any caller persist arbitrary junk into the org row.
_SETTING_KEYS = {"timezone", "date_format", "notify_email", "notify_sms", "notify_webhook"}


async def _org_or_404(org_id: UUID, db: AsyncSession) -> Organization:
    o = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if o is None:
        raise HTTPException(status_code=404, detail="organization not found")
    return o


class OrgSettings(BaseModel):
    """The five allowlisted settings keys, and NOTHING IS EMITTED THAT WAS NOT STORED.

    Both routes are declared `response_model_exclude_unset=True`, which is load-bearing.
    The handlers return only the keys present in the org's settings blob; a plain model
    would fill the absent ones with `null`, and the admin Settings page does

        const current = { ...SETTING_DEFAULTS, ...settings, ...draft }

    — a spread, so an emitted `null` OVERWRITES the default rather than falling back to
    it. Declaring this naively would have blanked the Timezone field and turned three
    notification toggles from `true` to null for every organization that had never saved
    a setting. Not a dropped field this time; an INVENTED one, which the same spread
    cannot tell from a real value.
    """

    timezone: Optional[str] = None
    date_format: Optional[str] = None
    notify_email: Optional[bool] = None
    notify_sms: Optional[bool] = None
    notify_webhook: Optional[bool] = None


@organizations_router.get(
    "/settings/current",
    response_model=OrgSettings,
    response_model_exclude_unset=True,
)
async def get_org_settings(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """The caller's organization settings (admin Settings page)."""
    o = await _org_or_404(org_id, db)
    stored = o.settings or {}
    return {k: v for k, v in stored.items() if k in _SETTING_KEYS}


@organizations_router.put(
    "/settings/current",
    response_model=OrgSettings,
    response_model_exclude_unset=True,
)
async def update_org_settings(
    settings_patch: Dict[str, Any],
    current_user=Depends(require_admin),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Merge an allowlisted patch into the org settings blob (admin only)."""
    unknown = set(settings_patch) - _SETTING_KEYS
    if unknown:
        raise HTTPException(status_code=422,
                            detail=f"unknown settings keys: {sorted(unknown)}")
    o = await _org_or_404(org_id, db)
    merged = {**(o.settings or {}), **settings_patch}
    o.settings = merged
    await db.commit()
    return {k: v for k, v in merged.items() if k in _SETTING_KEYS}
