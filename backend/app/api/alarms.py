"""Alarms API Routes.

TENANCY (FS-216/217). Every query here MUST constrain by organization.

``alarms`` used to have neither an ``organization_id`` column nor an RLS policy
(absent from migrations 011/033), so ``get_tenant_db``'s ``app.current_org_id`` GUC
did nothing for it and tenancy existed only where a query joined ``assets``. Five
of the six endpoints did not join: org B could read, acknowledge, clear and
bulk-acknowledge org A's alarms. The sixth (``/active``) joined only
``if organization_id:`` — a client-supplied optional query parameter, so omitting
it dropped the filter and supplying another org's id was obeyed.

Two barriers now, and both matter:

* ``_org_scoped()`` below, so no endpoint has to remember the join. Use it for
  every new alarm query.
* Migration 046 added ``alarms.organization_id`` with FORCE ROW LEVEL SECURITY,
  so a query that forgets the predicate returns nothing rather than everything.

One consequence of that RLS: **do not** ``await db.refresh(obj)`` after
``await db.commit()`` in this module. The GUC is session-scoped but commit returns
the connection to the pool, so the refresh can run on a connection that never had
it set and RLS hides the row. See the warning in ``app/core/tenant.py`` — the two
calls here survived that cleanup only because ``alarms`` had no policy at the time.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from types import SimpleNamespace
from sqlalchemy import Select, select, and_, case, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.pagination import PaginatedResponse, paginate
from app.db.models import Alarm, Asset, User
from app.models.schemas import AlarmResponse, AlarmAcknowledge
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.middleware.rbac import require_operator_or_admin
from pydantic import BaseModel


class ActiveAlarmSeverityCounts(BaseModel):
    """The five buckets `/active` counts. `info` is sent and the client's type omits it —
    kept because the handler produces it, not because anything reads it."""

    critical: int
    high: int
    medium: int
    low: int
    info: int


class ActiveAlarmsResponse(BaseModel):
    """`GET /active`.

    `alarms` was the only alarm payload on this router serving RAW ORM rows — the list and
    detail endpoints have always filtered through `AlarmResponse`. Declaring it here makes
    the three consistent and stops `organization_id` going out on one of them; every field
    the client's `Alarm` type reads is in `AlarmResponse` already.
    """

    count: int
    by_severity: ActiveAlarmSeverityCounts
    alarms: List[AlarmResponse]


class AlarmsAcknowledged(BaseModel):
    acknowledged_count: int
    message: str

router = APIRouter(dependencies=[Depends(get_current_active_user)])

# Severity ordering for display. `alarms.severity` is a VARCHAR with a CHECK
# constraint (migration 001), so ordering by the column sorts ALPHABETICALLY —
# "critical, high, low, medium" — which puts `low` above `medium`. This maps to an
# explicit rank instead. `info` is in the CHECK constraint and must be included or
# it sorts as NULL.
_SEVERITY_RANK = case(
    {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4},
    value=Alarm.severity,
    else_=5,
)


def _org_scoped(org_id: UUID) -> Select:
    """A ``select(Alarm)`` already constrained to one organization.

    The join is the ONLY thing separating tenants on this table (see module
    docstring), so it belongs in one place rather than in six call sites.
    """
    return select(Alarm).join(Asset, Alarm.asset_id == Asset.id).where(
        Asset.organization_id == org_id
    )


async def _get_own_alarm(db: AsyncSession, alarm_id: UUID, org_id: UUID) -> Alarm:
    """Fetch one alarm belonging to ``org_id``, or 404.

    404 rather than 403 for a foreign alarm, matching the convention elsewhere:
    do not leak the existence of another tenant's resources.
    """
    result = await db.execute(_org_scoped(org_id).where(Alarm.id == alarm_id))
    alarm = result.scalars().first()
    if not alarm:
        raise HTTPException(status_code=404, detail="Alarm not found")
    return alarm


@router.get("/", response_model=PaginatedResponse[AlarmResponse], summary="List alarms", description="Retrieve a paginated list of alarms with optional filtering by asset, severity, acknowledgment status, and time range. Defaults to last 24 hours if no time range specified. Returns a {items, meta} envelope with the true total count.")
async def list_alarms(
    asset_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    severity: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """List alarms with filtering"""
    query = _org_scoped(org_id)

    if asset_id:
        query = query.where(Alarm.asset_id == asset_id)
    if is_active is not None:
        query = query.where(Alarm.is_active == is_active)
    if severity:
        query = query.where(Alarm.severity == severity)
    if acknowledged is not None:
        query = query.where(Alarm.is_acknowledged == acknowledged)
    if start_time:
        query = query.where(Alarm.occurred_at >= start_time)
    if end_time:
        query = query.where(Alarm.occurred_at <= end_time)

    # Default to last 24 hours if no time range
    if not start_time and not end_time:
        query = query.where(Alarm.occurred_at >= datetime.now(timezone.utc) - timedelta(hours=24))

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    query = query.order_by(Alarm.occurred_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return paginate(result.scalars().all(), total, SimpleNamespace(skip=skip, limit=limit))


@router.get("/active", response_model=ActiveAlarmsResponse, summary="List active alarms", description="Retrieve all currently active (unacknowledged) alarms with severity-based ordering. Used for real-time monitoring dashboards.")
async def get_active_alarms(
    severity: Optional[str] = None,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get active (unacknowledged) alarms.

    The ``organization_id`` query parameter this endpoint used to accept is gone —
    org comes from the token. It was optional, so callers who omitted it received
    every tenant's alarms, and callers who supplied someone else's id were obeyed.
    """
    query = _org_scoped(org_id).where(
        and_(
            Alarm.is_active == True,
            Alarm.is_acknowledged == False
        )
    )

    if severity:
        query = query.where(Alarm.severity == severity)

    query = query.order_by(_SEVERITY_RANK, Alarm.occurred_at.desc())

    result = await db.execute(query)
    alarms = result.scalars().all()

    return {
        "count": len(alarms),
        "by_severity": {
            "critical": len([a for a in alarms if a.severity == "critical"]),
            "high": len([a for a in alarms if a.severity == "high"]),
            "medium": len([a for a in alarms if a.severity == "medium"]),
            "low": len([a for a in alarms if a.severity == "low"]),
            "info": len([a for a in alarms if a.severity == "info"]),
        },
        "alarms": alarms
    }


