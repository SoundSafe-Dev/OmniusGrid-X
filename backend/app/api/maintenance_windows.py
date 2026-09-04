"""Tenant-scoped recurring maintenance-window management."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.core.pagination import MAX_OFFSET, mark_truncated
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import conflict_response
from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import AuditLog, MaintenanceWindow, Site, User
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from app.services.maintenance_windows import (
    MaintenanceWindowValidationError,
    effective_scope_label,
    evaluate_group_windows,
    utc_datetime,
    validate_local_times,
    validate_timezone_name,
    validate_weekdays,
)


router = APIRouter(dependencies=[Depends(get_current_active_user)])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MaintenanceWindowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    site_id: UUID | None = None
    timezone: str = Field(..., min_length=1, max_length=100)
    weekdays: list[int] = Field(..., min_length=1, max_length=7)
    local_start_time: time
    local_end_time: time
    enabled: bool = True


class MaintenanceWindowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    site_id: UUID | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    weekdays: list[int] | None = Field(default=None, min_length=1, max_length=7)
    local_start_time: time | None = None
    local_end_time: time | None = None
    enabled: bool | None = None


class MaintenanceWindowResponse(BaseModel):
    id: UUID
    organization_id: UUID
    site_id: UUID | None
    site_name: str | None
    name: str
    timezone: str
    weekdays: list[int]
    local_start_time: time
    local_end_time: time
    overnight: bool
    enabled: bool
    created_by: UUID | None
    created_at: datetime | None
    updated_at: datetime | None


class MaintenanceWindowPreviewRequest(BaseModel):
    site_ids: list[UUID | None] = Field(
        default_factory=lambda: [None],
        min_length=1,
        max_length=20,
    )
    at: datetime | None = None
    horizon_days: int = Field(default=15, ge=1, le=31)


class MaintenanceWindowOccurrenceResponse(BaseModel):
    start_at: datetime
    end_at: datetime


class MaintenanceWindowPreviewResponse(BaseModel):
    at: datetime
    site_ids: list[UUID | None]
    is_open: bool
    next_eligible_at: datetime | None
    current_closes_at: datetime | None
    missing_scopes: list[str]
    effective_window_ids: list[UUID]
    occurrences: list[MaintenanceWindowOccurrenceResponse]


def _window_response(
    window: MaintenanceWindow,
    *,
    site_name: str | None = None,
) -> MaintenanceWindowResponse:
    return MaintenanceWindowResponse(
        id=window.id,
        organization_id=window.organization_id,
        site_id=window.site_id,
        site_name=site_name,
        name=window.name,
        timezone=window.timezone,
        weekdays=list(window.weekdays or []),
        local_start_time=window.local_start_time,
        local_end_time=window.local_end_time,
        overnight=window.local_end_time < window.local_start_time,
        enabled=bool(window.enabled),
        created_by=window.created_by,
        created_at=window.created_at,
        updated_at=window.updated_at,
    )


def _audit(
    db: AsyncSession,
    request: Request,
    *,
    user: User,
    org_id: UUID,
    action: str,
    window_id: UUID,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            user_id=user.id,
            organization_id=org_id,
            action=action,
            resource_type="maintenance_window",
            resource_id=str(window_id),
            details=details,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            hash_chain="pending",
        )
    )


async def _commit_conflict(db: AsyncSession) -> None:
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
            raise HTTPException(
                status_code=409,
                detail="A maintenance window with that name already exists",
            ) from exc
        raise


async def _tenant_site(
    site_id: UUID,
    org_id: UUID,
    db: AsyncSession,
    *,
    require_active: bool,
) -> Site:
    query = select(Site).where(
        Site.id == site_id,
        Site.organization_id == org_id,
    )
    if require_active:
        query = query.where(Site.is_active.is_(True))
    site = (await db.execute(query)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


async def _tenant_window(
    window_id: UUID,
    org_id: UUID,
    db: AsyncSession,
    *,
    lock: bool = False,
) -> MaintenanceWindow:
    query = select(MaintenanceWindow).where(
        MaintenanceWindow.id == window_id,
        MaintenanceWindow.organization_id == org_id,
    )
    if lock:
        query = query.with_for_update()
    window = (await db.execute(query)).scalar_one_or_none()
    if window is None:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    return window


def _validated_recurrence(
    *,
    timezone_name: str,
    weekdays: list[int],
    local_start_time: time,
    local_end_time: time,
) -> tuple[str, list[int], time, time]:
    try:
        normalized_timezone = validate_timezone_name(timezone_name)
        normalized_weekdays = validate_weekdays(weekdays)
        start_time, end_time = validate_local_times(
            local_start_time,
            local_end_time,
        )
    except MaintenanceWindowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return normalized_timezone, normalized_weekdays, start_time, end_time


@router.get(
    "/maintenance-windows",
    response_model=list[MaintenanceWindowResponse],
)
@rate_limit("100/minute")
async def list_maintenance_windows(
    request: Request,
    response: Response,
    include_disabled: bool = False,
    site_id: UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = (
        select(MaintenanceWindow, Site.name)
        .outerjoin(
            Site,
            (Site.id == MaintenanceWindow.site_id)
            & (Site.organization_id == MaintenanceWindow.organization_id),
        )
        .where(MaintenanceWindow.organization_id == org_id)
    )
    if not include_disabled:
        query = query.where(MaintenanceWindow.enabled.is_(True))
    if site_id is not None:
        await _tenant_site(site_id, org_id, db, require_active=False)
        query = query.where(MaintenanceWindow.site_id == site_id)
    rows = (
        await db.execute(
            query.order_by(
                MaintenanceWindow.site_id.nullsfirst(),
                MaintenanceWindow.name,
                MaintenanceWindow.id,
            )
            .offset(offset)
            .limit(limit + 1)
        )
    ).all()
    rows = mark_truncated(response, rows, limit)
    return [
        _window_response(window, site_name=site_name)
        for window, site_name in rows
    ]


@router.post(
    "/maintenance-windows/preview",
    response_model=MaintenanceWindowPreviewResponse,
    dependencies=[Depends(require_admin)],
)
@rate_limit("100/minute")
async def preview_maintenance_windows(
    request: Request,
    payload: MaintenanceWindowPreviewRequest,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    unique_site_ids = sorted(
        set(payload.site_ids),
        key=lambda value: "" if value is None else str(value),
    )
    for site_id in unique_site_ids:
        if site_id is not None:
            await _tenant_site(site_id, org_id, db, require_active=False)
    windows = list(
        (
            await db.execute(
                select(MaintenanceWindow).where(
                    MaintenanceWindow.organization_id == org_id,
                    MaintenanceWindow.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    try:
        at = utc_datetime(payload.at or _utcnow())
        eligibility = evaluate_group_windows(
            windows,
            unique_site_ids,
            at=at,
            horizon_days=payload.horizon_days,
        )
    except MaintenanceWindowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MaintenanceWindowPreviewResponse(
        at=at,
        site_ids=unique_site_ids,
        is_open=eligibility.is_open,
        next_eligible_at=eligibility.next_eligible_at,
        current_closes_at=eligibility.current_closes_at,
        missing_scopes=[
            effective_scope_label(site_id)
            for site_id in eligibility.missing_site_ids
        ],
        effective_window_ids=list(eligibility.effective_window_ids),
        occurrences=[
            MaintenanceWindowOccurrenceResponse(
                start_at=occurrence.start_at,
                end_at=occurrence.end_at,
            )
            for occurrence in eligibility.occurrences
        ],
    )


@router.post(
    "/maintenance-windows",
    response_model=MaintenanceWindowResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    responses={**conflict_response},
)
@rate_limit("30/minute")
async def create_maintenance_window(
    request: Request,
    payload: MaintenanceWindowCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name may not be blank")
    if payload.site_id is not None:
        await _tenant_site(payload.site_id, org_id, db, require_active=True)
    normalized_timezone, weekdays, start_time, end_time = _validated_recurrence(
        timezone_name=payload.timezone,
        weekdays=payload.weekdays,
        local_start_time=payload.local_start_time,
        local_end_time=payload.local_end_time,
    )
    window = MaintenanceWindow(
        id=uuid4(),
        organization_id=org_id,
        site_id=payload.site_id,
        name=name,
        timezone=normalized_timezone,
        weekdays=weekdays,
        local_start_time=start_time,
        local_end_time=end_time,
        enabled=payload.enabled,
        created_by=current_user.id,
    )
    db.add(window)
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="maintenance_window_created",
        window_id=window.id,
        details={
            "name": name,
            "site_id": str(payload.site_id) if payload.site_id else None,
            "timezone": normalized_timezone,
            "weekdays": weekdays,
            "local_start_time": start_time.isoformat(),
            "local_end_time": end_time.isoformat(),
            "enabled": payload.enabled,
        },
    )
    await _commit_conflict(db)
    site_name = None
    if window.site_id is not None:
        site_name = (
            await _tenant_site(window.site_id, org_id, db, require_active=False)
        ).name
    return _window_response(window, site_name=site_name)


@router.patch(
    "/maintenance-windows/{window_id}",
    response_model=MaintenanceWindowResponse,
    dependencies=[Depends(require_admin)],
    responses={**conflict_response},
)
@rate_limit("30/minute")
async def update_maintenance_window(
    request: Request,
    window_id: UUID,
    payload: MaintenanceWindowUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    window = await _tenant_window(window_id, org_id, db, lock=True)
    values = payload.model_dump(exclude_unset=True)
    for field in (
        "name",
        "timezone",
        "weekdays",
        "local_start_time",
        "local_end_time",
        "enabled",
    ):
        if field in values and values[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} may not be null")
    if "site_id" in values and values["site_id"] is not None:
        await _tenant_site(values["site_id"], org_id, db, require_active=True)

    name = str(values.get("name", window.name)).strip()
    if not name:
        raise HTTPException(status_code=422, detail="name may not be blank")
    normalized_timezone, weekdays, start_time, end_time = _validated_recurrence(
        timezone_name=str(values.get("timezone", window.timezone)),
        weekdays=list(values.get("weekdays", window.weekdays)),
        local_start_time=values.get(
            "local_start_time",
            window.local_start_time,
        ),
        local_end_time=values.get("local_end_time", window.local_end_time),
    )
    before = {
        "name": window.name,
        "site_id": str(window.site_id) if window.site_id else None,
        "timezone": window.timezone,
        "weekdays": list(window.weekdays or []),
        "local_start_time": window.local_start_time.isoformat(),
        "local_end_time": window.local_end_time.isoformat(),
        "enabled": bool(window.enabled),
    }
    window.name = name
    if "site_id" in values:
        window.site_id = values["site_id"]
    window.timezone = normalized_timezone
    window.weekdays = weekdays
    window.local_start_time = start_time
    window.local_end_time = end_time
    if "enabled" in values:
        window.enabled = values["enabled"]
    window.updated_at = _utcnow()
    after = {
        "name": window.name,
        "site_id": str(window.site_id) if window.site_id else None,
        "timezone": window.timezone,
        "weekdays": window.weekdays,
        "local_start_time": window.local_start_time.isoformat(),
        "local_end_time": window.local_end_time.isoformat(),
        "enabled": bool(window.enabled),
    }
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="maintenance_window_updated",
        window_id=window.id,
        details={"before": before, "after": after},
    )
    await _commit_conflict(db)
    site_name = None
    if window.site_id is not None:
        site_name = (
            await _tenant_site(window.site_id, org_id, db, require_active=False)
        ).name
    return _window_response(window, site_name=site_name)


@router.delete(
    "/maintenance-windows/{window_id}",
    response_model=MaintenanceWindowResponse,
    dependencies=[Depends(require_admin)],
)
@rate_limit("30/minute")
async def disable_maintenance_window(
    request: Request,
    window_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    window = await _tenant_window(window_id, org_id, db, lock=True)
    window.enabled = False
    window.updated_at = _utcnow()
    _audit(
        db,
        request,
        user=current_user,
        org_id=org_id,
        action="maintenance_window_disabled",
        window_id=window.id,
        details={
            "name": window.name,
            "site_id": str(window.site_id) if window.site_id else None,
        },
    )
    await db.commit()
    site_name = None
    if window.site_id is not None:
        site_name = (
            await _tenant_site(window.site_id, org_id, db, require_active=False)
        ).name
    return _window_response(window, site_name=site_name)
