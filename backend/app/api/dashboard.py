"""Dashboard & OEE API Routes"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import Asset, Alarm, PackMLState, Organization, Telemetry
from app.models.schemas import DashboardOverview, OEEMetrics
from app.services.oee_calculator import oee_calculator

router = APIRouter(dependencies=[Depends(get_current_active_user)])


class WorkcellAssetStatus(BaseModel):
    id: str
    name: str
    current_packml_state: Optional[str] = None
    is_active: Optional[bool] = None
    last_seen: Optional[str] = None


class WorkcellStatusOut(BaseModel):
    workcell_id: str
    asset_count: int
    assets: List[WorkcellAssetStatus]


class AssetOEEOut(BaseModel):
    """Three real factors, and two flags saying whether two of them were MEASURED.

    This endpoint used to hardcode `performance = quality = 1.0` and serve availability
    under the name `oee`. It now delegates to `oee_calculator`, and `quality_measured` /
    `performance_measured` exist because 1.0 is the neutral multiplier for an absent
    factor — correct arithmetic, and the wrong thing to print as "100%".
    """

    asset_id: str
    asset_name: str
    time_range: str
    #: 0–1 RATIOS on this endpoint. `oee_calculator` returns percentages and the handler
    #: divides; `/api/v1/oee/*` serves the same quantities as percentages.
    availability: float
    performance: float
    quality: float
    oee: float
    quality_measured: bool
    performance_measured: bool
    total_parts: Optional[int] = None
    good_parts: Optional[int] = None
    #: PackML state -> summed seconds, keyed by whatever states the asset reported.
    state_durations: Dict[str, float] = Field(default_factory=dict)
    total_planned_time_seconds: int


class FleetAssetAvailability(BaseModel):
    asset_id: str
    asset_name: str
    availability: float
    #: Always True. Availability alone is not OEE, and the old code served this exact
    #: number under the key `oee`, which overstated every asset in the fleet.
    availability_only: bool


class FleetOEEOut(BaseModel):
    time_range: str
    asset_count: int
    #: `None`, not 0, for a fleet with nothing to average — 0% availability renders as a
    #: fleet-wide outage, and an average of nothing is not zero.
    fleet_average_availability: Optional[float] = None
    assets_measured: int
    availability_only: bool
    assets: List[FleetAssetAvailability]



def _summarise_assets(rows) -> tuple[dict, int, int]:
    """Histogram, total and active count, from ONE grouped pass.

    Extracted so the derivation can be tested against a population that includes the case
    that matters: an asset whose `current_packml_state` is NULL. Postgres groups NULL as
    its own group, so the sum of the histogram is the same population `COUNT(*)` counted —
    but only while the query has no predicate excluding it, and an HTTP test against an
    empty fixture cannot tell the difference. It was vacuous when first written (FS-879).
    """
    histogram = {state: total for state, total, _ in rows}
    return (
        histogram,
        sum(total for _, total, _ in rows),
        sum(active for _, _, active in rows),
    )


@router.get("/overview", response_model=DashboardOverview)
async def get_dashboard_overview(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get dashboard overview metrics for the authenticated user's organization.

    The org comes from the JWT, never from the query string: an earlier version
    took an optional ``organization_id`` query param, which let a caller aim the
    query at another tenant. Scoping is explicit here AND enforced by RLS —
    ``get_tenant_db`` sets the ``app.current_org_id`` GUC the policies read.
    Using ``get_db`` here (which sets no GUC) is what made every tile render 0.
    """
    # Base query — explicit org filter on top of the RLS predicate.
    # FS-879. FIVE ROUND TRIPS BECAME TWO, and the arithmetic is the reason: three of the
    # five queries read `assets` and two read the same `Alarm ⋈ Asset` join, each pair
    # differing only by one predicate. A `FILTER` clause answers a subset in the same pass
    # the superset is already making, so the extra queries were paying a full round trip —
    # and, for the alarms, a full second join — to re-ask a question already in flight.
    #
    # It matters because of who calls this: `Dashboard.tsx:159` polls every 30 seconds PER
    # OPEN TAB, so the cost is five queries × every dashboard anyone has left open, against
    # a connection pool sized at 10 per process (FS-839).
    #
    # NOT SERVED FROM THE CONTINUOUS AGGREGATES, despite what the task pool suggested.
    # `002_continuous_aggregates.sql` rolls up `telemetry` — hourly temperature features and
    # minute performance features. Nothing here is time-series: these are row counts in
    # `assets` and `alarms`, and no aggregate over telemetry can answer them.

    # One pass over `assets`: the state histogram, and the two totals derived from it.
    # Grouping includes the NULL state as its own group, so summing the groups is the same
    # population `COUNT(*)` was counting.
    state_rows = (
        await db.execute(
            select(
                Asset.current_packml_state,
                func.count().label("total"),
                func.count().filter(Asset.is_active == True).label("active"),  # noqa: E712
            )
            .where(Asset.organization_id == org_id)
            .group_by(Asset.current_packml_state)
        )
    ).all()

    assets_by_state, total_assets, active_assets = _summarise_assets(state_rows)

    # One pass over the join: active alarms, and the critical subset of them.
    alarm_counts = (
        await db.execute(
            select(
                func.count().label("active"),
                func.count()
                .filter(Alarm.severity == "critical")
                .label("critical"),
            )
            .select_from(Alarm)
            .join(Asset, Alarm.asset_id == Asset.id)
            .where(Alarm.is_active == True, Asset.organization_id == org_id)  # noqa: E712
        )
    ).one()
    active_alarms = alarm_counts.active
    critical_alarms = alarm_counts.critical
    
    return DashboardOverview(
        total_assets=total_assets,
        active_assets=active_assets,
        assets_by_state=assets_by_state,
        active_alarms=active_alarms,
        critical_alarms=critical_alarms
    )


