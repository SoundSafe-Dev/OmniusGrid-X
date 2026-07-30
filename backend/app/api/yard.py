"""
Yard Management API Endpoints (YMS)
Trailer tracking, dock scheduling, yard operations
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.pagination import PaginatedResponse, paginate
from app.db.database import get_db  # noqa: F401  (kept for any non-tenant reads)
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.db.models import (
    YardTrailer, DockDoor, YardMove, DriverWaitTime,
    DockAppointment, YardCheckPoint, Carrier
)
from app.models.schemas import (
    YardTrailerCreate, YardTrailerUpdate, YardTrailerResponse,
    DockDoorCreate, DockDoorUpdate, DockDoorResponse,
    YardMoveCreate, YardMoveResponse,
    DriverWaitTimeCreate, DriverWaitTimeResponse,
    DockAppointmentCreate, DockAppointmentUpdate, DockAppointmentResponse,
    YardCheckPointCreate, YardCheckPointResponse,
    DwellTimeAnalytics
)
from app.services.yard_management import (
    yard_management_service, dock_scheduler, DetentionCalculator
)

# No router-level prefix: main.py already includes this router at its /api/v1/...
# path. (The old prefix double-prefixed every route — e.g. /api/v1/yard/yard/* —
# never noticed because the frontend ran on mocks.)
from app.middleware.rbac import require_operator_or_admin

router = APIRouter(tags=["yard_management"], dependencies=[Depends(get_current_active_user)])


def _iso(dt):
    """ISO-8601 string for a datetime, or None."""
    return dt.isoformat() if dt else None


async def _resolve_carrier_names(carrier_ids, db: AsyncSession) -> Dict[str, Any]:
    """Map {carrier_id -> carrier_name} in one query (the UI shows names)."""
    ids = {c for c in carrier_ids if c}
    if not ids:
        return {}
    rows = (await db.execute(
        select(Carrier.id, Carrier.carrier_name).where(Carrier.id.in_(ids))
    )).all()
    return {str(cid): name for cid, name in rows}


async def _resolve_trailer_plates(trailer_ids, db: AsyncSession) -> Dict[str, Any]:
    """Map {trailer_id -> license_plate} in one query.

    The dock-door card renders `door.trailerLicensePlate` as bare text and the appointment
    row renders `appt.trailerLicensePlate || appt.trailerId || '-'`. Neither was ever sent:
    `dock_doors.current_trailer_id` and `dock_appointments.trailer_id` reference
    `yard_trailers`, and the plate lives there. The door card showed an empty line where the
    trailer at the dock should be identified.

    One query, not one per row — the same shape as `_resolve_carrier_names` directly above,
    and for the same reason.
    """
    ids = {t for t in trailer_ids if t}
    if not ids:
        return {}
    rows = (await db.execute(
        select(YardTrailer.id, YardTrailer.license_plate).where(YardTrailer.id.in_(ids))
    )).all()
    return {str(tid): plate for tid, plate in rows}


# ==================== Yard Trailer Endpoints ====================

@router.post("/trailers/checkin", response_model=YardTrailerResponse, dependencies=[Depends(require_operator_or_admin)])
async def trailer_check_in(
    data: YardTrailerCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Process trailer check-in to yard"""
    trailer = await yard_management_service.check_in_trailer(
    # FROM THE TOKEN, NEVER THE REQUEST. This read `data.organization_id`, a field the
    # client supplies, so a caller could file the row under any organisation they named.
    # Removed by hand six times already in this codebase — the yard list, dock doors, dock
    # schedule, maintenance schedule, geofence zones and dashboard overview each carry a
    # comment saying so — which is why it is now a guard
    # (test_no_handler_takes_its_tenant_from_the_body.py) rather than a seventh comment.
    #
    # The `*Create` schema still declares the field, so an existing client may keep sending
    # one; it is ignored. Making it optional there is a separate change with its own readers
    # to check.
        organization_id=organization_id,
        trailer_number=data.trailer_number,
        carrier_id=data.carrier_id,
        driver_id=data.driver_id,
        shipment_id=data.shipment_id,
        trailer_type=data.trailer_type,
        seal_number=data.seal_number,
        weight_lbs=data.weight_lbs,
        db=db
    )
    return trailer


