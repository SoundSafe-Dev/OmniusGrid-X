"""Fleet health / tracker endpoints (FS-15).

The web client's fleetHealth.ts and fleetTracker.ts called a family of
/api/v1/fleet/* routes that never existed (dead real branch). This router
serves them by aggregating the telematics data the platform already stores
(geotab diagnostics/exceptions/trips, drivers, shipments, geofence zones).

Mounted alongside — not inside — the OTA fleet routers (agents/releases/
rollouts); the paths are disjoint. Responses are camelCase to match the client
types directly (no transform adapter needed), matching the geotab/geofencing
convention.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.middleware.rbac import require_operator_or_admin
from app.middleware.tenant_isolation import get_tenant_org_id, get_tenant_db
from app.db.models import GeoTabDiagnostic, GeoTabException, GeoTabTrip, Driver, Shipment, User
from app.db.logistics_models import GeofenceZone

router = APIRouter(dependencies=[Depends(get_current_active_user)])


# ---- Response schemas (FS-100). Field names stay camelCase — this router's
# responses match the frontend client types directly (no transform adapter).
# Shapes are unchanged; these only document/type what the handlers already return.

class FleetHealthStatsResponse(BaseModel):
    totalVehicles: int
    activeDtcs: int
    criticalDtcs: int
    vehiclesWithIssues: int


class DtcItem(BaseModel):
    code: Optional[str] = None
    description: Optional[str] = None
    severity: str
    system: str
    timestamp: Optional[str] = None
    cleared: bool
    vehicleId: Optional[str] = None
    vehicleNumber: Optional[str] = None


class VehicleHealthItem(BaseModel):
    """One row of `_vehicle_row`, shared by the fleet list and the single-vehicle
    endpoint because they return the same dict.

    Declares exactly the nine keys `_vehicle_row` produces and no more. The
    frontend's `VehicleHealthStatus` also carries optional `driverId`,
    `driverName` and `fuelLevel`; none is ever sent, and adding them here as
    `Optional[...] = None` would not document them — it would start emitting
    three nulls that were previously absent keys. A response model has to match
    what the handler returns, not what a consumer could tolerate.
    """

    vehicleId: str
    vehicleNumber: str
    status: str
    lastCommunication: str
    dtcs: List[DtcItem]
    safetyScore: int
    securityStatus: str
    engineHours: int
    odometer: int


class SecurityEventItem(BaseModel):
    """`_security_out` — the list, the single-vehicle list, and the PATCH all
    return it, so all three share this model."""

    id: str
    vehicleId: Optional[str] = None
    vehicleNumber: Optional[str] = None
    eventType: str
    timestamp: Optional[str] = None
    severity: str
    #: `GeoTabException.location` is a JSON column; the handler passes it through
    #: untouched (`e.location or None`), so its shape is the sender's, not ours.
    location: Optional[Any] = None
    description: str
    acknowledged: bool


class DriverSafetyItem(BaseModel):
    """`_driver_safety_out`, shared by the fleet list and the per-driver route.

    `idleTimeHours` and `seatbeltViolations` are hardcoded 0 and `trend` is
    hardcoded "stable" — declared because the handler does return them, not
    because anything measures them. See #44: a figure nothing computes should not
    be mistaken for one that is measured.
    """

    driverId: str
    driverName: str
    overallScore: int
    harshBrakingEvents: int
    harshAccelerationEvents: int
    speedingEvents: int
    idleTimeHours: int
    seatbeltViolations: int
    period: str
    trend: str


class GeoPosition(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timestamp: Optional[str] = None


class VehicleLocationItem(BaseModel):
    deviceId: Optional[str] = None
    vehicleId: Optional[str] = None
    driverId: Optional[str] = None
    position: GeoPosition
    status: str
    speed: float
    heading: float
    lastUpdate: Optional[str] = None


class LatLng(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class ActiveRouteItem(BaseModel):
    shipmentId: str
    shipmentNumber: Optional[str] = None
    origin: LatLng
    destination: LatLng
    waypoints: List[Any]
    status: str
    vehicleId: Optional[str] = None
    color: str


class GeofenceItem(BaseModel):
    id: str
    name: str
    type: str
    center: Optional[LatLng] = None
    radius: Optional[float] = None
    coordinates: List[Any]
    color: str
    description: Optional[str] = None

# OBD-II DTC prefix -> health system bucket used by the frontend type.
_SYSTEM = {"P": "engine", "C": "other", "B": "safety", "U": "other"}
# geotab exception_type -> SecurityEvent.eventType
_EVENT = {
    "speeding": "unusual_route",
    "harsh_braking": "device_tampering",
    "harsh_acceleration": "device_tampering",
    "geofence": "geofence_violation",
    "after_hours": "after_hours_use",
}


def _dtc_out(d: GeoTabDiagnostic) -> dict:
    return {
        "code": d.dtc_code,
        "description": d.description or d.dtc_code,
        "severity": d.severity or "medium",
        "system": _SYSTEM.get((d.dtc_code or "")[:1].upper(), "other"),
        "timestamp": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "cleared": d.status != "active",
        "vehicleId": d.vehicle_id,
        "vehicleNumber": d.vehicle_id,
    }


async def _active_diagnostics(db, org_id, vehicle_id=None):
    stmt = select(GeoTabDiagnostic).where(
        GeoTabDiagnostic.organization_id == org_id,
        GeoTabDiagnostic.status == "active",
    )
    # Single-vehicle callers push the filter into SQL rather than loading the
    # whole org and linear-searching in Python.
    if vehicle_id is not None:
        stmt = stmt.where(GeoTabDiagnostic.vehicle_id == vehicle_id)
    return (await db.execute(stmt)).scalars().all()


async def _exceptions(db, org_id, device_id=None):
    stmt = select(GeoTabException).where(GeoTabException.organization_id == org_id)
    # Exceptions key on device_id (the single-vehicle security endpoint passes
    # the path's vehicle_id here, matching the previous Python filter exactly).
    if device_id is not None:
        stmt = stmt.where(GeoTabException.device_id == device_id)
    return (await db.execute(stmt)).scalars().all()


async def _exception_count(db, org_id, device_ids) -> int:
    """Count this org's exceptions on any of ``device_ids`` (SQL count, no rows)."""
    if not device_ids:
        return 0
    return int((await db.execute(
        select(func.count()).select_from(GeoTabException).where(
            GeoTabException.organization_id == org_id,
            GeoTabException.device_id.in_(list(device_ids)),
        )
    )).scalar() or 0)


