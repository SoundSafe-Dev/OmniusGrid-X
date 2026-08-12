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
from app.core.pagination import MAX_OFFSET, PaginatedResponse, paginate
from app.db.database import get_db  # noqa: F401  (kept for any non-tenant reads)
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.db.models import (
    YardTrailer, DockDoor, YardMove, DriverWaitTime,
    DockAppointment, YardCheckPoint, Carrier, Driver
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


async def _resolve_driver_contacts(driver_ids, db: AsyncSession) -> Dict[str, Any]:
    """Map {driver_id -> {"phone", "name"}} in ONE query.

    THE NAME CAME LATER AND HAD TO COME IN THE SAME QUERY (FS-437). Adding a second
    resolver beside this one worked and was caught immediately by
    `test_yard_driver_phone_is_resolved_realdb.py`: *"expected exactly one query against
    drivers for a page of trailers, saw 2"*. That guard was written for this resolver and
    was right to refuse the second — a per-page lookup that becomes two per page becomes
    three the next time someone needs a field.

    WHY THE NAME MATTERS AT ALL, given the phone already worked. The trailer detail panel
    wraps the whole driver section in `{trailer.driverName && ( … )}`, and `driverName` was
    never sent — so the block never rendered and took the phone inside it with it. The phone
    resolution below was real, correct, and invisible. A guard on a field nobody sends is a
    permanent `false`, and everything inside it disappears; that is worse than a blank line,
    because a blank line can be seen.

    `drivers` stores `first_name`/`last_name`, so the display name is composed here rather
    than stored. A driver with neither yields `None` and the panel then correctly omits the
    block — for a driver record with no name, rather than for every driver in the system.

    The trailer card and the trailer detail panel both render `trailer.driverPhone`, and the
    appointment row renders `appt.driverPhone` — the number an operator calls when a trailer
    has been sitting on the yard. Neither was ever sent: `yard_trailers.driver_id` and
    `dock_appointments.driver_id` reference `drivers`, and the phone lives there.

    The same shape as `_resolve_trailer_plates` above, for the same reason and with the same
    batching. `drivers.phone` is nullable, so a driver with no number recorded stays `None` and
    the line is omitted rather than showing an empty one.
    """
    ids = {d for d in driver_ids if d}
    if not ids:
        return {}
    rows = (await db.execute(
        select(Driver.id, Driver.phone, Driver.first_name, Driver.last_name)
        .where(Driver.id.in_(ids))
    )).all()
    return {
        str(did): {
            "phone": phone,
            "name": " ".join(part for part in (first, last) if part) or None,
        }
        for did, phone, first, last in rows
    }


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
        # FIVE MORE FIELDS THE SCHEMA DECLARED AND THIS ROUTE DROPPED (FS-661). Every one
        # has a column on `yard_trailers`, so they were accepted, discarded, and returned as
        # their defaults.
        #
        # `seal_number` was passed and `seal_status` was not, which is the pairing that makes
        # this worth fixing: the record says WHICH seal and could not say whether it was
        # intact. Same shape as the checkpoint with no inspector.
        #
        # The temperatures are cold-chain evidence on a reefer check-in, and `yard_location`
        # is where the trailer actually is — the field the yard map reads.
        #
        # `status` is deliberately NOT among them. The service sets 'checked_in', and a
        # caller-supplied status would let somebody check a trailer straight to 'checked_out'
        # without it ever entering the yard. Declaring it on the Create schema is that
        # schema's error, the same one `organization_id` above carries.
        seal_status=data.seal_status,
        temperature_setpoint=data.temperature_setpoint,
        temperature_actual=data.temperature_actual,
        yard_location=data.yard_location,
        meta_data=data.metadata,
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
    skip: int = Query(0, ge=0, le=MAX_OFFSET),
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
    driver_contacts = await _resolve_driver_contacts({t.driver_id for t in trailers}, db)

    items: List[Dict[str, Any]] = []
    for t in trailers:
        row = YardTrailerResponse.model_validate(t).model_dump(mode="json", by_alias=True)
        row["carrierName"] = carrier_names.get(str(t.carrier_id))
        # The number an operator calls about a trailer sitting on the yard. Declared by the
        # client, rendered on the card and in the detail panel, and sent by nothing —
        # `yard_trailers.driver_id` references `drivers`, where the phone is.
        contact = driver_contacts.get(str(t.driver_id)) or {}
        row["driverPhone"] = contact.get("phone")
        row["driverName"] = contact.get("name")
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
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Create new dock door"""
    # Server-side override: ignore any client-supplied organization_id and bind the
    # door to the authenticated user's organization — the same rule assets.py:100
    # already applies. This was the only endpoint in the API that stored the client's
    # value, so a request could name someone else's tenant. Row-level security is
    # forced on dock_doors and would reject that write, but relying on it alone means
    # the outcome depends on the database ROLE rather than the code: a connection with
    # BYPASSRLS turns the same request into a genuine cross-tenant write, and even
    # where RLS holds, the caller gets a 500 from a policy violation instead of a row
    # bound to their own tenant. Two independent controls, neither trusted alone.
    payload = data.model_dump()
    payload["organization_id"] = org_id
    door = DockDoor(**payload)
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
    driver_contacts = await _resolve_driver_contacts({a.driver_id for a in appointments}, db)

    items: List[Dict[str, Any]] = []
    for a in appointments:
        row = DockAppointmentResponse.model_validate(a).model_dump(mode="json", by_alias=True)
        row["carrierName"] = carrier_names.get(str(a.carrier_id))
        row["trailer_license_plate"] = plates.get(str(a.trailer_id))
        contact = driver_contacts.get(str(a.driver_id)) or {}
        row["driverPhone"] = contact.get("phone")
        row["driverName"] = contact.get("name")
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
        # BOTH OF THESE WERE DROPPED (FS-660). `YardCheckPointCreate` declares them and
        # `YardCheckPointResponse` returns them, and the route passed neither on — so a
        # caller recording a weigh-station or inspection checkpoint sent `inspector_id`,
        # got 200, and read `inspector_id: null` back from a column that exists and stayed
        # empty. On an inspection checkpoint that field IS the audit trail: who passed this
        # trailer. Silently discarding it leaves a record that says the check happened and
        # cannot say who made it.
        inspector_id=data.inspector_id,
        meta_data=data.metadata,
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
    organization_id: UUID = Depends(get_tenant_org_id),
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
    # UNCONDITIONAL. `organization_id` was a client-supplied optional query parameter, so a
    # bare request filtered by nothing — every other handler in this file was moved to
    # `get_tenant_org_id` and this one was missed.
    query = query.where(YardTrailer.organization_id == str(organization_id))

    trailers = (await db.execute(query)).scalars().all()
    now = datetime.now(timezone.utc)
    alerts = []
    at_risk = []
    for t in trailers:
        alert = build_detention_alert(
            trailer_number=t.trailer_number,
            trailer_id=str(t.id),
            check_in_at=t.check_in_at,
            now=now,
        )
        if alert:
            alerts.append(alert)
            at_risk.append(t)

    # THE BANNER RENDERS FOUR THINGS AND THREE OF THEM WERE NOT SENT. It shows the trailer, the
    # carrier, where in the yard it is sitting, and what it is costing — and this dict carried
    # only the identifiers and the numbers, so the row read "<id> • " above "$" and
    # "N/A excess". All three are real columns (`license_plate`, `yard_location`, and the
    # carrier's name one join away), on rows this loop already has in hand.
    #
    # An operator reads this banner to go and move a specific trailer. Its whole value is
    # saying WHICH trailer and WHERE.
    carrier_names = await _resolve_carrier_names({t.carrier_id for t in at_risk}, db)
    for alert, t in zip(alerts, at_risk):
        alert["license_plate"] = t.license_plate
        alert["yard_location"] = t.yard_location
        alert["carrier_name"] = carrier_names.get(str(t.carrier_id))

    # Worst exposure first.
    alerts.sort(key=lambda a: a["current_charge"], reverse=True)
    return alerts
