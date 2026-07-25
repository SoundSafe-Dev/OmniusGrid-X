"""Fleet/logistics KPI endpoints (FS-14).

Real aggregates computed from the tables the platform actually populates:
  - on-time performance  <- shipments (scheduled vs actual delivery)
  - DTC count / systems   <- geotab_diagnostics
  - vehicle health        <- geotab_diagnostics severity
  - idle time / distance  <- geotab_trips

Metrics with no source column (fuel consumed, itemized cost breakdown) are
reported as zero rather than fabricated; the response shape still matches the
frontend contract so the dashboard renders. Responses are snake_case; the web
client camel-cases them via transform.ts.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.middleware.tenant_isolation import get_tenant_org_id, get_tenant_db
from app.db.models import Shipment, GeoTabTrip, GeoTabDiagnostic

router = APIRouter(dependencies=[Depends(get_current_active_user)])


# ---- Response schemas (FS-100). Shapes match what the handlers already return;
# snake_case on the wire, camel-cased by the web client's transform seam.

class FuelEfficiencyResponse(BaseModel):
    fleet_average: float
    unit: str
    best_performers: List[Any]
    worst_performers: List[Any]
    trend: List[Any]
    by_vehicle: Dict[str, Any]
    total_fuel_consumed: float
    total_distance: float


class IdleVehicleStats(BaseModel):
    hours: float
    percentage: float
    cost: float


class IdleTimeResponse(BaseModel):
    total_hours: float
    percentage_of_runtime: float
    cost_impact: float
    by_vehicle: Dict[str, IdleVehicleStats]
    trend: List[Any]


class OnTimePerformanceResponse(BaseModel):
    overall_percentage: float
    on_time_count: int
    late_count: int
    by_carrier: Dict[str, float]
    by_route: Dict[str, Any]
    trend: List[Any]


class VehicleHealthResponse(BaseModel):
    fleet_average: float
    by_vehicle: Dict[str, int]
    critical_count: int
    warning_count: int
    healthy_count: int
    factors: Dict[str, int]


class CostPerMileResponse(BaseModel):
    total_cost: float
    total_miles: float
    average_cost_per_mile: float
    breakdown: Dict[str, float]
    trend: List[Any]


class DtcRecentItem(BaseModel):
    code: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    vehicle_id: Optional[str] = None
    timestamp: Optional[str] = None


class DtcCountResponse(BaseModel):
    total_active: int
    critical_count: int
    by_vehicle: Dict[str, int]
    by_system: Dict[str, int]
    recent: List[DtcRecentItem]
    trend: List[Any]


class KpiDashboardResponse(BaseModel):
    fuel_efficiency: FuelEfficiencyResponse
    idle_time: IdleTimeResponse
    on_time_performance: OnTimePerformanceResponse
    vehicle_health: VehicleHealthResponse
    cost_per_mile: CostPerMileResponse
    dtc_count: DtcCountResponse

# Assumption constant for cost-per-mile until a costing source exists (FS-26).
_COST_PER_MILE_USD = 1.38  # industry-typical all-in operating cost; documented, not fabricated per-row

_RANGE_DAYS = {"today": 1, "week": 7, "month": 30, "quarter": 90, "year": 365, "custom": 30}


def _range_start(time_range: str) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=_RANGE_DAYS.get(time_range, 30))


def _dtc_system(dtc_code: str) -> str:
    """Map an OBD-II DTC prefix to a vehicle system (P=powertrain, C=chassis, ...)."""
    prefix = (dtc_code or "").strip()[:1].upper()
    return {"P": "powertrain", "C": "chassis", "B": "body", "U": "network"}.get(prefix, "other")


@router.get("/fuel-efficiency", response_model=FuelEfficiencyResponse)
async def get_fuel_efficiency(
    range: str = Query("month"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    since = _range_start(range)
    # Only the total distance is used below (per-vehicle fuel isn't collected
    # yet, so by_vehicle is empty), so sum it in SQL instead of loading every
    # trip row. coalesce keeps an all-NULL/no-rows range at 0.0.
    total_distance = float((await db.execute(
        select(func.coalesce(func.sum(GeoTabTrip.distance_miles), 0)).where(
            GeoTabTrip.organization_id == org_id,
            GeoTabTrip.start_time >= since,
        )
    )).scalar() or 0)

    # Fuel consumption is not collected yet, so efficiency cannot be computed.
    return {
        "fleet_average": 0.0,
        "unit": "mpg",
        "best_performers": [],
        "worst_performers": [],
        "trend": [],
        "by_vehicle": {},
        "total_fuel_consumed": 0.0,
        "total_distance": round(total_distance, 1),
    }


@router.get("/idle-time", response_model=IdleTimeResponse)
async def get_idle_time(
    range: str = Query("month"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    since = _range_start(range)
    # One GROUP BY vehicle_id in SQL instead of loading every trip and summing in
    # Python. The dict is still rebuilt Python-side with the same rounding, so
    # the numbers are byte-identical. The NULL-vehicle group is returned too and
    # feeds the totals (as before) but is excluded from the per-vehicle
    # breakdown.
    grouped = (await db.execute(
        select(
            GeoTabTrip.vehicle_id,
            func.coalesce(func.sum(GeoTabTrip.idle_time_seconds), 0),
            func.coalesce(func.sum(GeoTabTrip.duration_seconds), 0),
        ).where(
            GeoTabTrip.organization_id == org_id,
            GeoTabTrip.start_time >= since,
        ).group_by(GeoTabTrip.vehicle_id)
    )).all()

    total_idle_s = 0.0
    total_run_s = 0.0
    by_vehicle = {}
    for vid, idle_sum, run_sum in grouped:
        idle_s = float(idle_sum or 0)
        run_s = float(run_sum or 0)
        total_idle_s += idle_s
        total_run_s += run_s
        if vid:
            denom = run_s or 1
            by_vehicle[vid] = {
                "hours": round(idle_s / 3600, 2),
                "percentage": round(idle_s / denom * 100, 1),
                "cost": round((idle_s / 3600) * _COST_PER_MILE_USD, 2),
            }

    idle_hours = total_idle_s / 3600
    pct = (total_idle_s / total_run_s * 100) if total_run_s else 0.0
    cost = idle_hours * _COST_PER_MILE_USD  # idle cost proxy (per idle hour)

    return {
        "total_hours": round(idle_hours, 2),
        "percentage_of_runtime": round(pct, 1),
        "cost_impact": round(cost, 2),
        "by_vehicle": by_vehicle,
        "trend": [],
    }


@router.get("/on-time-performance", response_model=OnTimePerformanceResponse)
async def get_on_time_performance(
    range: str = Query("month"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    since = _range_start(range)
    # Count on-time vs total per carrier in SQL (GROUP BY) instead of loading
    # every delivered shipment. The WHERE already excludes actual_delivery IS
    # NULL, so the on-time rule reduces to "no schedule, or delivered on/before
    # it" — the same test the Python code applied.
    on_time_expr = case(
        (
            or_(
                Shipment.scheduled_delivery.is_(None),
                Shipment.actual_delivery <= Shipment.scheduled_delivery,
            ),
            1,
        ),
        else_=0,
    )
    grouped = (await db.execute(
        select(
            Shipment.carrier_id,
            func.count(),
            func.coalesce(func.sum(on_time_expr), 0),
        ).where(
            Shipment.organization_id == org_id,
            Shipment.status == "delivered",
            Shipment.actual_delivery.isnot(None),
            Shipment.updated_at >= since,
        ).group_by(Shipment.carrier_id)
    )).all()

    on_time = late = 0
    by_carrier = {}
    for cid, group_total, group_on in grouped:
        group_total = int(group_total or 0)
        group_on = int(group_on or 0)
        on_time += group_on
        late += group_total - group_on
        # The NULL-carrier group feeds the totals above but not the breakdown.
        if cid:
            by_carrier[str(cid)] = (
                round(group_on / group_total * 100, 1) if group_total else 0.0
            )

    total = on_time + late
    return {
        "overall_percentage": round(on_time / total * 100, 1) if total else 0.0,
        "on_time_count": on_time,
        "late_count": late,
        "by_carrier": by_carrier,
        "by_route": {},
        "trend": [],
    }


@router.get("/vehicle-health", response_model=VehicleHealthResponse)
async def get_vehicle_health(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rows = (await db.execute(
        select(GeoTabDiagnostic).where(
            GeoTabDiagnostic.organization_id == org_id,
            GeoTabDiagnostic.status == "active",
        )
    )).scalars().all()

    # Health score per vehicle: 100 minus a weighted penalty for active DTCs.
    penalty = {"critical": 30, "high": 20, "medium": 10, "low": 5}
    score_by_vehicle: dict = defaultdict(lambda: 100)
    for d in rows:
        if d.vehicle_id:
            score_by_vehicle[d.vehicle_id] = max(
                0, score_by_vehicle[d.vehicle_id] - penalty.get(d.severity, 10)
            )

    scores = list(score_by_vehicle.values())
    fleet_avg = round(sum(scores) / len(scores), 1) if scores else 100.0
    critical = sum(1 for s in scores if s < 50)
    warning = sum(1 for s in scores if 50 <= s < 80)
    healthy = sum(1 for s in scores if s >= 80)
    return {
        "fleet_average": fleet_avg,
        "by_vehicle": dict(score_by_vehicle),
        "critical_count": critical,
        "warning_count": warning,
        "healthy_count": healthy,
        "factors": {"dtcs": len(rows), "maintenance": 0, "age": 0, "utilization": 0},
    }


@router.get("/cost-per-mile", response_model=CostPerMileResponse)
async def get_cost_per_mile(
    range: str = Query("month"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    since = _range_start(range)
    # Sum in SQL rather than loading every trip row just to add up distances.
    total_miles = round(float((await db.execute(
        select(func.coalesce(func.sum(GeoTabTrip.distance_miles), 0)).where(
            GeoTabTrip.organization_id == org_id,
            GeoTabTrip.start_time >= since,
        )
    )).scalar() or 0), 1)
    total_cost = round(total_miles * _COST_PER_MILE_USD, 2)
    return {
        "total_cost": total_cost,
        "total_miles": total_miles,
        "average_cost_per_mile": _COST_PER_MILE_USD if total_miles else 0.0,
        "breakdown": {"fuel": 0.0, "maintenance": 0.0, "insurance": 0.0, "other": total_cost},
        "trend": [],
    }


@router.get("/dtc-count", response_model=DtcCountResponse)
async def get_dtc_count(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rows = (await db.execute(
        select(GeoTabDiagnostic).where(
            GeoTabDiagnostic.organization_id == org_id,
            GeoTabDiagnostic.status == "active",
        )
    )).scalars().all()

    by_vehicle = defaultdict(int)
    by_system = defaultdict(int)
    critical = 0
    recent = []
    for d in rows:
        if d.vehicle_id:
            by_vehicle[d.vehicle_id] += 1
        by_system[_dtc_system(d.dtc_code)] += 1
        if d.severity == "critical":
            critical += 1
    # Sort by epoch float so a NULL last_seen_at (or mixed naive/aware datetimes
    # across dialects) never triggers an offset-naive vs aware comparison.
    for d in sorted(rows, key=lambda x: x.last_seen_at.timestamp() if x.last_seen_at else 0.0, reverse=True)[:10]:
        recent.append({
            "code": d.dtc_code,
            "description": d.description,
            "severity": d.severity,
            "vehicle_id": d.vehicle_id,
            "timestamp": d.last_seen_at.isoformat() if d.last_seen_at else None,
        })

    return {
        "total_active": len(rows),
        "critical_count": critical,
        "by_vehicle": dict(by_vehicle),
        "by_system": dict(by_system),
        "recent": recent,
        "trend": [],
    }


@router.get("/dashboard", response_model=KpiDashboardResponse)
async def get_dashboard(
    range: str = Query("month"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Bundle every KPI so the dashboard fetches once."""
    return {
        "fuel_efficiency": await get_fuel_efficiency(range, org_id, db),
        "idle_time": await get_idle_time(range, org_id, db),
        "on_time_performance": await get_on_time_performance(range, org_id, db),
        "vehicle_health": await get_vehicle_health(org_id, db),
        "cost_per_mile": await get_cost_per_mile(range, org_id, db),
        "dtc_count": await get_dtc_count(org_id, db),
    }