def _vehicle_row(vid, dtcs, exc_count: int) -> dict:
    """The per-vehicle health dict, shared by the fleet list and the single-
    vehicle endpoint so they can't drift. ``_vehicle_row(vid, [], 0)`` is exactly
    the old 'unknown vehicle' default (online / secure / safetyScore 100)."""
    crit = any(d.severity == "critical" for d in dtcs)
    return {
        "vehicleId": vid, "vehicleNumber": vid,
        "status": "warning" if dtcs else "online",
        "lastCommunication": max(
            (d.last_seen_at for d in dtcs if d.last_seen_at),
            default=datetime.now(timezone.utc),
        ).isoformat(),
        "dtcs": [_dtc_out(d) for d in dtcs],
        "safetyScore": max(0, 100 - exc_count * 5),
        "securityStatus": "alert" if crit else ("warning" if dtcs else "secure"),
        "engineHours": 0, "odometer": 0,
    }


# ---------------------------------------------------------------- health / DTCs

@router.get("/health", response_model=List[VehicleHealthItem])
async def fleet_health(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    diags = await _active_diagnostics(db, org_id)
    excs = await _exceptions(db, org_id)
    by_vehicle_dtc = defaultdict(list)
    device_to_vehicle: dict = {}
    for d in diags:
        if d.vehicle_id:
            by_vehicle_dtc[d.vehicle_id].append(d)
        if d.device_id and d.vehicle_id:
            device_to_vehicle[d.device_id] = d.vehicle_id
    # Exceptions carry device_id; map them to vehicle_id via diagnostics so the
    # safety-score join uses the same identifier space (device_id != vehicle_id).
    exc_by_vehicle = defaultdict(int)
    for e in excs:
        vehicle = device_to_vehicle.get(e.device_id, e.device_id)
        exc_by_vehicle[vehicle] += 1

    return [
        _vehicle_row(vid, dtcs, exc_by_vehicle.get(vid, 0))
        for vid, dtcs in by_vehicle_dtc.items()
    ]


@router.get("/health/statistics", response_model=FleetHealthStatsResponse)
async def fleet_health_stats(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    diags = await _active_diagnostics(db, org_id)
    vehicles = {d.vehicle_id for d in diags if d.vehicle_id}
    return {
        "totalVehicles": len(vehicles),
        "activeDtcs": len(diags),
        "criticalDtcs": sum(1 for d in diags if d.severity == "critical"),
        "vehiclesWithIssues": len(vehicles),
    }


@router.get("/health/{vehicle_id}", response_model=VehicleHealthItem)
async def vehicle_health(vehicle_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    # Scoped instead of building the whole fleet aggregation and linear-searching
    # it. A vehicle with no active diagnostics returns the default row (exactly
    # the old fallback), and — matching the old code — its exceptions are not
    # even consulted in that case.
    dtcs = await _active_diagnostics(db, org_id, vehicle_id=vehicle_id)
    exc_count = 0
    if dtcs:
        # fleet_health maps an exception to a vehicle by device_id via the
        # diagnostics device set, falling back to device_id == vehicle_id. Scope
        # the count to that same identifier set (the vehicle's devices plus the
        # vehicle_id itself) so the score matches the full-fleet computation.
        device_ids = {d.device_id for d in dtcs if d.device_id} | {vehicle_id}
        exc_count = await _exception_count(db, org_id, device_ids)
    return _vehicle_row(vehicle_id, dtcs, exc_count)


@router.get("/dtcs", response_model=List[DtcItem])
async def all_dtcs(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    return [_dtc_out(d) for d in await _active_diagnostics(db, org_id)]


@router.get("/vehicles/{vehicle_id}/dtcs", response_model=List[DtcItem])
async def vehicle_dtcs(vehicle_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    diags = await _active_diagnostics(db, org_id, vehicle_id=vehicle_id)
    return [_dtc_out(d) for d in diags]


# ------------------------------------------------------------------- security

def _security_out(e: GeoTabException) -> dict:
    return {
        "id": str(e.id), "vehicleId": e.device_id, "vehicleNumber": e.device_id,
        "eventType": _EVENT.get(e.exception_type, "unusual_route"),
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "severity": e.severity or "medium", "location": e.location or None,
        "description": f"{e.exception_type} event", "acknowledged": bool(e.acknowledged),
    }


@router.get("/security/events", response_model=List[SecurityEventItem])
async def security_events(
    acknowledged: Optional[bool] = Query(None),
    severity: Optional[str] = Query(None),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    excs = await _exceptions(db, org_id)
    out = [_security_out(e) for e in excs]
    if acknowledged is not None:
        out = [e for e in out if e["acknowledged"] == acknowledged]
    if severity:
        out = [e for e in out if e["severity"] == severity]
    return out


class SecurityEventAcknowledge(BaseModel):
    acknowledged: bool = True


@router.patch("/security/events/{event_id}", response_model=SecurityEventItem, dependencies=[Depends(require_operator_or_admin)])
async def acknowledge_security_event(
    event_id: UUID,
    payload: SecurityEventAcknowledge,
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Acknowledge (or un-acknowledge) a fleet security event.

    THE UI HAS ALWAYS CALLED THIS; the backend has never served it.
    `HealthSecurityPanel` awaits `fleetHealthApi.acknowledgeSecurityEvent` with no
    `catch`, so the 404 rejected the promise, the optimistic state update never ran,
    and an operator clicking "acknowledge" saw nothing happen and no error.

    Everything else was already in place — `geotab_exceptions` carries `acknowledged`,
    `acknowledged_by` and `acknowledged_at`, and `GET /security/events` already returns
    and filters on the flag. Only the write was missing.

    `acknowledged_by` comes from the token rather than the body, matching
    `alarms.acknowledge_alarm`: attribution a caller can set is not attribution.
    """
    event = (
        await db.execute(
            select(GeoTabException).where(
                GeoTabException.id == event_id,
                GeoTabException.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if event is None:
        # 404 rather than 403 for another tenant's event: telling a caller that an id
        # exists but is not theirs is itself a disclosure.
        raise HTTPException(status_code=404, detail="Security event not found")

    event.acknowledged = payload.acknowledged
    if payload.acknowledged:
        event.acknowledged_by = current_user.id
        event.acknowledged_at = datetime.now(timezone.utc)
    else:
        event.acknowledged_by = None
        event.acknowledged_at = None

    await db.commit()
    return _security_out(event)


@router.get("/vehicles/{vehicle_id}/security", response_model=List[SecurityEventItem])
async def vehicle_security(vehicle_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    excs = await _exceptions(db, org_id, device_id=vehicle_id)
    return [_security_out(e) for e in excs]


# --------------------------------------------------------------- driver safety

@router.get("/safety/drivers", response_model=List[DriverSafetyItem])
async def driver_safety(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    drivers = (await db.execute(select(Driver).where(Driver.organization_id == org_id))).scalars().all()
    excs = await _exceptions(db, org_id)
    by_type = defaultdict(lambda: defaultdict(int))
    for e in excs:
        if e.driver_id:
            by_type[str(e.driver_id)][e.exception_type] += 1
    return [_driver_safety_out(d, by_type[str(d.id)]) for d in drivers]


def _driver_safety_out(d: Driver, counts: dict) -> dict:
    harsh_b = counts.get("harsh_braking", 0)
    harsh_a = counts.get("harsh_acceleration", 0)
    speeding = counts.get("speeding", 0)
    score = max(0, 100 - (harsh_b + harsh_a) * 5 - speeding * 8)
    return {
        "driverId": str(d.id), "driverName": f"{d.first_name} {d.last_name}".strip(),
        "overallScore": score, "harshBrakingEvents": harsh_b,
        "harshAccelerationEvents": harsh_a, "speedingEvents": speeding,
        "idleTimeHours": 0, "seatbeltViolations": 0, "period": "30d", "trend": "stable",
    }


@router.get("/safety/drivers/{driver_id}", response_model=DriverSafetyItem)
async def one_driver_safety(driver_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    from fastapi import HTTPException

    # `drivers.id` is a UUID column and this parameter is a free-form `str`. On Postgres
    # `WHERE uuid_col = '0'` is an asyncpg type error, not an empty result — so
    # `GET /fleet/safety/drivers/0` answered 500 where the schema promises a 4xx. A
    # malformed id matches no driver, which is a 404 and not a server fault. Found by the
    # contract gate (FS-259); same class as `fleet_logistics._uuid_or_404`.
    try:
        UUID(driver_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="driver not found")

    d = (await db.execute(select(Driver).where(Driver.id == driver_id, Driver.organization_id == org_id))).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="driver not found")
    excs = await _exceptions(db, org_id)
    counts = defaultdict(int)
    for e in excs:
        if str(e.driver_id) == driver_id:
            counts[e.exception_type] += 1
    return _driver_safety_out(d, counts)


# ------------------------------------------------------------- live tracking

@router.get("/vehicles/locations", response_model=List[VehicleLocationItem])
async def vehicle_locations(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    trips = (await db.execute(
        select(GeoTabTrip).where(GeoTabTrip.organization_id == org_id).order_by(GeoTabTrip.start_time.desc())
    )).scalars().all()
    seen = {}
    for t in trips:
        if t.device_id in seen:
            continue
        loc = t.end_location or t.start_location or {}
        seen[t.device_id] = {
            "deviceId": t.device_id, "vehicleId": t.vehicle_id or t.device_id,
            "driverId": str(t.driver_id) if t.driver_id else None,
            "position": {"latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
                         "timestamp": (t.end_time or t.start_time).isoformat() if (t.end_time or t.start_time) else None},
            "status": "idle", "speed": loc.get("speed") or 0, "heading": loc.get("heading") or 0,
            "lastUpdate": (t.end_time or t.start_time).isoformat() if (t.end_time or t.start_time) else None,
        }
    return list(seen.values())


@router.get("/vehicles/{device_id}/location", response_model=VehicleLocationItem)
async def vehicle_location(device_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    from fastapi import HTTPException
    all_locs = await vehicle_locations(org_id, db)
    for v in all_locs:
        if v["deviceId"] == device_id:
            return v
    raise HTTPException(status_code=404, detail="no location for device")


@router.get("/shipments/active-routes", response_model=List[ActiveRouteItem])
async def active_routes(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    ships = (await db.execute(
        select(Shipment).where(
            Shipment.organization_id == org_id,
            Shipment.status.in_(("dispatched", "in_transit")),
        )
    )).scalars().all()
    colors = {"in_transit": "#22c55e", "dispatched": "#eab308"}
    out = []
    for s in ships:
        origin = s.origin or {}
        dest = s.destination or {}
        out.append({
            "shipmentId": str(s.id), "shipmentNumber": s.shipment_number,
            "origin": {"latitude": origin.get("latitude"), "longitude": origin.get("longitude")},
            "destination": {"latitude": dest.get("latitude"), "longitude": dest.get("longitude")},
            "waypoints": [], "status": s.status,
            "vehicleId": str(s.trailer_id) if s.trailer_id else None,
            "color": colors.get(s.status, "#3b82f6"),
        })
    return out


@router.get("/geofences", response_model=List[GeofenceItem])
async def fleet_geofences(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    zones = (await db.execute(
        select(GeofenceZone).where(
            GeofenceZone.organization_id == str(org_id),
            GeofenceZone.is_active == True,  # noqa: E712
        )
    )).scalars().all()
    sev_color = {"info": "green", "warning": "yellow", "critical": "red"}
    return [{
        "id": str(z.id), "name": z.name,
        "type": "polygon" if z.polygon else "circle",
        "center": {"latitude": z.center_lat, "longitude": z.center_lng} if z.center_lat is not None else None,
        "radius": z.radius_meters, "coordinates": z.polygon or [],
        "color": sev_color.get(z.severity, "green"), "description": None,
    } for z in zones]
