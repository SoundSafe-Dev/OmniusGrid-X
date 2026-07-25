"""Dashboard & OEE API Routes"""

from typing import List, Optional
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
    base_query = select(Asset).where(Asset.organization_id == org_id)

    # Total assets
    result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total_assets = result.scalar()

    # Active assets
    result = await db.execute(
        select(func.count())
        .select_from(base_query.where(Asset.is_active == True).subquery())
    )
    active_assets = result.scalar()

    # Assets by PackML state
    state_query = (
        select(Asset.current_packml_state, func.count())
        .where(Asset.organization_id == org_id)
        .group_by(Asset.current_packml_state)
    )
    result = await db.execute(state_query)
    assets_by_state = {state: count for state, count in result.all()}

    # Active alarms
    alarms_query = (
        select(Alarm)
        .join(Asset, Alarm.asset_id == Asset.id)
        .where(Alarm.is_active == True, Asset.organization_id == org_id)
    )

    result = await db.execute(
        select(func.count()).select_from(alarms_query.subquery())
    )
    active_alarms = result.scalar()
    
    # Critical alarms
    result = await db.execute(
        select(func.count())
        .select_from(
            alarms_query.where(Alarm.severity == "critical").subquery()
        )
    )
    critical_alarms = result.scalar()
    
    return DashboardOverview(
        total_assets=total_assets,
        active_assets=active_assets,
        assets_by_state=assets_by_state,
        active_alarms=active_alarms,
        critical_alarms=critical_alarms
    )


@router.get("/workcells/{workcell_id}/status")
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


@router.get("/assets/{asset_id}/oee")
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


@router.get("/fleet/oee")
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

    avg_availability = (
        sum(r["availability"] for r in oee_results) / len(oee_results)
        if oee_results else 0
    )

    return {
        "time_range": f"Last {hours} hours",
        "asset_count": len(assets),
        "fleet_average_availability": round(avg_availability, 4),
        # `fleet_average_oee` used to be this same availability number. Callers
        # wanting a fleet OEE trend should use /api/v1/dashboard/oee/trend,
        # which is explicit about being availability-only.
        "availability_only": True,
        "assets": oee_results,
    }