@router.get("/workcells/{workcell_id}/status", response_model=WorkcellStatusOut)
async def get_workcell_status(
    workcell_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get status for all assets in a workcell"""
    result = await db.execute(
        select(Asset).where(Asset.workcell_id == workcell_id)
    )
    assets = result.scalars().all()
    
    if not assets:
        raise HTTPException(status_code=404, detail="No assets found in workcell")
    
    return {
        "workcell_id": str(workcell_id),
        "asset_count": len(assets),
        "assets": [
            {
                "id": str(a.id),
                "name": a.name,
                "current_packml_state": a.current_packml_state,
                "is_active": a.is_active,
                "last_seen": a.last_seen.isoformat() if a.last_seen else None
            }
            for a in assets
        ]
    }


@router.get("/assets/{asset_id}/oee", response_model=AssetOEEOut)
async def get_asset_oee(
    asset_id: UUID,
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Calculate OEE for an asset over a time period"""
    # Verify asset exists
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Calculate time range
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    
    # Query PackML state durations
    result = await db.execute(
        select(
            PackMLState.state,
            func.sum(PackMLState.duration_seconds)
        )
        .where(
            PackMLState.asset_id == asset_id,
            PackMLState.state_entered_at >= start_time,
            PackMLState.state_entered_at <= end_time
        )
        .group_by(PackMLState.state)
    )
    state_durations = {state: duration or 0 for state, duration in result.all()}
    total_time = hours * 3600

    # Delegate to the real calculator instead of recomputing a crippled version.
    # This endpoint used to hardcode `performance = quality = 1.0` and return
    # availability under the name "oee" — inflating every figure it served.
    # oee_calculator derives performance from the asset's ideal cycle time and
    # quality from good/total part counters, so the three factors are real.
    metrics = await oee_calculator.calculate_oee(str(asset_id), time_window_hours=float(hours))

    return {
        "asset_id": str(asset_id),
        "asset_name": asset.name,
        "time_range": f"Last {hours} hours",
        # calculate_oee returns percentages; keep this endpoint's 0–1 ratios.
        "availability": round(metrics.availability / 100, 4),
        "performance": round(metrics.performance / 100, 4),
        "quality": round(metrics.quality / 100, 4),
        "oee": round(metrics.oee / 100, 4),
        # Whether each factor was actually measured (FS-234). Quality reads 1.0
        # when an asset has no part counters — a neutral multiplier for OEE, but not
        # a measurement. A consumer should render "—" rather than "100%" when this
        # is false.
        "quality_measured": metrics.quality_measured,
        "performance_measured": metrics.performance_measured,
        "total_parts": metrics.total_parts,
        "good_parts": metrics.good_parts,
        "state_durations": state_durations,
        "total_planned_time_seconds": total_time,
    }


@router.get("/fleet/oee", response_model=FleetOEEOut)
async def get_fleet_oee(
    hours: int = Query(24, ge=1, le=168),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get OEE metrics for the authenticated user's fleet.

    Org comes from the JWT — the old optional ``organization_id`` query param
    let a caller read another tenant's fleet.
    """
    query = select(Asset).where(
        Asset.is_active == True, Asset.organization_id == org_id
    )

    result = await db.execute(query)
    assets = result.scalars().all()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    total_time = hours * 3600

    # One grouped query for the whole fleet. This used to run a SELECT per asset
    # inside the loop below — an N+1 that grew with the fleet.
    run_rows = await db.execute(
        select(PackMLState.asset_id, func.sum(PackMLState.duration_seconds))
        .where(
            PackMLState.asset_id.in_([a.id for a in assets]) if assets else False,
            PackMLState.state == 'Execute',
            PackMLState.state_entered_at >= start_time,
            PackMLState.state_entered_at <= end_time,
        )
        .group_by(PackMLState.asset_id)
    ) if assets else None
    run_seconds = {r[0]: float(r[1] or 0) for r in run_rows.all()} if run_rows else {}

    oee_results = []
    for asset in assets:
        availability = (
            run_seconds.get(asset.id, 0.0) / total_time if total_time > 0 else 0
        )
        oee_results.append({
            "asset_id": str(asset.id),
            "asset_name": asset.name,
            "availability": round(availability, 4),
            # Availability only — NOT full OEE. Performance needs each asset's
            # ideal cycle time and quality needs part counters, neither of which
            # fits one grouped query. Use /api/v1/dashboard/assets/{id}/oee for
            # the real three-factor figure. The old code returned this value
            # under the key "oee", which overstated every asset.
            "availability_only": True,
        })

    # AN AVERAGE OF NOTHING IS NOT ZERO. With no assets in the fleet this returned 0,
    # which renders as 0% availability — a fleet-wide outage, reported because there was
    # nothing to average. `None` cannot be mistaken for a measurement, and
    # `assets_measured` says how many rows the figure rests on.
    avg_availability = (
        sum(r["availability"] for r in oee_results) / len(oee_results)
        if oee_results
        else None
    )

    return {
        "time_range": f"Last {hours} hours",
        "asset_count": len(assets),
        "fleet_average_availability": (
            round(avg_availability, 4) if avg_availability is not None else None
        ),
        "assets_measured": len(oee_results),
        # `fleet_average_oee` used to be this same availability number. Callers
        # wanting a fleet OEE trend should use /api/v1/dashboard/oee/trend,
        # which is explicit about being availability-only.
        "availability_only": True,
        "assets": oee_results,
    }