@router.get("/{alarm_id}", response_model=AlarmResponse, summary="Get alarm details", description="Retrieve detailed information about a specific alarm including its history, acknowledgment status, and related asset.")
async def get_alarm(
    alarm_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get a single alarm by ID"""
    return await _get_own_alarm(db, alarm_id, org_id)


@router.post("/{alarm_id}/acknowledge", response_model=AlarmResponse, summary="Acknowledge alarm", description="Mark an alarm as acknowledged with optional notes. Acknowledged alarms remain active but are tracked as reviewed by an operator.", dependencies=[Depends(require_operator_or_admin)])
async def acknowledge_alarm(
    alarm_id: UUID,
    ack_data: AlarmAcknowledge,
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Acknowledge an alarm.

    ``acknowledged_by`` comes from the token. It was previously
    ``user_id: UUID = None  # Would come from auth dependency`` — a QUERY
    PARAMETER, so every acknowledgement wrote NULL and a caller could attribute
    their acknowledgement to any user id they chose.
    """
    alarm = await _get_own_alarm(db, alarm_id, org_id)

    if alarm.is_acknowledged:
        raise HTTPException(status_code=400, detail="Alarm already acknowledged")

    alarm.is_acknowledged = True
    alarm.acknowledged_by = current_user.id
    alarm.acknowledged_at = datetime.now(timezone.utc)
    alarm.acknowledged_comment = ack_data.comment

    # No `await db.refresh(alarm)` here. get_tenant_db's GUC is session-scoped but
    # commit() returns the connection to the pool, so the refresh SELECT can land on
    # a connection that never had app.current_org_id set — RLS then hides the row and
    # refresh raises "Could not refresh instance", load-dependently. See the warning
    # in app/core/tenant.py. AsyncSessionLocal sets expire_on_commit=False, so `alarm`
    # is already fully populated.
    #
    # These two calls survived the sweep that removed ~20 others only because
    # `alarms` had no RLS policy; migration 046 turned a latent bug into a real one.
    await db.commit()

    return alarm


@router.post("/{alarm_id}/clear", response_model=AlarmResponse, summary="Clear alarm", description="Mark an alarm as resolved/cleared. This should only be done when the underlying issue has been fixed.", dependencies=[Depends(require_operator_or_admin)])
async def clear_alarm(
    alarm_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Mark an alarm as cleared"""
    alarm = await _get_own_alarm(db, alarm_id, org_id)

    alarm.is_active = False
    alarm.cleared_at = datetime.now(timezone.utc)

    # No `await db.refresh(alarm)` here. get_tenant_db's GUC is session-scoped but
    # commit() returns the connection to the pool, so the refresh SELECT can land on
    # a connection that never had app.current_org_id set — RLS then hides the row and
    # refresh raises "Could not refresh instance", load-dependently. See the warning
    # in app/core/tenant.py. AsyncSessionLocal sets expire_on_commit=False, so `alarm`
    # is already fully populated.
    #
    # These two calls survived the sweep that removed ~20 others only because
    # `alarms` had no RLS policy; migration 046 turned a latent bug into a real one.
    await db.commit()

    return alarm


@router.post("/acknowledge-all", response_model=AlarmsAcknowledged, summary="Acknowledge all active alarms", description="Bulk acknowledge all currently active alarms, optionally filtered by asset and severity. Used during shift handover or after maintenance.", dependencies=[Depends(require_operator_or_admin)])
async def acknowledge_all_alarms(
    asset_id: Optional[UUID] = None,
    severity: Optional[str] = None,
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Acknowledge all active alarms matching criteria.

    This was the widest of the six: an unscoped bulk mutation, so one caller
    could acknowledge every tenant's outstanding alarms in a single request.
    """
    query = _org_scoped(org_id).where(
        and_(
            Alarm.is_active == True,
            Alarm.is_acknowledged == False
        )
    )

    if asset_id:
        query = query.where(Alarm.asset_id == asset_id)
    if severity:
        query = query.where(Alarm.severity == severity)

    result = await db.execute(query)
    alarms = result.scalars().all()

    now = datetime.now(timezone.utc)
    for alarm in alarms:
        alarm.is_acknowledged = True
        alarm.acknowledged_by = current_user.id
        alarm.acknowledged_at = now

    await db.commit()

    return {
        "acknowledged_count": len(alarms),
        "message": f"Acknowledged {len(alarms)} alarms"
    }
