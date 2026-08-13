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
    """What the active-diagnostics table can actually answer (FS-398).

    `totalVehicles` was here and is gone. It was computed as the size of the
    active-diagnostics set — identical to `vehiclesWithIssues` on every call — so the pair
    could never disagree, and a fleet with nothing wrong reported zero vehicles in total.
    The fleet size is not derivable here: `GeoTabDiagnostic.vehicle_id` is a bare
    `String(100)` with no foreign key to `vehicles`.
    """

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

    THREE OF THESE WERE CONSTANTS AND ONE WAS A LIE (FS-533). The previous docstring
    recorded the first part honestly — `idleTimeHours` and `seatbeltViolations` were
    hardcoded `0` and `trend` was hardcoded `"stable"` — and left it there, which is how a
    documented placeholder becomes a permanent one.

    `seatbeltViolations: 0` is not a neutral placeholder on a driver safety report. It is a
    claim that no driver in the fleet has ever been recorded unbelted, on the same screen as
    a score that determines who gets coached. It is now **counted from the same
    `geotab_exceptions` rows the other three come from**, which is where it always was.

    `period: "30d"` was the lie. `_exceptions` applied no time filter at all, so every count
    on this response was lifetime-to-date while the payload said thirty days. A driver's
    score got worse forever and never recovered, because nothing ever aged out. The query is
    now windowed, which makes the existing label true and makes `trend` computable.

    `idleTimeHours` stays **None**. Idle time is a duration and `geotab_exceptions` records
    events, with no duration column — there is nothing in this schema to compute it from.
    Optional and null is the honest shape; a zero is a measurement.
    """

    driverId: str
    driverName: str
    overallScore: int
    harshBrakingEvents: int
    harshAccelerationEvents: int
    speedingEvents: int
    #: None — no duration data exists for this. See the class docstring.
    idleTimeHours: Optional[int] = None
    seatbeltViolations: int
    period: str
    #: "improving" | "worsening" | "stable", from this window against the one before it.
    #: None when the previous window has nothing to compare against.
    trend: Optional[str] = None


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


async def _device_ids_for(db, org_id, identifier: str) -> list[str]:
    """Every GeoTab device id belonging to `identifier`, whichever space it is in.

    `geotab_diagnostics` is the only table carrying both `device_id` and `vehicle_id`, so it
    is the bridge between them — `fleet_health()` already walks it the other way to build
    `device_to_vehicle`. A vehicle can have more than one device over its life, so this
    returns a list rather than the first match.

    THE IDENTIFIER IS ALWAYS INCLUDED, not used only as a fallback. Exceptions in this
    codebase are keyed both ways depending on where the row came from — the seeded fleet
    keys them by `gt-device-001` while `test_fleet_health_query_shape`'s fixture keys them
    by the vehicle id — and both are legitimate. Returning the union answers either without
    having to know which, and costs one extra value in an `IN` clause (FS-404).
    """
    rows = (
        await db.execute(
            select(GeoTabDiagnostic.device_id).where(
                GeoTabDiagnostic.organization_id == org_id,
                GeoTabDiagnostic.vehicle_id == identifier,
                GeoTabDiagnostic.device_id.isnot(None),
            )
        )
    ).scalars().all()
    return sorted({r for r in rows if r} | {identifier})


#: The window the driver-safety response has always claimed (`period: "30d"`) and never
#: applied. Named rather than inlined so the label and the filter come from one place —
#: they disagreed for as long as both existed.
SAFETY_WINDOW_DAYS = 30


async def _exceptions(db, org_id, device_id=None, device_ids=None, since=None):
    """Exceptions for this org, optionally windowed.

    `since` is opt-in and defaults to None so the callers that want every exception —
    the security feed, the vehicle DTC join — are unchanged. Only the safety scores
    pass it, because only they claim a period.
    """
    stmt = select(GeoTabException).where(GeoTabException.organization_id == org_id)
    if since is not None:
        stmt = stmt.where(GeoTabException.timestamp >= since)
    # `device_ids` is the resolved set from `_device_ids_for` — the vehicle's devices plus
    # the caller's own identifier. Filtered in SQL so a per-vehicle read never loads the org.
    if device_ids is not None:
        stmt = stmt.where(GeoTabException.device_id.in_(device_ids))
    elif device_id is not None:
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
    # `vehicles` IS THE SET WITH ACTIVE DIAGNOSTICS — not the fleet (FS-398).
    #
    # `totalVehicles` was this same set, so the two figures were equal by construction and
    # a client rendering "N of M vehicles have issues" would always show all of them. A
    # healthy fleet would have reported `totalVehicles: 0`.
    #
    # It is REMOVED rather than corrected, because this endpoint cannot know the fleet size:
    # `GeoTabDiagnostic.vehicle_id` is a bare `String(100)` with no foreign key to
    # `vehicles`, so the two identifier spaces are not joinable here and counting rows in
    # `vehicles` would be a guess dressed as a total. An endpoint should not publish a figure
    # it cannot compute — the same call FS-346 made about the compliance report's four.
    vehicles = {d.vehicle_id for d in diags if d.vehicle_id}
    return {
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
    """Security exceptions for one vehicle.

    THE PATH SAYS VEHICLE AND THE FILTER MEANT DEVICE (FS-404). This passed the path's
    `vehicle_id` straight to `_exceptions(device_id=...)`, and there are THREE identifier
    spaces in this subsystem, none of them interchangeable:

        vehicles.id                      3ca4146e-…  (UUID)
        geotab_diagnostics.vehicle_id    TRK-114     (the vehicle number)
        geotab_*.device_id               gt-device-001

    `GET /fleet/health` — the list a UI renders and picks a row from — publishes
    `vehicleId: TRK-114`. So the only identifier a caller HAS returned nothing, and the only
    one that worked (`gt-device-001`) is not exposed by any endpoint. Measured: UUID -> 0
    events, TRK-114 -> 0, gt-device-001 -> 2.

    `geotab_diagnostics` carries both columns and is already used as exactly this bridge by
    `fleet_health()` above, which builds a `device_to_vehicle` map from it. The same bridge
    is walked in the other direction here.

    A device id still works. That is deliberate rather than lazy: it is the identifier this
    endpoint has always accepted, and silently rejecting it would break any caller that had
    worked out the trick.
    """
    device_ids = await _device_ids_for(db, org_id, vehicle_id)
    # ONE query with an IN clause, not one per device. `test_fleet_health_query_shape`
    # asserts this filter is pushed into SQL rather than applied in Python, and it caught
    # the first version of this fix, which looped and issued a query each time.
    events = await _exceptions(db, org_id, device_ids=device_ids)
    return [_security_out(e) for e in events]


# --------------------------------------------------------------- driver safety

#: Exception types that count as a seatbelt violation. GeoTab spells this differently
#: across firmware versions, and `geotab_exceptions.exception_type` is a free-form string —
#: so a set, not an equality. Missing a spelling under-counts a safety figure, which is the
#: direction that looks like good news.
SEATBELT_EXCEPTION_TYPES = frozenset({"seatbelt", "seat_belt", "seatbelt_violation"})


def _counts_by_driver(exceptions) -> dict:
    by_driver: dict = defaultdict(lambda: defaultdict(int))
    for e in exceptions:
        if e.driver_id:
            by_driver[str(e.driver_id)][e.exception_type] += 1
    return by_driver


@router.get("/safety/drivers", response_model=List[DriverSafetyItem])
async def driver_safety(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    drivers = (await db.execute(select(Driver).where(Driver.organization_id == org_id))).scalars().all()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=SAFETY_WINDOW_DAYS)
    previous_start = window_start - timedelta(days=SAFETY_WINDOW_DAYS)

    current = _counts_by_driver(await _exceptions(db, org_id, since=window_start))
    # The window before this one, for `trend`. Fetched whole and split rather than issued
    # per driver — `test_fleet_health_query_shape.py` asserts these reads do not loop.
    earlier = _counts_by_driver(
        [
            e for e in await _exceptions(db, org_id, since=previous_start)
            if e.timestamp is not None and e.timestamp < window_start
        ]
    )
    return [
        _driver_safety_out(d, current[str(d.id)], earlier[str(d.id)]) for d in drivers
    ]


def _safety_score(counts: dict) -> int:
    harsh = counts.get("harsh_braking", 0) + counts.get("harsh_acceleration", 0)
    return max(0, 100 - harsh * 5 - counts.get("speeding", 0) * 8)


def _driver_safety_out(d: Driver, counts: dict, previous: dict | None = None) -> dict:
    harsh_b = counts.get("harsh_braking", 0)
    harsh_a = counts.get("harsh_acceleration", 0)
    speeding = counts.get("speeding", 0)
    seatbelt = sum(counts.get(t, 0) for t in SEATBELT_EXCEPTION_TYPES)
    score = _safety_score(counts)

    # `trend` compares this window's score with the one before it. None when the previous
    # window is empty: with nothing to compare against, "stable" is a claim rather than an
    # observation — which is what it was for every driver, always.
    trend = None
    if previous:
        before = _safety_score(previous)
        trend = "improving" if score > before else "worsening" if score < before else "stable"

    return {
        "driverId": str(d.id), "driverName": f"{d.first_name} {d.last_name}".strip(),
        "overallScore": score, "harshBrakingEvents": harsh_b,
        "harshAccelerationEvents": harsh_a, "speedingEvents": speeding,
        # None, not 0. `geotab_exceptions` records events and has no duration column, so
        # there is nothing here to compute idle HOURS from. A zero would be a measurement.
        "idleTimeHours": None,
        "seatbeltViolations": seatbelt,
        "period": f"{SAFETY_WINDOW_DAYS}d",
        "trend": trend,
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
    # Windowed and split exactly as the list route is (FS-533). These two handlers share
    # `_driver_safety_out`, so a period applied in one and not the other would have the
    # same driver scoring differently on the list and on their own page — the shape FS-492
    # named, where one caller reads a private copy of what another computes.
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=SAFETY_WINDOW_DAYS)
    previous_start = window_start - timedelta(days=SAFETY_WINDOW_DAYS)

    counts: dict = defaultdict(int)
    previous: dict = defaultdict(int)
    for e in await _exceptions(db, org_id, since=previous_start):
        if str(e.driver_id) != driver_id or e.timestamp is None:
            continue
        (counts if e.timestamp >= window_start else previous)[e.exception_type] += 1
    return _driver_safety_out(d, counts, previous)


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
