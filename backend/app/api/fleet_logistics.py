"""Geofencing, maintenance, and logistics-aggregate endpoints (tasks D20-D21).

Backs the Transportation page panels that previously ran on frontend mocks only.
Three routers, mounted to match the frontend clients' URLs exactly:

    geofencing_router  -> /api/v1/geofencing/*     (zones CRUD, alerts, ack)
    maintenance_router -> /api/v1/maintenance/*    (schedules, repair orders, costs)
    logistics_router   -> /api/v1/logistics/*      (delivery-efficiency, compliance summary)

logistics_router shares the /api/v1/logistics prefix with the (separately owned)
logistics-correlation router — FastAPI merges routers on one prefix, so that
file is untouched.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db  # noqa: F401 — kept for non-tenant reads
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.db.logistics_models import (
    GeofenceAlert,
    GeofenceZone,
    MaintenanceSchedule,
    RepairOrder,
    Vehicle,
)
from app.db.models import Carrier, Driver, Shipment

logger = structlog.get_logger()


def _uuid_or_404(value: str) -> str:
    """Validate a path id before comparing it to a UUIDColumn.

    On Postgres, `WHERE uuid_col = 'not-a-uuid'` is an asyncpg type error →
    500. A malformed id simply matches nothing, so answer the honest 404.
    """
    import uuid as _uuid
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="Not found")
    return value


def _iso_or_400(value: str, field: str) -> datetime:
    """Parse an ISO-8601 payload field, answering 400 (not a 500) on garbage."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"{field} must be an ISO-8601 datetime")


from app.api.auth import get_current_active_user

_auth = [Depends(get_current_active_user)]
geofencing_router = APIRouter(tags=["Geofencing"], dependencies=_auth)
maintenance_router = APIRouter(tags=["Fleet Maintenance"], dependencies=_auth)
logistics_router = APIRouter(tags=["Transportation Management"], dependencies=_auth)


def _scope(query, model, org_id: UUID):
    """Restrict a query to the caller's organization.

    THE FIRST OF TWO LAYERS, in the order migration 051's header insists on: application
    filter first, policy second. It was written when these four tables — geofence_zones,
    geofence_alerts, maintenance_schedules, repair_orders — carried `organization_id` with
    no policy at all, so it was the only thing protecting them; 051 then added ENABLE +
    FORCE to all four.

    It stays, and not merely out of habit. The filter is what works on the SQLite offline
    path, where row-level security does not exist, and it is what makes a missing predicate
    a visible bug rather than a silently empty page.

    `organization_id` is VARCHAR(36) on all four, not a UUID column: comparing it to a
    UUID object matches zero rows rather than raising, which reads as "scoping works"
    while emptying the page. Hence `str(org_id)`.
    """
    return query.where(model.organization_id == str(org_id))

# ==================== Geofencing ====================

def _zone_out(z: GeofenceZone) -> Dict[str, Any]:
    return {
        "id": str(z.id), "name": z.name, "zoneType": z.zone_type,
        "center": {"lat": z.center_lat, "lng": z.center_lng},
        "radiusMeters": z.radius_meters, "polygon": z.polygon,
        "triggerOn": z.trigger_on, "severity": z.severity, "isActive": z.is_active,
    }