@router.post("/trailers/{trailer_id}/checkout", response_model=dict, dependencies=[Depends(require_operator_or_admin)])
async def trailer_check_out(
    trailer_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Process trailer check-out from yard"""
    try:
        result = await yard_management_service.check_out_trailer(
            trailer_id=trailer_id,
            db=db
        )
        return {
            "message": "Trailer checked out successfully",
            "trailer_id": str(trailer_id),
            "trailer_number": result['trailer'].trailer_number
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/trailers", response_model=PaginatedResponse[Dict[str, Any]])
async def get_yard_inventory(
    # organization_id comes from the TOKEN, not the query string. It was a
    # required client-supplied query parameter — the IDOR shape this codebase
    # forbids (see app/core/tenant.py), and the WHERE clause below used the
    # caller's value directly. RLS was the only thing standing between that and a
    # cross-tenant read.
    #
    # It was also simply broken: being required with no default, every frontend
    # call — none of which sent it — got a 422.
    organization_id: UUID = Depends(get_tenant_org_id),
    status: Optional[str] = Query(None, description="Filter by status: checked_in, docked, yard"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get current yard inventory (FS-99: {items, meta} envelope with a real total).

    Adds carrierName join + the MISSING UI columns.
    """
    trailers, total = await yard_management_service.get_yard_inventory(
        organization_id=organization_id,
        status=status,
        skip=skip,
        limit=limit,
        db=db
    )

    carrier_names = await _resolve_carrier_names(
        {t.carrier_id for t in trailers if t.carrier_id}, db
    )

    items: List[Dict[str, Any]] = []
    for t in trailers:
        row = YardTrailerResponse.model_validate(t).model_dump(mode="json", by_alias=True)
        row["carrierName"] = carrier_names.get(str(t.carrier_id))
        row["licensePlate"] = t.license_plate
        row["detentionCost"] = t.detention_cost
        row["detentionRisk"] = t.detention_risk
        items.append(row)
    return paginate(items, total, SimpleNamespace(skip=skip, limit=limit))


@router.get("/trailers/{trailer_id}", response_model=YardTrailerResponse)
async def get_trailer(
    trailer_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get trailer details"""
    from sqlalchemy import select
    result = await db.execute(
        select(YardTrailer).where(YardTrailer.id == trailer_id)
    )
    trailer = result.scalar_one_or_none()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    return trailer


@router.put("/trailers/{trailer_id}", response_model=YardTrailerResponse, dependencies=[Depends(require_operator_or_admin)])
async def update_trailer(
    trailer_id: UUID,
    data: YardTrailerUpdate,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Update trailer information"""
    from sqlalchemy import select
    result = await db.execute(
        select(YardTrailer).where(YardTrailer.id == trailer_id)
    )
    trailer = result.scalar_one_or_none()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(trailer, field, value)
    
    trailer.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return trailer


# ==================== Dock Door Endpoints ====================

@router.post("/dock/doors", response_model=DockDoorResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_dock_door(
    data: DockDoorCreate,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Create new dock door"""
    door = DockDoor(**data.model_dump())
    db.add(door)
    await db.commit()
    return door


@router.get("/dock/doors", response_model=List[DockDoorResponse])
async def get_dock_doors(
    # organization_id comes from the TOKEN, not the query string. It was a
    # required client-supplied query parameter — the IDOR shape this codebase
    # forbids (see app/core/tenant.py), and the WHERE clause below used the
    # caller's value directly. RLS was the only thing standing between that and a
    # cross-tenant read.
    #
    # It was also simply broken: being required with no default, every frontend
    # call — none of which sent it — got a 422.
    organization_id: UUID = Depends(get_tenant_org_id),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get all dock doors"""
    from sqlalchemy import select
    query = select(DockDoor).where(DockDoor.organization_id == organization_id)
    if status:
        query = query.where(DockDoor.status == status)
    doors = (await db.execute(query)).scalars().all()

    # `trailerLicensePlate` is what the door card prints to identify the trailer at the
    # dock, and it was never sent — the plate is on `yard_trailers`, reached through
    # `current_trailer_id`. Returning ORM rows directly is what made that easy to miss:
    # the response model quietly describes only the columns of one table.
    plates = await _resolve_trailer_plates({d.current_trailer_id for d in doors}, db)
    items: List[Dict[str, Any]] = []
    for d in doors:
        row = DockDoorResponse.model_validate(d).model_dump(mode="json", by_alias=True)
        # snake_case ON THE WIRE. `/api/v1/yard` is registered on the frontend casing
        # seam, which converts `trailer_license_plate` to `trailerLicensePlate` — writing
        # the camel form here would survive the transform unchanged and arrive as a second,
        # differently-spelled key.
        row["trailer_license_plate"] = plates.get(str(d.current_trailer_id))
        items.append(row)
    return items


@router.post("/dock/doors/{door_id}/assign/{trailer_id}", response_model=dict, dependencies=[Depends(require_operator_or_admin)])
async def assign_trailer_to_dock(
    door_id: UUID,
    trailer_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Assign trailer to dock door"""
    try:
        result = await yard_management_service.assign_dock_door(
            trailer_id=trailer_id,
            dock_door_id=door_id,
            db=db
        )
        return {
            "message": "Trailer assigned to dock",
            "dock_door_id": str(door_id),
            "trailer_id": str(trailer_id),
            "door_number": result['dock_door'].door_number
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Dock Appointment Endpoints ====================

@router.post("/dock/appointments", response_model=DockAppointmentResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_dock_appointment(
    data: DockAppointmentCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Schedule dock appointment"""
    try:
        appointment = await dock_scheduler.schedule_appointment(
    # FROM THE TOKEN, NEVER THE REQUEST — see the guard in
    # test_no_handler_takes_its_tenant_from_the_body.py. `data.organization_id` is
    # client-supplied, so a caller could file the row under any organisation they named.
            organization_id=organization_id,
            dock_door_id=data.dock_door_id,
            scheduled_start=data.scheduled_start,
            scheduled_end=data.scheduled_end,
            appointment_type=data.appointment_type,
            carrier_id=data.carrier_id,
            trailer_id=data.trailer_id,
            shipment_id=data.shipment_id,
            operation_id=data.operation_id,
            priority=data.priority,
            db=db
        )
        return appointment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dock/appointments", response_model=List[Dict[str, Any]])
async def get_dock_schedule(
    # organization_id comes from the TOKEN, not the query string. It was a
    # required client-supplied query parameter — the IDOR shape this codebase
    # forbids (see app/core/tenant.py), and the WHERE clause below used the
    # caller's value directly. RLS was the only thing standing between that and a
    # cross-tenant read.
    #
    # It was also simply broken: being required with no default, every frontend
    # call — none of which sent it — got a 422.
    organization_id: UUID = Depends(get_tenant_org_id),
    start_date: datetime = Query(default_factory=lambda: datetime.now(timezone.utc)),
    end_date: Optional[datetime] = Query(None),
    dock_door_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get dock schedule for date range (adds carrierName join)."""
    if not end_date:
        end_date = start_date + timedelta(days=1)

    appointments = await dock_scheduler.get_dock_schedule(
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        dock_door_id=dock_door_id,
        db=db
    )

    carrier_names = await _resolve_carrier_names(
        {a.carrier_id for a in appointments if a.carrier_id}, db
    )
    plates = await _resolve_trailer_plates({a.trailer_id for a in appointments}, db)

    items: List[Dict[str, Any]] = []
    for a in appointments:
        row = DockAppointmentResponse.model_validate(a).model_dump(mode="json", by_alias=True)
        row["carrierName"] = carrier_names.get(str(a.carrier_id))
        row["trailer_license_plate"] = plates.get(str(a.trailer_id))
        items.append(row)
    return items


@router.post("/dock/appointments/{appointment_id}/start", response_model=DockAppointmentResponse, dependencies=[Depends(require_operator_or_admin)])
async def start_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Mark appointment as started"""
    try:
        appointment = await dock_scheduler.start_appointment(
            appointment_id=appointment_id,
            db=db
        )
        return appointment
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/dock/appointments/{appointment_id}/complete", response_model=DockAppointmentResponse, dependencies=[Depends(require_operator_or_admin)])
async def complete_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Mark appointment as completed"""
    try:
        appointment = await dock_scheduler.complete_appointment(
            appointment_id=appointment_id,
            db=db
        )
        return appointment
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== Yard Move Endpoints ====================

@router.post("/moves", response_model=YardMoveResponse, dependencies=[Depends(require_operator_or_admin)])
async def record_yard_move(
    data: YardMoveCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Record yard jockey move"""
    move = await yard_management_service.record_yard_move(
    # FROM THE TOKEN, NEVER THE REQUEST — see the guard in
    # test_no_handler_takes_its_tenant_from_the_body.py. `data.organization_id` is
    # client-supplied, so a caller could file the row under any organisation they named.
        organization_id=organization_id,
        trailer_id=data.trailer_id,
        from_location=data.from_location,
        to_location=data.to_location,
        move_type=data.move_type or 'yard_relocate',
        jockey_driver_id=data.jockey_driver_id,
        db=db
    )
    return move


@router.post("/moves/{move_id}/complete", response_model=YardMoveResponse, dependencies=[Depends(require_operator_or_admin)])
async def complete_yard_move(
    move_id: UUID,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Complete yard move"""
    try:
        move = await yard_management_service.complete_yard_move(
            move_id=move_id,
            db=db
        )
        return move
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== Driver Wait Time Endpoints ====================

@router.get("/dwell-times", response_model=List[DwellTimeAnalytics])
async def get_dwell_time_analytics(
    # organization_id comes from the TOKEN, not the query string. It was a
    # required client-supplied query parameter — the IDOR shape this codebase
    # forbids (see app/core/tenant.py), and the WHERE clause below used the
    # caller's value directly. RLS was the only thing standing between that and a
    # cross-tenant read.
    #
    # It was also simply broken: being required with no default, every frontend
    # call — none of which sent it — got a 422.
    organization_id: UUID = Depends(get_tenant_org_id),
    start_date: datetime = Query(default_factory=lambda: datetime.now(timezone.utc) - timedelta(days=7)),
    end_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get dwell time analytics"""
    if not end_date:
        end_date = datetime.now(timezone.utc)
    
    analytics = await yard_management_service.get_dwell_time_analytics(
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        db=db
    )
    return analytics


@router.post("/driver-wait-times", response_model=DriverWaitTimeResponse, dependencies=[Depends(require_operator_or_admin)])
async def create_driver_wait_time(
    data: DriverWaitTimeCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Create driver wait time record"""
    wait_time = await yard_management_service.create_driver_wait_time(
    # FROM THE TOKEN, NEVER THE REQUEST — see the guard in
    # test_no_handler_takes_its_tenant_from_the_body.py. `data.organization_id` is
    # client-supplied, so a caller could file the row under any organisation they named.
        organization_id=organization_id,
        driver_id=data.driver_id,
        trailer_id=data.trailer_id,
        check_in_at=data.check_in_at,
        detention_rate=data.detention_rate,
        demurrage_rate=data.demurrage_rate,
        db=db
    )
    return wait_time


# ==================== Checkpoint Endpoints ====================

@router.post("/checkpoints", response_model=YardCheckPointResponse, dependencies=[Depends(require_operator_or_admin)])
async def record_checkpoint(
    data: YardCheckPointCreate,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Record trailer checkpoint passage"""
    checkpoint = await yard_management_service.record_checkpoint(
    # FROM THE TOKEN, NEVER THE REQUEST — see the guard in
    # test_no_handler_takes_its_tenant_from_the_body.py. `data.organization_id` is
    # client-supplied, so a caller could file the row under any organisation they named.
        organization_id=organization_id,
        trailer_id=data.trailer_id,
        checkpoint_type=data.checkpoint_type,
        checkpoint_name=data.checkpoint_name,
        weight_lbs=data.weight_lbs,
        inspection_status=data.inspection_status,
        db=db
    )
    return checkpoint


# ==================== Detention Alerts (task C17) ====================

def build_detention_alert(
    trailer_number: str,
    trailer_id: str,
    check_in_at: datetime,
    now: Optional[datetime] = None,
    hourly_rate: float = DetentionCalculator.DEFAULT_DETENTION_RATE,
    free_minutes: int = DetentionCalculator.FREE_TIME_MINUTES,
    warn_within_minutes: int = 30,
) -> Optional[dict]:
    """Pure alert builder: live detention exposure for an in-yard trailer.

    Returns an alert dict once the trailer is inside the warning window before
    free time expires ("at_risk") or already accruing charges ("detention");
    None while comfortably inside free time.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:  # callers/tests may pass naive nows
        now = now.replace(tzinfo=timezone.utc)
    if check_in_at.tzinfo is None:
        # SQLite hands back naive datetimes, PG aware — coerce before the
        # aware-`now` subtraction (naive-vs-aware raises TypeError).
        check_in_at = check_in_at.replace(tzinfo=timezone.utc)
    elapsed_minutes = (now - check_in_at).total_seconds() / 60
    remaining_free = free_minutes - elapsed_minutes

    if remaining_free > warn_within_minutes:
        return None

    over_minutes = max(0.0, elapsed_minutes - free_minutes)
    charge = round((over_minutes / 60) * hourly_rate, 2)
    return {
        "trailer_id": trailer_id,
        "trailer_number": trailer_number,
        "status": "detention" if over_minutes > 0 else "at_risk",
        "elapsed_minutes": round(elapsed_minutes, 1),
        "detention_minutes": round(over_minutes, 1),
        "current_charge": charge,
        "hourly_rate": hourly_rate,
        "free_minutes": free_minutes,
        "check_in_at": check_in_at.isoformat(),
    }


@router.get("/detention-alerts", response_model=List[dict])
async def get_detention_alerts(
    organization_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_tenant_db)
):
    """Live detention exposure for trailers still in the yard.

    Computes from check-in time + the DetentionCalculator defaults, so the
    frontend's detention banner reflects real dwell instead of a hardcoded mock.
    """
    from sqlalchemy import select

    query = select(YardTrailer).where(
        YardTrailer.check_in_at.isnot(None),
        YardTrailer.check_out_at.is_(None),
    )
    if organization_id:
        query = query.where(YardTrailer.organization_id == organization_id)

    trailers = (await db.execute(query)).scalars().all()
    now = datetime.now(timezone.utc)
    alerts = []
    for t in trailers:
        alert = build_detention_alert(
            trailer_number=t.trailer_number,
            trailer_id=str(t.id),
            check_in_at=t.check_in_at,
            now=now,
        )
        if alert:
            alerts.append(alert)
    # Worst exposure first.
    alerts.sort(key=lambda a: a["current_charge"], reverse=True)
    return alerts
