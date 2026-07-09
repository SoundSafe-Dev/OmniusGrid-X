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

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.logistics_models import (
    GeofenceAlert,
    GeofenceZone,
    MaintenanceSchedule,
    RepairOrder,
)
from app.db.models import Carrier, Driver, Shipment

logger = structlog.get_logger()

geofencing_router = APIRouter(tags=["Geofencing"])
maintenance_router = APIRouter(tags=["Fleet Maintenance"])
logistics_router = APIRouter(tags=["Transportation Management"])


# ==================== Geofencing ====================

def _zone_out(z: GeofenceZone) -> Dict[str, Any]:
    return {
        "id": str(z.id), "name": z.name, "zoneType": z.zone_type,
        "center": {"lat": z.center_lat, "lng": z.center_lng},
        "radiusMeters": z.radius_meters, "polygon": z.polygon,
        "triggerOn": z.trigger_on, "severity": z.severity, "isActive": z.is_active,
    }


@geofencing_router.get("/zones")
async def list_zones(db: AsyncSession = Depends(get_db)):
    zones = (await db.execute(
        select(GeofenceZone).where(GeofenceZone.is_active == True)  # noqa: E712
    )).scalars().all()
    return [_zone_out(z) for z in zones]


@geofencing_router.post("/zones")
async def create_zone(payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    if not payload.get("name"):
        raise HTTPException(status_code=400, detail="name is required")
    center = payload.get("center") or {}
    zone = GeofenceZone(
        organization_id=payload.get("organization_id"),
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
async def update_zone(zone_id: str, payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    zone = (await db.execute(select(GeofenceZone).where(GeofenceZone.id == zone_id))).scalar_one_or_none()
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
async def delete_zone(zone_id: str, db: AsyncSession = Depends(get_db)):
    zone = (await db.execute(select(GeofenceZone).where(GeofenceZone.id == zone_id))).scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail="zone not found")
    zone.is_active = False  # soft delete
    await db.commit()
    return {"message": "zone deleted"}


@geofencing_router.get("/alerts")
async def list_alerts(
    acknowledged: Optional[bool] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    query = select(GeofenceAlert).order_by(GeofenceAlert.created_at.desc()).limit(limit)
    if acknowledged is not None:
        query = query.where(GeofenceAlert.acknowledged == acknowledged)
    if severity:
        query = query.where(GeofenceAlert.severity == severity)
    alerts = (await db.execute(query)).scalars().all()
    return [{
        "id": str(a.id), "zoneId": a.zone_id, "vehicleId": a.vehicle_id,
        "eventType": a.event_type, "severity": a.severity, "location": a.location or {},
        "acknowledged": a.acknowledged,
        "createdAt": a.created_at.isoformat() if a.created_at else None,
    } for a in alerts]


@geofencing_router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, db: AsyncSession = Depends(get_db)):
    alert = (await db.execute(select(GeofenceAlert).where(GeofenceAlert.id == alert_id))).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    alert.acknowledged = True
    alert.acknowledged_at = datetime.utcnow()
    await db.commit()
    return {"message": "acknowledged", "id": alert_id}


# ==================== Maintenance ====================

@maintenance_router.get("/schedules")
async def list_schedules(
    status: Optional[str] = Query(None),
    vehicle_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(MaintenanceSchedule)
    now = datetime.utcnow()
    if status == "overdue":
        query = query.where(
            MaintenanceSchedule.status.in_(("scheduled", "overdue")),
            MaintenanceSchedule.due_date < now,
        )
    elif status:
        query = query.where(MaintenanceSchedule.status == status)
    if vehicle_id:
        query = query.where(MaintenanceSchedule.vehicle_id == vehicle_id)
    schedules = (await db.execute(query.order_by(MaintenanceSchedule.due_date.asc()))).scalars().all()
    return [{
        "id": str(s.id), "vehicleId": s.vehicle_id, "maintenanceType": s.maintenance_type,
        "description": s.description,
        "dueDate": s.due_date.isoformat() if s.due_date else None,
        "dueOdometer": s.due_odometer_miles,
        "status": "overdue" if (s.status in ("scheduled", "overdue") and s.due_date and s.due_date < now) else s.status,
        "estimatedCost": s.estimated_cost,
    } for s in schedules]


@maintenance_router.post("/schedules")
async def create_schedule(payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    if not payload.get("vehicleId") and not payload.get("vehicle_id"):
        raise HTTPException(status_code=400, detail="vehicleId is required")
    schedule = MaintenanceSchedule(
        organization_id=payload.get("organization_id"),
        vehicle_id=payload.get("vehicleId") or payload.get("vehicle_id"),
        maintenance_type=payload.get("maintenanceType") or payload.get("maintenance_type") or "inspection",
        description=payload.get("description"),
        due_date=datetime.fromisoformat(payload["dueDate"]) if payload.get("dueDate") else None,
        due_odometer_miles=payload.get("dueOdometer"),
        estimated_cost=payload.get("estimatedCost"),
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return {"id": str(schedule.id), "status": schedule.status}


@maintenance_router.get("/repair-orders")
async def list_repair_orders(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(RepairOrder)
    if status == "active":
        query = query.where(RepairOrder.status.in_(("open", "in_progress", "awaiting_parts")))
    elif status:
        query = query.where(RepairOrder.status == status)
    orders = (await db.execute(query.order_by(RepairOrder.opened_at.desc()))).scalars().all()
    return [{
        "id": str(o.id), "vehicleId": o.vehicle_id, "title": o.title,
        "status": o.status, "priority": o.priority, "vendor": o.vendor,
        "cost": o.cost, "category": o.category,
        "openedAt": o.opened_at.isoformat() if o.opened_at else None,
    } for o in orders]


@maintenance_router.post("/repair-orders")
async def create_repair_order(payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    if not (payload.get("vehicleId") or payload.get("vehicle_id")) or not payload.get("title"):
        raise HTTPException(status_code=400, detail="vehicleId and title are required")
    order = RepairOrder(
        organization_id=payload.get("organization_id"),
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
    now = now or datetime.utcnow()
    overdue = [
        s for s in schedules
        if getattr(s, "status", None) in ("scheduled", "overdue")
        and getattr(s, "due_date", None) and s.due_date < now
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
    return {
        "scheduledCount": sum(1 for s in schedules if getattr(s, "status", None) == "scheduled"),
        "overdueCount": len(overdue),
        "activeRepairs": len(active),
        "ytdCosts": round(sum(float(o.cost) for o in ytd), 2),
        "costsByCategory": by_category,
    }


@maintenance_router.get("/statistics")
async def maintenance_statistics(db: AsyncSession = Depends(get_db)):
    schedules = (await db.execute(select(MaintenanceSchedule))).scalars().all()
    orders = (await db.execute(select(RepairOrder))).scalars().all()
    return summarize_maintenance(schedules, orders)


@maintenance_router.get("/costs")
async def maintenance_costs(db: AsyncSession = Depends(get_db)):
    orders = (await db.execute(select(RepairOrder))).scalars().all()
    summary = summarize_maintenance([], orders)
    return {"ytdTotal": summary["ytdCosts"], "byCategory": summary["costsByCategory"]}


# ==================== Logistics aggregates ====================

@logistics_router.get("/delivery-efficiency")
async def delivery_efficiency(db: AsyncSession = Depends(get_db)):
    from app.api.transportation import compute_delivery_efficiency

    shipments = (await db.execute(select(Shipment))).scalars().all()
    return compute_delivery_efficiency(shipments)


@logistics_router.get("/compliance/summary")
async def compliance_summary(db: AsyncSession = Depends(get_db)):
    """Org-wide carrier/driver compliance rollup for the Compliance tab."""
    carriers = (await db.execute(select(Carrier).where(Carrier.is_active == True))).scalars().all()  # noqa: E712
    drivers = (await db.execute(select(Driver).where(Driver.is_active == True))).scalars().all()  # noqa: E712
    now = datetime.utcnow()
    hos_violations = sum(
        1 for d in drivers
        if (d.hos_drive_hours_today or 0) >= 11 or (d.hos_cycle_hours or 0) >= 70
    )
    expiring_soon = sum(
        1 for c in carriers
        if c.insurance_expires_at and (c.insurance_expires_at - now).days <= 30
    )
    return {
        "totalCarriers": len(carriers),
        "ctpatCertified": sum(1 for c in carriers if c.ctpat_certified),
        "activeViolations": hos_violations,
        "safetyAlerts": expiring_soon,
    }