@geofencing_router.get("/zones")
async def list_zones(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    zones = (await db.execute(
        _scope(select(GeofenceZone).where(GeofenceZone.is_active == True), GeofenceZone, org_id)  # noqa: E712
    )).scalars().all()
    return [_zone_out(z) for z in zones]


@geofencing_router.get("/zones/{zone_id}")
async def get_zone(zone_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    _uuid_or_404(zone_id)
    zone = (await db.execute(
        _scope(select(GeofenceZone).where(GeofenceZone.id == zone_id), GeofenceZone, org_id)
    )).scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail="zone not found")
    return _zone_out(zone)


@geofencing_router.post("/zones")
async def create_zone(
    payload: Dict[str, Any],
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    if not payload.get("name"):
        raise HTTPException(status_code=400, detail="name is required")
    center = payload.get("center") or {}
    zone = GeofenceZone(
        # From the TOKEN, never the payload. Taking it from the body let a caller file a
        # record under any organization they cared to name, and at the time these tables had
        # no policy, so nothing downstream would have questioned it. Migration 051 policied
        # them; the token is still the only honest source for a tenant.
        organization_id=str(org_id),
        name=payload["name"],
        zone_type=payload.get("zoneType", "circle"),
        center_lat=center.get("lat"),
        center_lng=center.get("lng"),
        radius_meters=payload.get("radiusMeters"),
        polygon=payload.get("polygon"),
        trigger_on=payload.get("triggerOn", "both"),
        severity=payload.get("severity", "warning"),
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return _zone_out(zone)


@geofencing_router.put("/zones/{zone_id}")
async def update_zone(zone_id: str, payload: Dict[str, Any], org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    _uuid_or_404(zone_id)
    zone = (await db.execute(
        _scope(select(GeofenceZone).where(GeofenceZone.id == zone_id), GeofenceZone, org_id)
    )).scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail="zone not found")
    center = payload.get("center") or {}
    for attr, value in (
        ("name", payload.get("name")), ("zone_type", payload.get("zoneType")),
        ("center_lat", center.get("lat")), ("center_lng", center.get("lng")),
        ("radius_meters", payload.get("radiusMeters")), ("polygon", payload.get("polygon")),
        ("trigger_on", payload.get("triggerOn")), ("severity", payload.get("severity")),
        ("is_active", payload.get("isActive")),
    ):
        if value is not None:
            setattr(zone, attr, value)
    await db.commit()
    await db.refresh(zone)
    return _zone_out(zone)


@geofencing_router.delete("/zones/{zone_id}")
async def delete_zone(zone_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    _uuid_or_404(zone_id)
    zone = (await db.execute(
        _scope(select(GeofenceZone).where(GeofenceZone.id == zone_id), GeofenceZone, org_id)
    )).scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail="zone not found")
    zone.is_active = False  # soft delete
    await db.commit()
    return {"message": "zone deleted"}


@geofencing_router.get("/alerts")
async def list_alerts(
    acknowledged: Optional[bool] = Query(None),
    severity: Optional[str] = Query(None),
    vehicle_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = _scope(
        select(GeofenceAlert).order_by(GeofenceAlert.created_at.desc()).limit(limit),
        GeofenceAlert, org_id,
    )
    if acknowledged is not None:
        query = query.where(GeofenceAlert.acknowledged == acknowledged)
    if severity:
        query = query.where(GeofenceAlert.severity == severity)
    if vehicle_id:
        query = query.where(GeofenceAlert.vehicle_id == vehicle_id)
    alerts = (await db.execute(query)).scalars().all()

    # THE NAMES THE CLIENT ACTUALLY READS. This emitted `zoneId`, `eventType` and
    # `createdAt`; `GeofenceAlert` in TypeScript declares `geofenceId`, `alertType` and
    # `timestamp`, and nothing in the frontend reads the three names that were being sent.
    #
    # `alertType` was the damaging one. `GeofencingPanel` renders
    #
    #     alert.alertType === 'entry' ? 'Entered' : alert.alertType === 'exit' ? 'Exited'
    #                                             : 'Violation'
    #
    # so an undefined field matched neither branch and EVERY alert — every routine entry
    # into an authorised zone — displayed as "Violation". A falsy ternary branch that
    # asserts, again.
    #
    # `geofenceName` and `vehicleNumber` need the zone and the vehicle, which the alert row
    # references by id. Fetched in two batched queries rather than per row: an N+1 behind
    # an alert list would be a performance defect introduced while fixing a correctness one.
    zone_names: Dict[str, str] = {}
    vehicle_numbers: Dict[str, str] = {}

    # ONLY IDS THAT ARE ACTUALLY UUIDS. `geofence_alerts.zone_id` and `.vehicle_id` are
    # `String(36)`, while `geofence_zones.id` and `vehicles.id` are UUID columns — so an
    # `IN (...)` against a free-form string raises `DataError: invalid UUID` and 500s the
    # whole endpoint. Integrations do write non-UUID identifiers here (the tenant-isolation
    # suite seeds `'VEH-a'`, which is what caught this), and a device reference that is not
    # an internal id is not a reason to fail the list — those rows simply resolve to None.
    def _uuids(values):
        out = set()
        for value in values:
            try:
                out.add(str(UUID(str(value))))
            except (ValueError, AttributeError, TypeError):
                continue
        return out

    zone_ids = _uuids(a.zone_id for a in alerts if a.zone_id)
    vehicle_ids = _uuids(a.vehicle_id for a in alerts if a.vehicle_id)
    if zone_ids:
        zone_names = {
            str(z.id): z.name
            for z in (await db.execute(
                _scope(select(GeofenceZone).where(GeofenceZone.id.in_(zone_ids)),
                       GeofenceZone, org_id)
            )).scalars().all()
        }
    if vehicle_ids:
        vehicle_numbers = {
            str(v.id): v.vehicle_number
            for v in (await db.execute(
                _scope(select(Vehicle).where(Vehicle.id.in_(vehicle_ids)), Vehicle, org_id)
            )).scalars().all()
        }

    return [{
        "id": str(a.id),
        "geofenceId": a.zone_id,
        # None, not "" — the panel must be able to tell a zone it could not resolve from
        # one with an empty name. A blank would read as an unnamed zone.
        "geofenceName": zone_names.get(str(a.zone_id)) if a.zone_id else None,
        "vehicleId": a.vehicle_id,
        "vehicleNumber": vehicle_numbers.get(str(a.vehicle_id)) if a.vehicle_id else None,
        "alertType": a.event_type,
        "severity": a.severity,
        "location": a.location or {},
        "acknowledged": a.acknowledged,
        "timestamp": a.created_at.isoformat() if a.created_at else None,
    } for a in alerts]


@geofencing_router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    _uuid_or_404(alert_id)
    alert = (await db.execute(
        _scope(select(GeofenceAlert).where(GeofenceAlert.id == alert_id), GeofenceAlert, org_id)
    )).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    alert.acknowledged = True
    alert.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "acknowledged", "id": alert_id}


# ==================== Maintenance ====================

def _aware(d: Optional[datetime]) -> Optional[datetime]:
    """Coerce a datetime to aware-UTC so naive (sqlite) and aware (asyncpg
    timestamptz) values never get compared directly."""
    if d is None:
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _schedule_out(s: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = _aware(now) or _now_utc()
    due = _aware(s.due_date)
    # Field names match the frontend MaintenanceSchedule contract.
    return {
        "id": str(s.id), "vehicleId": s.vehicle_id, "vehicleNumber": s.vehicle_id,
        "serviceType": s.maintenance_type,
        "description": s.description,
        "scheduledDate": s.due_date.isoformat() if s.due_date else None,
        "dueMileage": s.due_odometer_miles,
        "status": "overdue" if (s.status in ("scheduled", "overdue") and due and due < now) else s.status,
        # Emitted since migration 054. It was absent, so the client's adapter substituted
        # the literal 'medium' — not even a member of its own declared union — and every
        # row rendered the same invented priority whatever the operator had chosen.
        "priority": s.priority,
        "estimatedCost": s.estimated_cost,
    }


def _order_out(o: Any) -> Dict[str, Any]:
    return {
        "id": str(o.id), "vehicleId": o.vehicle_id, "title": o.title,
        # `description` was NOT SENT, though the column has always existed. The client's
        # adapter therefore filled `issueDescription` from `title` — a rename that reads
        # sensibly and quietly discarded the longer detail a technician had typed. The
        # completed-work serializer below (`_history_out`) does read `o.description`, so the
        # same repair carried its description in one view and lost it in the other.
        "description": o.description,
        "status": o.status, "priority": o.priority, "vendor": o.vendor,
        "cost": o.cost, "category": o.category,
        "completedAt": o.completed_at.isoformat() if o.completed_at else None,
        "openedAt": o.opened_at.isoformat() if o.opened_at else None,
    }


def _history_out(o: Any) -> Dict[str, Any]:
    """A completed repair order projected onto the ServiceHistoryEntry shape."""
    return {
        "id": str(o.id), "vehicleId": o.vehicle_id, "vehicleNumber": o.vehicle_id,
        "serviceType": o.category or "other", "description": o.title or o.description or "",
        "serviceDate": (o.completed_at or o.opened_at).isoformat() if (o.completed_at or o.opened_at) else None,
        "mileageAtService": 0, "cost": o.cost or 0, "technician": o.vendor, "notes": o.description,
    }


@maintenance_router.get("/schedules")
async def list_schedules(
    status: Optional[str] = Query(None),
    vehicle_id: Optional[str] = Query(None),
    upcoming: Optional[int] = Query(None, description="only schedules due within N days"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = _scope(select(MaintenanceSchedule), MaintenanceSchedule, org_id)
    now = datetime.now(timezone.utc)
    if status == "overdue":
        query = query.where(
            MaintenanceSchedule.status.in_(("scheduled", "overdue")),
            MaintenanceSchedule.due_date < now,
        )
    elif status:
        query = query.where(MaintenanceSchedule.status == status)
    if upcoming is not None:
        query = query.where(
            MaintenanceSchedule.status.in_(("scheduled", "overdue")),
            MaintenanceSchedule.due_date >= now,
            MaintenanceSchedule.due_date <= now + timedelta(days=upcoming),
        )
    if vehicle_id:
        query = query.where(MaintenanceSchedule.vehicle_id == vehicle_id)
    schedules = (await db.execute(query.order_by(MaintenanceSchedule.due_date.asc()))).scalars().all()
    return [_schedule_out(s, now) for s in schedules]


@maintenance_router.get("/schedules/{schedule_id}")
async def get_schedule(schedule_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    _uuid_or_404(schedule_id)
    s = (await db.execute(
        _scope(select(MaintenanceSchedule).where(MaintenanceSchedule.id == schedule_id),
               MaintenanceSchedule, org_id)
    )).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return _schedule_out(s)


@maintenance_router.patch("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, payload: Dict[str, Any], org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    _uuid_or_404(schedule_id)
    s = (await db.execute(
        _scope(select(MaintenanceSchedule).where(MaintenanceSchedule.id == schedule_id),
               MaintenanceSchedule, org_id)
    )).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    # Accept the frontend MaintenanceSchedule field names (serviceType/dueMileage),
    # with the legacy maintenanceType/dueOdometer as fallbacks.
    def pick(*keys):
        for k in keys:
            if payload.get(k) is not None:
                return payload[k]
        return None
    for value, attr in (
        (pick("serviceType", "maintenanceType"), "maintenance_type"),
        (pick("description"), "description"),
        (pick("status"), "status"),
        (pick("dueMileage", "dueOdometer"), "due_odometer_miles"),
        (pick("priority"), "priority"),
        (pick("estimatedCost"), "estimated_cost"),
    ):
        if value is not None:
            setattr(s, attr, value)
    scheduled = pick("scheduledDate", "dueDate")
    if scheduled:
        s.due_date = _iso_or_400(scheduled, "scheduledDate")
    if payload.get("status") == "completed" and s.completed_at is None:
        s.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)
    return _schedule_out(s)


@maintenance_router.get("/vehicles/{vehicle_id}/schedules")
async def list_vehicle_schedules(vehicle_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    schedules = (await db.execute(
        _scope(select(MaintenanceSchedule).where(MaintenanceSchedule.vehicle_id == vehicle_id),
               MaintenanceSchedule, org_id)
        .order_by(MaintenanceSchedule.due_date.asc())
    )).scalars().all()
    now = datetime.now(timezone.utc)
    return [_schedule_out(s, now) for s in schedules]


@maintenance_router.post("/schedules")
async def create_schedule(
    payload: Dict[str, Any],
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    # `vehicleNumber` is accepted because `_schedule_out` EMITS it — from this same
    # column, alongside `vehicleId`. The create form sends what it was shown, so it sent
    # vehicleNumber and every creation failed with "vehicleId is required". Reading a
    # field under one name and refusing to accept it under that name is a round trip
    # that cannot close.
    vehicle = (payload.get("vehicleId") or payload.get("vehicle_id")
               or payload.get("vehicleNumber"))
    if not vehicle:
        raise HTTPException(status_code=400, detail="vehicleId is required")
    scheduled = payload.get("scheduledDate") or payload.get("dueDate")
    schedule = MaintenanceSchedule(
        # From the TOKEN, never the payload. Taking it from the body let a caller file a
        # record under any organization they cared to name, and at the time these tables had
        # no policy, so nothing downstream would have questioned it. Migration 051 policied
        # them; the token is still the only honest source for a tenant.
        organization_id=str(org_id),
        vehicle_id=vehicle,
        maintenance_type=payload.get("serviceType") or payload.get("maintenanceType") or payload.get("maintenance_type") or "inspection",
        description=payload.get("description"),
        due_date=_iso_or_400(scheduled, "scheduledDate") if scheduled else None,
        due_odometer_miles=payload.get("dueMileage") or payload.get("dueOdometer"),
        # Collected by the form since it shipped; dropped on the floor until 054.
        priority=payload.get("priority") or "normal",
        estimated_cost=payload.get("estimatedCost"),
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    # The whole row, not two fields. Returning only id+status meant a caller could not
    # confirm that what it sent was what was stored — which is exactly how a silently
    # dropped `priority` survived.
    return _schedule_out(schedule)


@maintenance_router.get("/repair-orders")
async def list_repair_orders(
    status: Optional[str] = Query(None),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = _scope(select(RepairOrder), RepairOrder, org_id)
    if status == "active":
        query = query.where(RepairOrder.status.in_(("open", "in_progress", "awaiting_parts")))
    elif status:
        query = query.where(RepairOrder.status == status)
    orders = (await db.execute(query.order_by(RepairOrder.opened_at.desc()))).scalars().all()
    return [_order_out(o) for o in orders]


@maintenance_router.get("/repair-orders/{order_id}")
async def get_repair_order(order_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    _uuid_or_404(order_id)
    o = (await db.execute(
        _scope(select(RepairOrder).where(RepairOrder.id == order_id), RepairOrder, org_id)
    )).scalar_one_or_none()
    if o is None:
        raise HTTPException(status_code=404, detail="repair order not found")
    return _order_out(o)


@maintenance_router.patch("/repair-orders/{order_id}")
async def update_repair_order(order_id: str, payload: Dict[str, Any], org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    o = (await db.execute(
        _scope(select(RepairOrder).where(RepairOrder.id == order_id), RepairOrder, org_id)
    )).scalar_one_or_none()
    if o is None:
        raise HTTPException(status_code=404, detail="repair order not found")
    for key, attr in (("title", "title"), ("description", "description"), ("status", "status"),
                      ("priority", "priority"), ("vendor", "vendor"), ("cost", "cost"),
                      ("category", "category")):
        if payload.get(key) is not None:
            setattr(o, attr, payload[key])
    if payload.get("status") == "completed" and o.completed_at is None:
        o.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(o)
    return _order_out(o)


@maintenance_router.get("/vehicles/{vehicle_id}/repair-orders")
async def list_vehicle_repair_orders(vehicle_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    orders = (await db.execute(
        _scope(select(RepairOrder).where(RepairOrder.vehicle_id == vehicle_id), RepairOrder, org_id)
        .order_by(RepairOrder.opened_at.desc())
    )).scalars().all()
    return [_order_out(o) for o in orders]


@maintenance_router.get("/vehicles/{vehicle_id}/history")
async def vehicle_service_history(
    vehicle_id: str,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Service history = completed repair orders for the vehicle, newest first.

    THE ONE HANDLER IN THIS FILE THAT TOOK NO `org_id` AND CALLED NO `_scope`. It filtered on
    `vehicle_id` and status alone, and returned `_history_out` — description, cost, vendor and
    the technician's notes.

    On Postgres migration 051's FORCEd policy covers it, so there was no leak there. On the
    SQLite offline path there is no policy at all, which is the case `_scope` exists for: any
    caller who knew a vehicle id got that vehicle's repair history regardless of whose vehicle
    it was. The sibling endpoint one function up — same table, same shape — was scoped.
    """
    orders = (await db.execute(
        _scope(
            select(RepairOrder).where(
                RepairOrder.vehicle_id == vehicle_id,
                RepairOrder.status == "completed",
            ),
            RepairOrder,
            org_id,
        ).order_by(RepairOrder.completed_at.desc())
    )).scalars().all()
    return [_history_out(o) for o in orders]


@maintenance_router.post("/history")
async def add_service_history(
    payload: Dict[str, Any],
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Record a completed service as a completed repair order."""
    vehicle_id = payload.get("vehicleId") or payload.get("vehicle_id")
    if not vehicle_id:
        raise HTTPException(status_code=400, detail="vehicleId is required")
    order = RepairOrder(
        # From the TOKEN, never the payload. Taking it from the body let a caller file a
        # record under any organization they cared to name, and at the time these tables had
        # no policy, so nothing downstream would have questioned it. Migration 051 policied
        # them; the token is still the only honest source for a tenant.
        organization_id=str(org_id),
        vehicle_id=vehicle_id,
        title=payload.get("description") or payload.get("serviceType") or "Service",
        description=payload.get("notes"),
        status="completed",
        vendor=payload.get("technician"),
        cost=payload.get("cost"),
        category=payload.get("serviceType"),
        completed_at=_iso_or_400(payload["serviceDate"], "serviceDate") if payload.get("serviceDate") else datetime.now(timezone.utc),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return _history_out(order)


@maintenance_router.post("/repair-orders")
async def create_repair_order(
    payload: Dict[str, Any],
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    if not (payload.get("vehicleId") or payload.get("vehicle_id")) or not payload.get("title"):
        raise HTTPException(status_code=400, detail="vehicleId and title are required")
    order = RepairOrder(
        # From the TOKEN, never the payload. Taking it from the body let a caller file a
        # record under any organization they cared to name, and at the time these tables had
        # no policy, so nothing downstream would have questioned it. Migration 051 policied
        # them; the token is still the only honest source for a tenant.
        organization_id=str(org_id),
        vehicle_id=payload.get("vehicleId") or payload.get("vehicle_id"),
        schedule_id=payload.get("scheduleId"),
        title=payload["title"],
        description=payload.get("description"),
        priority=payload.get("priority", "medium"),
        vendor=payload.get("vendor"),
        cost=payload.get("cost"),
        category=payload.get("category"),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return {"id": str(order.id), "status": order.status}


def summarize_maintenance(schedules: List[Any], orders: List[Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Pure stats/costs aggregate for the maintenance panel."""
    now = _aware(now) or _now_utc()
    overdue = [
        s for s in schedules
        if getattr(s, "status", None) in ("scheduled", "overdue")
        # _aware(): SQLite hands back naive datetimes, PG aware — coerce before
        # comparing with the aware `now` (naive-vs-aware raises TypeError).
        and getattr(s, "due_date", None) and _aware(s.due_date) < now
    ]
    active = [o for o in orders if getattr(o, "status", None) in ("open", "in_progress", "awaiting_parts")]
    ytd = [
        o for o in orders
        if getattr(o, "completed_at", None) and o.completed_at.year == now.year and o.cost
    ]
    by_category: Dict[str, float] = {}
    for o in ytd:
        key = o.category or "other"
        by_category[key] = round(by_category.get(key, 0.0) + float(o.cost), 2)
    # Completed spend per month of the current year, up to and including this one. Every month
    # that has elapsed is present even at 0.00 — a month in which nothing was repaired really
    # did cost nothing, and a chart that silently omits it draws a shorter year.
    monthly: Dict[int, float] = {m: 0.0 for m in range(1, now.month + 1)}
    for o in ytd:
        month = _aware(o.completed_at).month
        if month in monthly:
            monthly[month] = round(monthly[month] + float(o.cost), 2)
    monthly_breakdown = [
        {"month": f"{now.year}-{m:02d}", "cost": monthly[m]} for m in sorted(monthly)
    ]

    ytd_total = round(sum(float(o.cost) for o in ytd), 2)

    # Estimated cost of maintenance that has NOT been done yet. `None` when no outstanding
    # schedule carries an estimate at all, which is a different fact from an outstanding
    # estimate of zero — the panel showed the latter, in a highlighted box reading
    # "Upcoming (Est.) $0", for a fleet whose upcoming work nobody had costed.
    outstanding = [
        s for s in schedules
        if getattr(s, "status", None) not in ("completed", "cancelled")
        and getattr(s, "estimated_cost", None) is not None
    ]
    upcoming_estimated = (
        round(sum(float(s.estimated_cost) for s in outstanding), 2) if outstanding else None
    )

    return {
        "scheduledCount": sum(1 for s in schedules if getattr(s, "status", None) == "scheduled"),
        "overdueCount": len(overdue),
        "activeRepairs": len(active),
        "ytdCosts": ytd_total,
        "costsByCategory": by_category,
        "monthlyBreakdown": monthly_breakdown,
        # YTD divided by the months that have ELAPSED. The client computed `ytd / 12` in
        # January as readily as in December, so the figure it showed was a twelfth of the
        # year's spend labelled as a monthly average.
        "monthlyAverage": round(ytd_total / now.month, 2),
        "upcomingEstimated": upcoming_estimated,
    }


@maintenance_router.get("/statistics")
async def maintenance_statistics(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    schedules = (await db.execute(_scope(select(MaintenanceSchedule), MaintenanceSchedule, org_id))).scalars().all()
    orders = (await db.execute(_scope(select(RepairOrder), RepairOrder, org_id))).scalars().all()
    return summarize_maintenance(schedules, orders)


@maintenance_router.get("/costs")
async def maintenance_costs(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    """The maintenance costs tab.

    THIS USED TO SEND TWO FIGURES AND THE CLIENT INVENTED THREE MORE. `monthlyAverage` was
    `ytd / 12` — computed in January as readily as in December; `costPerVehicle` and
    `upcomingEstimated` were hardcoded zeros, the second rendered in a highlighted box reading
    "Upcoming (Est.) $0"; and `monthlyBreakdown` was a required array the server never sent, so
    the chart below it drew nothing. A later pass made all four optional and the panel stopped
    displaying them, which removed the false figures and left four blank rows.

    All four are facts about data this endpoint already has, or one join away, so they are
    computed here instead. It also loads the SCHEDULES now — costs of work not yet done live
    there (`maintenance_schedules.estimated_cost`), and the previous call passed `[]`.
    """
    orders = (await db.execute(_scope(select(RepairOrder), RepairOrder, org_id))).scalars().all()
    schedules = (
        await db.execute(_scope(select(MaintenanceSchedule), MaintenanceSchedule, org_id))
    ).scalars().all()
    summary = summarize_maintenance(schedules, orders)

    # Cost per vehicle needs the fleet size, which is not derivable from repair orders: a
    # vehicle with no repairs this year has no row here and is exactly the vehicle that makes
    # the average meaningful. `None` for an empty fleet — not 0, and not a division by zero.
    vehicle_count = (
        await db.execute(_scope(select(func.count(Vehicle.id)), Vehicle, org_id))
    ).scalar() or 0

    return {
        "ytdTotal": summary["ytdCosts"],
        "byCategory": summary["costsByCategory"],
        "monthlyBreakdown": summary["monthlyBreakdown"],
        "monthlyAverage": summary["monthlyAverage"],
        "upcomingEstimated": summary["upcomingEstimated"],
        "costPerVehicle": (
            round(summary["ytdCosts"] / vehicle_count, 2) if vehicle_count else None
        ),
    }


# ==================== Logistics aggregates ====================

@logistics_router.get("/delivery-efficiency")
async def delivery_efficiency(db: AsyncSession = Depends(get_tenant_db)):
    from app.api.transportation import compute_delivery_efficiency

    shipments = (await db.execute(select(Shipment))).scalars().all()
    return compute_delivery_efficiency(shipments)


@logistics_router.get("/compliance/summary")
async def compliance_summary(db: AsyncSession = Depends(get_tenant_db)):
    """Org-wide carrier/driver compliance rollup for the Compliance tab."""
    carriers = (await db.execute(select(Carrier).where(Carrier.is_active == True))).scalars().all()  # noqa: E712
    drivers = (await db.execute(select(Driver).where(Driver.is_active == True))).scalars().all()  # noqa: E712
    now = datetime.now(timezone.utc)

    # `(d.hos_drive_hours_today or 0) >= 11` COUNTED AN UNREPORTED DRIVER AS COMPLIANT. Both
    # columns are nullable and NULL means the driver has not reported — not that they have
    # driven zero hours — so a fleet where nobody had reported produced `activeViolations: 0`,
    # which the Compliance tab renders in GREEN. An all-clear on DOT-regulated hours, generated
    # by the absence of the data that would decide it.
    #
    # This is the second time this exact class has been found on HOS. The first was
    # `hosDriveHoursRemaining === 0` on the driver list, where `null === 0` is false and every
    # fleet came back clean; the fix there derives the remaining hours and leaves them NULL
    # when the consumed figure is missing too. Same column family, different endpoint, and the
    # rollup was never brought into line.
    #
    # A driver is now assessable only if both figures are present. The counts are separate
    # because "no violations" and "nobody reported" are different facts, and
    # `/logistics_correlation`'s driver_compliance block already reports them that way.
    # The FMCSA limits live on HOSComplianceMonitor, which is what judges an individual
    # driver. A third copy of 11.0 and 70.0 here is a third place to update.
    from app.services.transportation_management import HOSComplianceMonitor

    assessable = [
        d for d in drivers
        if d.hos_drive_hours_today is not None and d.hos_cycle_hours is not None
    ]
    hos_violations = sum(
        1 for d in assessable
        if d.hos_drive_hours_today >= HOSComplianceMonitor.MAX_DRIVE_HOURS_DAY
        or d.hos_cycle_hours >= HOSComplianceMonitor.MAX_CYCLE_HOURS
    )
    expiring_soon = sum(
        1 for c in carriers
        if c.insurance_expires_at
        and (_aware(c.insurance_expires_at) - now).days <= 30
    )
    return {
        "totalCarriers": len(carriers),
        "ctpatCertified": sum(1 for c in carriers if c.ctpat_certified),
        "activeViolations": hos_violations,
        "safetyAlerts": expiring_soon,
        # So a zero can be read. `activeViolations: 0` means something different depending on
        # whether it was computed over the whole fleet or over nobody.
        "driversAssessed": len(assessable),
        "driversUnassessable": len(drivers) - len(assessable),
    }
