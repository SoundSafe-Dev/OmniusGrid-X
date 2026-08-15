"""Tenant-scoped fleet metadata, cohorts, inventory, and exact previews."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import conflict_response
from app.api.auth import get_current_active_user
from app.core.config import settings
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import (
    AgentRelease,
    Asset,
    AssetFleetGroup,
    AssetFleetTag,
    AssetType,
    AuditLog,
    FleetCohort,
    FleetGroup,
    FleetTag,
    FleetTargetPreview,
    Site,
    User,
    Workcell,
)
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from app.services.fleet_targeting import (
    TargetingValidationError,
    fleet_target_resolver,
    normalize_key,
    normalize_query,
    validate_query_references,
)

router = APIRouter(dependencies=[Depends(get_current_active_user)])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_name(value: str, field: str = "name") -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"{field} may not be blank")
    return cleaned


def _not_found(resource: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{resource} not found")


def _validation_error(exc: TargetingValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _reject_explicit_nulls(values: dict[str, Any], *fields: str) -> None:
    for field in fields:
        if field in values and values[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} may not be null")


def _audit(
    db: AsyncSession,
    request: Request,
    *,
    user: User,
    org_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            user_id=user.id,
            organization_id=org_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            details=details,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            # PostgreSQL's audit trigger replaces this with the chained hash.
            hash_chain="pending",
        )
    )


async def _commit_conflict(db: AsyncSession, detail: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        original = exc.orig
        cause = getattr(original, "__cause__", None)
        sqlstate = (
            getattr(original, "sqlstate", None)
            or getattr(original, "pgcode", None)
            or getattr(cause, "sqlstate", None)
            or getattr(cause, "pgcode", None)
        )
        await db.rollback()
        if sqlstate == "23505":
            raise HTTPException(status_code=409, detail=detail) from exc
        raise


class NamedFleetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    key: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=2000)


class NamedFleetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    key: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class TagCreate(NamedFleetCreate):
    color: str | None = Field(default=None, max_length=32)


class TagUpdate(NamedFleetUpdate):
    color: str | None = Field(default=None, max_length=32)


class WorkcellSiteUpdate(BaseModel):
    site_id: UUID | None


class BulkTagAssignment(BaseModel):
    tag_id: UUID
    asset_ids: list[UUID] = Field(..., min_length=1, max_length=500)
    operation: Literal["add", "remove"] = "add"


class CohortCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    query: dict[str, Any]


class CohortUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    query: dict[str, Any] | None = None
    is_active: bool | None = None


class TargetPreviewCreate(BaseModel):
    release_id: UUID
    selector: dict[str, Any]
    ttl_seconds: int | None = Field(default=None, ge=60, le=1800)


# RESPONSE MODELS, added 2026-08-08 during the merge that brought this router onto
# converged-pre-main. The router already built every shape below in its `_*_response`
# helpers — these DECLARE what it was already returning. Nothing about the wire changed.
#
# WHY IT WAS WORTH DOING RATHER THAN ALLOWING. A route with no `response_model` is
# invisible to the API contract gate, absent from the generated SDK, and a promise the
# OpenAPI schema cannot make — and this router added 27 of them at once, against a ratchet
# whose whole rule is that it only goes down. Raising the allowance would have been one
# line and would have widened a gate to fit a merge.


class SiteResponse(BaseModel):
    id: str
    key: str
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TagResponse(SiteResponse):
    color: Optional[str] = None


class GroupResponse(SiteResponse):
    pass


class CohortResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    query_version: Optional[int] = None
    query: Optional[dict[str, Any]] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TargetPreviewResponse(BaseModel):
    id: str
    release_id: str
    selector: Optional[dict[str, Any]] = None
    asset_ids: list[str] = []
    agents: list[Any] = []
    excluded_assets: list[Any] = []
    warnings: list[Any] = []
    membership_hash: Optional[str] = None
    asset_count: int
    agent_count: int
    created_by: str
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    #: Derived, not stored. A preview whose window has closed still answers, and a caller
    #: that cannot tell reuses a membership set that no longer reflects the fleet.
    expired: bool


class WorkcellSiteResponse(BaseModel):
    """A workcell as this router reports it — id, name, and the site it belongs to."""

    id: str
    name: Optional[str] = None
    site_id: Optional[str] = None
    site_key: Optional[str] = None


class AssetTagAssignmentResponse(BaseModel):
    """Attaching or detaching one asset.

    `created` and `removed` are what the handlers actually return — whether the call CHANGED
    anything, not whether the asset is now attached. Re-attaching an asset that is already
    tagged answers `created: false`, and that distinction is the reason the field exists.
    An earlier draft of this model declared `assigned` instead and would have deleted both.
    """

    asset_id: str
    tag_id: Optional[str] = None
    group_id: Optional[str] = None
    created: Optional[bool] = None
    removed: Optional[bool] = None


class BulkTagAssignmentResponse(BaseModel):
    """One bulk attach/detach. `changed_count` is the rows that MOVED, which is not the
    number requested — asking to tag forty assets when thirty already carry it changes ten."""

    tag_id: str
    operation: str
    changed_count: int
    results: list[Any] = []


class FleetInventoryResponse(BaseModel):
    """The targeting inventory: every asset with the sites, tags and groups it belongs to.
    A per-asset roll-up, not four parallel lists — which is what the first draft assumed."""

    assets: list[Any] = []


class DeactivatedResponse(BaseModel):
    """A soft delete. The id is echoed because these routes deactivate rather than remove,
    and a caller that assumed removal would otherwise have no way to tell."""

    id: str
    is_active: bool = False


def _site_response(site: Site) -> dict[str, Any]:
    return {
        "id": str(site.id),
        "key": site.key,
        "name": site.name,
        "description": site.description,
        "is_active": site.is_active,
        "created_at": site.created_at,
        "updated_at": site.updated_at,
    }


def _tag_response(tag: FleetTag) -> dict[str, Any]:
    return {
        "id": str(tag.id),
        "key": tag.key,
        "name": tag.name,
        "description": tag.description,
        "color": tag.color,
        "is_active": tag.is_active,
        "created_at": tag.created_at,
        "updated_at": tag.updated_at,
    }


def _group_response(group: FleetGroup) -> dict[str, Any]:
    return {
        "id": str(group.id),
        "key": group.key,
        "name": group.name,
        "description": group.description,
        "is_active": group.is_active,
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def _cohort_response(cohort: FleetCohort) -> dict[str, Any]:
    return {
        "id": str(cohort.id),
        "name": cohort.name,
        "description": cohort.description,
        "query_version": cohort.query_version,
        "query": cohort.query,
        "is_active": cohort.is_active,
        "created_at": cohort.created_at,
        "updated_at": cohort.updated_at,
    }


def _preview_response(preview: FleetTargetPreview) -> dict[str, Any]:
    return {
        "id": str(preview.id),
        "release_id": str(preview.release_id),
        "selector": preview.selector,
        "asset_ids": preview.ordered_asset_ids,
        "agents": preview.resolved_agents,
        "excluded_assets": preview.excluded_assets,
        "warnings": preview.warnings,
        "membership_hash": preview.membership_hash,
        "asset_count": preview.asset_count,
        "agent_count": preview.agent_count,
        "created_by": str(preview.created_by),
        "expires_at": preview.expires_at,
        "created_at": preview.created_at,
        "expired": preview.expires_at <= _utcnow(),
    }


async def _tenant_asset(asset_id: UUID, org_id: UUID, db: AsyncSession) -> Asset:
    asset = (
        await db.execute(
            select(Asset).where(
                Asset.id == asset_id,
                Asset.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise _not_found("Asset")
    return asset


@router.get("/sites", response_model=List[SiteResponse])
@rate_limit("100/minute")
async def list_sites(
    request: Request,
    include_inactive: bool = False,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = select(Site).where(Site.organization_id == org_id)
    if not include_inactive:
        query = query.where(Site.is_active.is_(True))
    sites = (await db.execute(query.order_by(Site.name, Site.id))).scalars().all()
    return [_site_response(site) for site in sites]


@router.post(
    "/sites",
    response_model=SiteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    responses={**conflict_response},
)
@rate_limit("30/minute")
async def create_site(
    request: Request,
    payload: NamedFleetCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    name = _clean_name(payload.name)
    try:
        key = normalize_key(payload.key or name)
    except TargetingValidationError as exc:
        raise _validation_error(exc) from exc
    site = Site(
        id=uuid4(),
        organization_id=org_id,
        key=key,
        name=name,
        description=payload.description,
        created_by=current_user.id,
    )
    db.add(site)
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_site_created",
        resource_type="site",
        resource_id=str(site.id),
        details={"key": key, "name": name},
    )
    await _commit_conflict(db, "A site with that key or name already exists")
    return _site_response(site)


@router.patch("/sites/{site_id}", response_model=SiteResponse, dependencies=[Depends(require_admin)], responses={**conflict_response})
@rate_limit("30/minute")
async def update_site(
    request: Request,
    site_id: UUID,
    payload: NamedFleetUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    site = (
        await db.execute(
            select(Site).where(Site.id == site_id, Site.organization_id == org_id)
        )
    ).scalar_one_or_none()
    if site is None:
        raise _not_found("Site")
    before = _site_response(site)
    values = payload.model_dump(exclude_unset=True)
    _reject_explicit_nulls(values, "name", "key", "is_active")
    if "name" in values:
        values["name"] = _clean_name(values["name"])
    if "key" in values:
        try:
            values["key"] = normalize_key(values["key"])
        except TargetingValidationError as exc:
            raise _validation_error(exc) from exc
    for key, value in values.items():
        setattr(site, key, value)
    site.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_site_updated",
        resource_type="site",
        resource_id=str(site.id),
        details={
            "before": {
                "key": before["key"],
                "name": before["name"],
                "description": before["description"],
                "is_active": before["is_active"],
            },
            "after": {
                "key": site.key,
                "name": site.name,
                "description": site.description,
                "is_active": site.is_active,
            },
        },
    )
    await _commit_conflict(db, "A site with that key or name already exists")
    return _site_response(site)


@router.delete("/sites/{site_id}", response_model=SiteResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/minute")
async def deactivate_site(
    request: Request,
    site_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    site = (
        await db.execute(
            select(Site).where(Site.id == site_id, Site.organization_id == org_id)
        )
    ).scalar_one_or_none()
    if site is None:
        raise _not_found("Site")
    site.is_active = False
    site.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_site_deactivated",
        resource_type="site",
        resource_id=str(site.id),
        details={"name": site.name},
    )
    await db.commit()
    return _site_response(site)


@router.get("/workcells", response_model=List[WorkcellSiteResponse])
@rate_limit("100/minute")
async def list_workcells(
    request: Request,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rows = (
        await db.execute(
            select(Workcell, Site)
            .outerjoin(
                Site,
                and_(
                    Site.id == Workcell.site_id,
                    Site.organization_id == Workcell.organization_id,
                ),
            )
            .where(Workcell.organization_id == org_id)
            .order_by(Workcell.name, Workcell.id)
        )
    ).all()
    return [
        {
            "id": str(workcell.id),
            "name": workcell.name,
            "description": workcell.description,
            "location": workcell.location,
            "site_id": str(site.id) if site else None,
            "site_name": site.name if site else None,
        }
        for workcell, site in rows
    ]


@router.patch(
    "/workcells/{workcell_id}/site",
    response_model=WorkcellSiteResponse,
    dependencies=[Depends(require_admin)],
)
@rate_limit("30/minute")
async def assign_workcell_site(
    request: Request,
    workcell_id: UUID,
    payload: WorkcellSiteUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    workcell = (
        await db.execute(
            select(Workcell).where(
                Workcell.id == workcell_id,
                Workcell.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if workcell is None:
        raise _not_found("Workcell")
    if payload.site_id is not None:
        site = (
            await db.execute(
                select(Site).where(
                    Site.id == payload.site_id,
                    Site.organization_id == org_id,
                    Site.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if site is None:
            raise _not_found("Site")
    previous_site_id = workcell.site_id
    workcell.site_id = payload.site_id
    workcell.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_workcell_site_assigned",
        resource_type="workcell",
        resource_id=str(workcell.id),
        details={
            "previous_site_id": str(previous_site_id) if previous_site_id else None,
            "site_id": str(payload.site_id) if payload.site_id else None,
        },
    )
    await db.commit()
    return {
        "id": str(workcell.id),
        "name": workcell.name,
        "site_id": str(workcell.site_id) if workcell.site_id else None,
    }


@router.get("/tags", response_model=List[TagResponse])
@rate_limit("100/minute")
async def list_tags(
    request: Request,
    include_inactive: bool = False,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = select(FleetTag).where(FleetTag.organization_id == org_id)
    if not include_inactive:
        query = query.where(FleetTag.is_active.is_(True))
    tags = (await db.execute(query.order_by(FleetTag.name, FleetTag.id))).scalars().all()
    return [_tag_response(tag) for tag in tags]


@router.post(
    "/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    responses={**conflict_response},
)
@rate_limit("30/minute")
async def create_tag(
    request: Request,
    payload: TagCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    name = _clean_name(payload.name)
    try:
        key = normalize_key(payload.key or name)
    except TargetingValidationError as exc:
        raise _validation_error(exc) from exc
    tag = FleetTag(
        id=uuid4(),
        organization_id=org_id,
        key=key,
        name=name,
        description=payload.description,
        color=payload.color,
        created_by=current_user.id,
    )
    db.add(tag)
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_tag_created",
        resource_type="fleet_tag",
        resource_id=str(tag.id),
        details={"key": key, "name": name},
    )
    await _commit_conflict(db, "A tag with that key or name already exists")
    return _tag_response(tag)


@router.patch("/tags/{tag_id}", response_model=TagResponse, dependencies=[Depends(require_admin)], responses={**conflict_response})
@rate_limit("30/minute")
async def update_tag(
    request: Request,
    tag_id: UUID,
    payload: TagUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    tag = (
        await db.execute(
            select(FleetTag).where(
                FleetTag.id == tag_id,
                FleetTag.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if tag is None:
        raise _not_found("Tag")
    before = _tag_response(tag)
    values = payload.model_dump(exclude_unset=True)
    _reject_explicit_nulls(values, "name", "key", "is_active")
    if "name" in values:
        values["name"] = _clean_name(values["name"])
    if "key" in values:
        try:
            values["key"] = normalize_key(values["key"])
        except TargetingValidationError as exc:
            raise _validation_error(exc) from exc
    for key, value in values.items():
        setattr(tag, key, value)
    tag.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_tag_updated",
        resource_type="fleet_tag",
        resource_id=str(tag.id),
        details={
            "before": {
                "key": before["key"],
                "name": before["name"],
                "description": before["description"],
                "color": before["color"],
                "is_active": before["is_active"],
            },
            "after": {
                "key": tag.key,
                "name": tag.name,
                "description": tag.description,
                "color": tag.color,
                "is_active": tag.is_active,
            },
        },
    )
    await _commit_conflict(db, "A tag with that key or name already exists")
    return _tag_response(tag)


@router.delete("/tags/{tag_id}", response_model=TagResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/minute")
async def deactivate_tag(
    request: Request,
    tag_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    tag = (
        await db.execute(
            select(FleetTag).where(
                FleetTag.id == tag_id,
                FleetTag.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if tag is None:
        raise _not_found("Tag")
    tag.is_active = False
    tag.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_tag_deactivated",
        resource_type="fleet_tag",
        resource_id=str(tag.id),
        details={"name": tag.name},
    )
    await db.commit()
    return _tag_response(tag)


@router.put(
    "/tags/{tag_id}/assets/{asset_id}",
    response_model=AssetTagAssignmentResponse,
    dependencies=[Depends(require_admin)],
)
@rate_limit("60/minute")
async def assign_tag(
    request: Request,
    tag_id: UUID,
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    tag = (
        await db.execute(
            select(FleetTag).where(
                FleetTag.id == tag_id,
                FleetTag.organization_id == org_id,
                FleetTag.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if tag is None:
        raise _not_found("Tag")
    await _tenant_asset(asset_id, org_id, db)
    created = (
        await db.execute(
            pg_insert(AssetFleetTag)
            .values(
                organization_id=org_id,
                asset_id=asset_id,
                tag_id=tag_id,
                assigned_by=current_user.id,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    AssetFleetTag.asset_id,
                    AssetFleetTag.tag_id,
                ]
            )
            .returning(AssetFleetTag.asset_id)
        )
    ).scalar_one_or_none() is not None
    if created:
        _audit(
            db,
            request,
            user=current_user,
            org_id=org_id,
            action="fleet_tag_assigned",
            resource_type="asset",
            resource_id=str(asset_id),
            details={"tag_id": str(tag_id)},
        )
    await db.commit()
    return {"asset_id": str(asset_id), "tag_id": str(tag_id), "created": created}


@router.delete(
    "/tags/{tag_id}/assets/{asset_id}",
    response_model=AssetTagAssignmentResponse,
    dependencies=[Depends(require_admin)],
)
@rate_limit("60/minute")
async def remove_tag(
    request: Request,
    tag_id: UUID,
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    await _tenant_asset(asset_id, org_id, db)
    tag = (
        await db.execute(
            select(FleetTag).where(
                FleetTag.id == tag_id,
                FleetTag.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if tag is None:
        raise _not_found("Tag")
    removed = (
        await db.execute(
            delete(AssetFleetTag)
            .where(
                AssetFleetTag.organization_id == org_id,
                AssetFleetTag.asset_id == asset_id,
                AssetFleetTag.tag_id == tag_id,
            )
            .returning(AssetFleetTag.asset_id)
        )
    ).scalar_one_or_none() is not None
    if removed:
        _audit(
            db,
            request,
            user=current_user,
            org_id=org_id,
            action="fleet_tag_removed",
            resource_type="asset",
            resource_id=str(asset_id),
            details={"tag_id": str(tag_id)},
        )
    await db.commit()
    return {"asset_id": str(asset_id), "tag_id": str(tag_id), "removed": removed}


@router.post("/tags/bulk-assignments", response_model=BulkTagAssignmentResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/minute")
async def bulk_tag_assignments(
    request: Request,
    payload: BulkTagAssignment,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    tag = (
        await db.execute(
            select(FleetTag).where(
                FleetTag.id == payload.tag_id,
                FleetTag.organization_id == org_id,
                FleetTag.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if tag is None:
        raise _not_found("Tag")
    requested = list(dict.fromkeys(payload.asset_ids))
    owned = {
        str(asset_id)
        for asset_id in (
            (
                await db.execute(
                    select(Asset.id).where(
                        Asset.organization_id == org_id,
                        Asset.id.in_(requested),
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    changed_set: set[str]
    if payload.operation == "add":
        rows = [
            {
                "organization_id": org_id,
                "asset_id": asset_id,
                "tag_id": payload.tag_id,
                "assigned_by": current_user.id,
            }
            for asset_id in requested
            if str(asset_id) in owned
        ]
        changed_set = (
            {
                str(asset_id)
                for asset_id in
                (
                    await db.execute(
                        pg_insert(AssetFleetTag)
                        .values(rows)
                        .on_conflict_do_nothing(
                            index_elements=[
                                AssetFleetTag.asset_id,
                                AssetFleetTag.tag_id,
                            ]
                        )
                        .returning(AssetFleetTag.asset_id)
                    )
                )
                .scalars()
                .all()
            }
            if rows
            else set()
        )
    else:
        changed_set = {
            str(asset_id)
            for asset_id in
            (
                await db.execute(
                    delete(AssetFleetTag)
                    .where(
                        AssetFleetTag.organization_id == org_id,
                        AssetFleetTag.tag_id == payload.tag_id,
                        AssetFleetTag.asset_id.in_(owned),
                    )
                    .returning(AssetFleetTag.asset_id)
                )
            )
            .scalars()
            .all()
        }
    results: list[dict[str, Any]] = []
    for asset_id in requested:
        canonical_asset_id = str(asset_id)
        if canonical_asset_id not in owned:
            results.append(
                {
                    "asset_id": canonical_asset_id,
                    "status": "error",
                    "error": "asset_unavailable",
                }
            )
            continue
        if canonical_asset_id not in changed_set:
            results.append({"asset_id": canonical_asset_id, "status": "unchanged"})
        else:
            results.append(
                {
                    "asset_id": canonical_asset_id,
                    "status": "added" if payload.operation == "add" else "removed",
                }
            )

    changed = [
        asset_id for asset_id in requested if str(asset_id) in changed_set
    ]
    if changed:
        _audit(
            db,
            request,
            user=current_user,
            org_id=org_id,
            action=f"fleet_tag_bulk_{payload.operation}",
            resource_type="fleet_tag",
            resource_id=str(payload.tag_id),
            details={
                "asset_ids": [str(asset_id) for asset_id in changed],
                "changed_count": len(changed),
            },
        )
    await db.commit()
    return {
        "tag_id": str(payload.tag_id),
        "operation": payload.operation,
        "changed_count": len(changed),
        "results": results,
    }


@router.get("/groups", response_model=List[GroupResponse])
@rate_limit("100/minute")
async def list_groups(
    request: Request,
    include_inactive: bool = False,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = select(FleetGroup).where(FleetGroup.organization_id == org_id)
    if not include_inactive:
        query = query.where(FleetGroup.is_active.is_(True))
    groups = (await db.execute(query.order_by(FleetGroup.name, FleetGroup.id))).scalars().all()
    return [_group_response(group) for group in groups]


@router.post(
    "/groups",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    responses={**conflict_response},
)
@rate_limit("30/minute")
async def create_group(
    request: Request,
    payload: NamedFleetCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    name = _clean_name(payload.name)
    try:
        key = normalize_key(payload.key or name)
    except TargetingValidationError as exc:
        raise _validation_error(exc) from exc
    group = FleetGroup(
        id=uuid4(),
        organization_id=org_id,
        key=key,
        name=name,
        description=payload.description,
        created_by=current_user.id,
    )
    db.add(group)
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_group_created",
        resource_type="fleet_group",
        resource_id=str(group.id),
        details={"key": key, "name": name},
    )
    await _commit_conflict(db, "A group with that key or name already exists")
    return _group_response(group)


@router.patch("/groups/{group_id}", response_model=GroupResponse, dependencies=[Depends(require_admin)], responses={**conflict_response})
@rate_limit("30/minute")
async def update_group(
    request: Request,
    group_id: UUID,
    payload: NamedFleetUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    group = (
        await db.execute(
            select(FleetGroup).where(
                FleetGroup.id == group_id,
                FleetGroup.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise _not_found("Group")
    before = _group_response(group)
    values = payload.model_dump(exclude_unset=True)
    _reject_explicit_nulls(values, "name", "key", "is_active")
    if "name" in values:
        values["name"] = _clean_name(values["name"])
    if "key" in values:
        try:
            values["key"] = normalize_key(values["key"])
        except TargetingValidationError as exc:
            raise _validation_error(exc) from exc
    for key, value in values.items():
        setattr(group, key, value)
    group.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_group_updated",
        resource_type="fleet_group",
        resource_id=str(group.id),
        details={
            "before": {
                "key": before["key"],
                "name": before["name"],
                "description": before["description"],
                "is_active": before["is_active"],
            },
            "after": {
                "key": group.key,
                "name": group.name,
                "description": group.description,
                "is_active": group.is_active,
            },
        },
    )
    await _commit_conflict(db, "A group with that key or name already exists")
    return _group_response(group)


@router.delete("/groups/{group_id}", response_model=GroupResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/minute")
async def deactivate_group(
    request: Request,
    group_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    group = (
        await db.execute(
            select(FleetGroup).where(
                FleetGroup.id == group_id,
                FleetGroup.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise _not_found("Group")
    group.is_active = False
    group.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_group_deactivated",
        resource_type="fleet_group",
        resource_id=str(group.id),
        details={"name": group.name},
    )
    await db.commit()
    return _group_response(group)


@router.put(
    "/groups/{group_id}/assets/{asset_id}",
    response_model=AssetTagAssignmentResponse,
    dependencies=[Depends(require_admin)],
)
@rate_limit("60/minute")
async def assign_group_member(
    request: Request,
    group_id: UUID,
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    group = (
        await db.execute(
            select(FleetGroup).where(
                FleetGroup.id == group_id,
                FleetGroup.organization_id == org_id,
                FleetGroup.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise _not_found("Group")
    await _tenant_asset(asset_id, org_id, db)
    created = (
        await db.execute(
            pg_insert(AssetFleetGroup)
            .values(
                organization_id=org_id,
                asset_id=asset_id,
                group_id=group_id,
                assigned_by=current_user.id,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    AssetFleetGroup.asset_id,
                    AssetFleetGroup.group_id,
                ]
            )
            .returning(AssetFleetGroup.asset_id)
        )
    ).scalar_one_or_none() is not None
    if created:
        _audit(
            db,
            request,
            user=current_user,
            org_id=org_id,
            action="fleet_group_member_added",
            resource_type="asset",
            resource_id=str(asset_id),
            details={"group_id": str(group_id)},
        )
    await db.commit()
    return {"asset_id": str(asset_id), "group_id": str(group_id), "created": created}


@router.delete(
    "/groups/{group_id}/assets/{asset_id}",
    response_model=AssetTagAssignmentResponse,
    dependencies=[Depends(require_admin)],
)
@rate_limit("60/minute")
async def remove_group_member(
    request: Request,
    group_id: UUID,
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    await _tenant_asset(asset_id, org_id, db)
    group = (
        await db.execute(
            select(FleetGroup).where(
                FleetGroup.id == group_id,
                FleetGroup.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise _not_found("Group")
    removed = (
        await db.execute(
            delete(AssetFleetGroup)
            .where(
                AssetFleetGroup.organization_id == org_id,
                AssetFleetGroup.asset_id == asset_id,
                AssetFleetGroup.group_id == group_id,
            )
            .returning(AssetFleetGroup.asset_id)
        )
    ).scalar_one_or_none() is not None
    if removed:
        _audit(
            db,
            request,
            user=current_user,
            org_id=org_id,
            action="fleet_group_member_removed",
            resource_type="asset",
            resource_id=str(asset_id),
            details={"group_id": str(group_id)},
        )
    await db.commit()
    return {"asset_id": str(asset_id), "group_id": str(group_id), "removed": removed}


@router.get("/cohorts", response_model=List[CohortResponse])
@rate_limit("100/minute")
async def list_cohorts(
    request: Request,
    include_inactive: bool = False,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = select(FleetCohort).where(FleetCohort.organization_id == org_id)
    if not include_inactive:
        query = query.where(FleetCohort.is_active.is_(True))
    cohorts = (await db.execute(query.order_by(FleetCohort.name, FleetCohort.id))).scalars().all()
    return [_cohort_response(cohort) for cohort in cohorts]


@router.get("/cohorts/{cohort_id}", response_model=CohortResponse)
@rate_limit("100/minute")
async def get_cohort(
    request: Request,
    cohort_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    cohort = (
        await db.execute(
            select(FleetCohort).where(
                FleetCohort.id == cohort_id,
                FleetCohort.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if cohort is None:
        raise _not_found("Cohort")
    return _cohort_response(cohort)


@router.post(
    "/cohorts",
    response_model=CohortResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    responses={**conflict_response},
)
@rate_limit("30/minute")
async def create_cohort(
    request: Request,
    payload: CohortCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    try:
        query = normalize_query(payload.query)
        await validate_query_references(query, org_id, db)
    except TargetingValidationError as exc:
        raise _validation_error(exc) from exc
    cohort = FleetCohort(
        id=uuid4(),
        organization_id=org_id,
        name=_clean_name(payload.name),
        description=payload.description,
        query_version=1,
        query=query,
        created_by=current_user.id,
    )
    db.add(cohort)
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_cohort_created",
        resource_type="fleet_cohort",
        resource_id=str(cohort.id),
        details={"name": cohort.name, "query_version": 1},
    )
    await _commit_conflict(db, "A cohort with that name already exists")
    return _cohort_response(cohort)


@router.patch("/cohorts/{cohort_id}", response_model=CohortResponse, dependencies=[Depends(require_admin)], responses={**conflict_response})
@rate_limit("30/minute")
async def update_cohort(
    request: Request,
    cohort_id: UUID,
    payload: CohortUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    cohort = (
        await db.execute(
            select(FleetCohort).where(
                FleetCohort.id == cohort_id,
                FleetCohort.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if cohort is None:
        raise _not_found("Cohort")
    before = _cohort_response(cohort)
    values = payload.model_dump(exclude_unset=True)
    _reject_explicit_nulls(values, "name", "query", "is_active")
    if "name" in values:
        values["name"] = _clean_name(values["name"])
    if "query" in values:
        try:
            values["query"] = normalize_query(values["query"])
            await validate_query_references(values["query"], org_id, db)
        except TargetingValidationError as exc:
            raise _validation_error(exc) from exc
    for key, value in values.items():
        setattr(cohort, key, value)
    cohort.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_cohort_updated",
        resource_type="fleet_cohort",
        resource_id=str(cohort.id),
        details={
            "before": {
                "name": before["name"],
                "query": before["query"],
                "is_active": before["is_active"],
            },
            "after": {
                "name": cohort.name,
                "query": cohort.query,
                "is_active": cohort.is_active,
            },
        },
    )
    await _commit_conflict(db, "A cohort with that name already exists")
    return _cohort_response(cohort)


@router.delete("/cohorts/{cohort_id}", response_model=CohortResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/minute")
async def deactivate_cohort(
    request: Request,
    cohort_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    cohort = (
        await db.execute(
            select(FleetCohort).where(
                FleetCohort.id == cohort_id,
                FleetCohort.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if cohort is None:
        raise _not_found("Cohort")
    cohort.is_active = False
    cohort.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_cohort_deactivated",
        resource_type="fleet_cohort",
        resource_id=str(cohort.id),
        details={"name": cohort.name},
    )
    await db.commit()
    return _cohort_response(cohort)


@router.get("/inventory", response_model=FleetInventoryResponse)
@rate_limit("100/minute")
async def fleet_inventory(
    request: Request,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rows = (
        await db.execute(
            select(Asset, Workcell, Site, AssetType)
            .join(Workcell, Workcell.id == Asset.workcell_id)
            .outerjoin(Site, Site.id == Workcell.site_id)
            .join(AssetType, AssetType.id == Asset.asset_type_id)
            .where(Asset.organization_id == org_id)
            .order_by(Asset.name, Asset.id)
        )
    ).all()
    asset_ids = [asset.id for asset, _, _, _ in rows]
    tags = await fleet_target_resolver._tag_context(db, org_id, asset_ids)
    groups = await fleet_target_resolver._group_context(db, org_id, asset_ids)
    collectors = await fleet_target_resolver._collector_context(db, org_id, asset_ids)
    return {
        "assets": [
            {
                "id": str(asset.id),
                "name": asset.name,
                "is_active": asset.is_active,
                "agent_id": asset.agent_id,
                "agent_version": asset.agent_version,
                "last_heartbeat": asset.agent_last_heartbeat,
                "workcell_id": str(workcell.id),
                "workcell_name": workcell.name,
                "site_id": str(site.id) if site else None,
                "site_name": site.name if site else None,
                "asset_type_id": str(asset_type.id),
                "asset_type_name": asset_type.name,
                "asset_category": asset_type.category,
                "collector_types": collectors.get(str(asset.id), []),
                "tags": tags.get(str(asset.id), []),
                "groups": groups.get(str(asset.id), []),
            }
            for asset, workcell, site, asset_type in rows
        ]
    }


@router.post(
    "/target-previews",
    response_model=TargetPreviewResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
@rate_limit("60/hour")
async def create_target_preview(
    request: Request,
    payload: TargetPreviewCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    release = (
        await db.execute(
            select(AgentRelease).where(
                AgentRelease.id == payload.release_id,
                AgentRelease.organization_id == org_id,
                AgentRelease.status == "published",
            )
        )
    ).scalar_one_or_none()
    if release is None:
        raise _not_found("Published release")
    try:
        resolution = await fleet_target_resolver.resolve(
            selector=payload.selector,
            organization_id=org_id,
            release=release,
            db=db,
        )
    except TargetingValidationError as exc:
        raise _validation_error(exc) from exc
    ttl = payload.ttl_seconds or settings.FLEET_TARGET_PREVIEW_TTL_SECONDS
    ttl = min(max(int(ttl), 60), 1800)
    preview = FleetTargetPreview(
        id=uuid4(),
        organization_id=org_id,
        release_id=release.id,
        selector=resolution.selector,
        ordered_asset_ids=resolution.asset_ids,
        resolved_agents=resolution.agents,
        excluded_assets=resolution.excluded_assets,
        warnings=resolution.warnings,
        membership_hash=resolution.membership_hash,
        asset_count=len(resolution.assets),
        agent_count=len(resolution.agents),
        created_by=current_user.id,
        expires_at=_utcnow() + timedelta(seconds=ttl),
    )
    db.add(preview)
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="fleet_target_preview_created",
        resource_type="fleet_target_preview",
        resource_id=str(preview.id),
        details={
            "release_id": str(release.id),
            "asset_count": preview.asset_count,
            "agent_count": preview.agent_count,
            "membership_hash": preview.membership_hash,
        },
    )
    await db.commit()
    return _preview_response(preview)


@router.get("/target-previews/{preview_id}", response_model=TargetPreviewResponse)
@rate_limit("100/minute")
async def get_target_preview(
    request: Request,
    preview_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    preview = (
        await db.execute(
            select(FleetTargetPreview).where(
                FleetTargetPreview.id == preview_id,
                FleetTargetPreview.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if preview is None:
        raise _not_found("Target preview")
    return _preview_response(preview)
