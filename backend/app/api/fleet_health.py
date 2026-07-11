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
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.middleware.tenant_isolation import get_tenant_org_id, get_tenant_db
from app.db.models import GeoTabDiagnostic, GeoTabException, GeoTabTrip, Driver, Shipment
from app.db.logistics_models import GeofenceZone

router = APIRouter(dependencies=[Depends(get_current_active_user)])

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


async def _active_diagnostics(db, org_id):
    return (await db.execute(
        select(GeoTabDiagnostic).where(
            GeoTabDiagnostic.organization_id == org_id,
            GeoTabDiagnostic.status == "active",
        )
    )).scalars().all()


async def _exceptions(db, org_id):
    return (await db.execute(
        select(GeoTabException).where(GeoTabException.organization_id == org_id)
    )).scalars().all()


# ---------------------------------------------------------------- health / DTCs

@router.get("/health")
async def fleet_health(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    diags = await _active_diagnostics(db, org_id)
    excs = await _exceptions(db, org_id)
    by_vehicle_dtc = defaultdict(list)
    for d in diags:
        if d.vehicle_id:
            by_vehicle_dtc[d.vehicle_id].append(d)
    exc_by_vehicle = defaultdict(int)
    for e in excs:
        # exceptions carry device_id; treat it as the vehicle key when present
        exc_by_vehicle[e.device_id] += 1

    out = []
    for vid, dtcs in by_vehicle_dtc.items():
        penalty = {"critical": 30, "high": 20, "medium": 10, "low": 5}
        score = max(0, 100 - sum(penalty.get(d.severity, 10) for d in dtcs))
        crit = any(d.severity == "critical" for d in dtcs)
        out.append({
            "vehicleId": vid, "vehicleNumber": vid, "status": "warning" if dtcs else "online",
            "lastCommunication": max((d.last_seen_at for d in dtcs if d.last_seen_at), default=datetime.now(timezone.utc)).isoformat(),
            "dtcs": [_dtc_out(d) for d in dtcs],
            "safetyScore": max(0, 100 - exc_by_vehicle.get(vid, 0) * 5),
            "securityStatus": "alert" if crit else ("warning" if dtcs else "secure"),
            "engineHours": 0, "odometer": 0,
        })
    return out


@router.get("/health/statistics")
async def fleet_health_stats(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    diags = await _active_diagnostics(db, org_id)
    vehicles = {d.vehicle_id for d in diags if d.vehicle_id}
    return {
        "totalVehicles": len(vehicles),
        "activeDtcs": len(diags),
        "criticalDtcs": sum(1 for d in diags if d.severity == "critical"),
        "vehiclesWithIssues": len(vehicles),
    }


@router.get("/health/{vehicle_id}")
async def vehicle_health(vehicle_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    all_health = await fleet_health(org_id, db)
    for v in all_health:
        if v["vehicleId"] == vehicle_id:
            return v
    return {
        "vehicleId": vehicle_id, "vehicleNumber": vehicle_id, "status": "online",
        "lastCommunication": datetime.now(timezone.utc).isoformat(), "dtcs": [],
        "safetyScore": 100, "securityStatus": "secure", "engineHours": 0, "odometer": 0,
    }


@router.get("/dtcs")
async def all_dtcs(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    return [_dtc_out(d) for d in await _active_diagnostics(db, org_id)]


@router.get("/vehicles/{vehicle_id}/dtcs")
async def vehicle_dtcs(vehicle_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    diags = await _active_diagnostics(db, org_id)
    return [_dtc_out(d) for d in diags if d.vehicle_id == vehicle_id]


# ------------------------------------------------------------------- security

def _security_out(e: GeoTabException) -> dict:
    return {
        "id": str(e.id), "vehicleId": e.device_id, "vehicleNumber": e.device_id,
        "eventType": _EVENT.get(e.exception_type, "unusual_route"),
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "severity": e.severity or "medium", "location": e.location or None,
        "description": f"{e.exception_type} event", "acknowledged": bool(e.acknowledged),
    }


@router.get("/security/events")
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


@router.get("/vehicles/{vehicle_id}/security")
async def vehicle_security(vehicle_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    excs = await _exceptions(db, org_id)
    return [_security_out(e) for e in excs if e.device_id == vehicle_id]


# --------------------------------------------------------------- driver safety

@router.get("/safety/drivers")
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


@router.get("/safety/drivers/{driver_id}")
async def one_driver_safety(driver_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    from fastapi import HTTPException
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

@router.get("/vehicles/locations")
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


@router.get("/vehicles/{device_id}/location")
async def vehicle_location(device_id: str, org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    from fastapi import HTTPException
    all_locs = await vehicle_locations(org_id, db)
    for v in all_locs:
        if v["deviceId"] == device_id:
            return v
    raise HTTPException(status_code=404, detail="no location for device")


@router.get("/shipments/active-routes")
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


@router.get("/geofences")
async def fleet_geofences(org_id: UUID = Depends(get_tenant_org_id), db: AsyncSession = Depends(get_tenant_db)):
    zones = (await db.execute(
        select(GeofenceZone).where(GeofenceZone.is_active == True)  # noqa: E712
    )).scalars().all()
    sev_color = {"info": "green", "warning": "yellow", "critical": "red"}
    return [{
        "id": str(z.id), "name": z.name,
        "type": "polygon" if z.polygon else "circle",
        "center": {"latitude": z.center_lat, "longitude": z.center_lng} if z.center_lat is not None else None,
        "radius": z.radius_meters, "coordinates": z.polygon or [],
        "color": sev_color.get(z.severity, "green"), "description": None,
    } for z in zones]
