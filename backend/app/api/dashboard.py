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
    
    # Calculate OEE components
    total_time = hours * 3600
    execute_time = state_durations.get('Execute', 0)
    
    # Availability = Execute time / Planned production time
    availability = execute_time / total_time if total_time > 0 else 0
    
    # Performance and Quality would need additional data
    # Placeholder: assume ideal performance and 100% quality for now
    performance = 1.0
    quality = 1.0
    
    # OEE = Availability × Performance × Quality
    oee = availability * performance * quality
    
    return {
        "asset_id": str(asset_id),
        "asset_name": asset.name,
        "time_range": f"Last {hours} hours",
        "availability": round(availability, 4),
        "performance": round(performance, 4),
        "quality": round(quality, 4),
        "oee": round(oee, 4),
        "state_durations": state_durations,
        "total_planned_time_seconds": total_time
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
    
    oee_results = []
    
    for asset in assets:
        # Query state durations for this asset
        result = await db.execute(
            select(
                func.sum(PackMLState.duration_seconds)
            )
            .where(
                PackMLState.asset_id == asset.id,
                PackMLState.state == 'Execute',
                PackMLState.state_entered_at >= start_time,
                PackMLState.state_entered_at <= end_time
            )
        )
        execute_time = result.scalar() or 0
        
        total_time = hours * 3600
        availability = execute_time / total_time if total_time > 0 else 0
        
        oee_results.append({
            "asset_id": str(asset.id),
            "asset_name": asset.name,
            "availability": round(availability, 4),
            "oee": round(availability, 4)  # Simplified: availability = OEE for now
        })
    
    # Calculate fleet averages
    avg_availability = sum(r["availability"] for r in oee_results) / len(oee_results) if oee_results else 0
    avg_oee = sum(r["oee"] for r in oee_results) / len(oee_results) if oee_results else 0
    
    return {
        "time_range": f"Last {hours} hours",
        "asset_count": len(assets),
        "fleet_average_availability": round(avg_availability, 4),
        "fleet_average_oee": round(avg_oee, 4),
        "assets": oee_results
    }
