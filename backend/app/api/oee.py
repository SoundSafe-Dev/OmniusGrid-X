"""API routes for OEE (Overall Equipment Effectiveness)"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db, AsyncSessionLocal
from app.core.tenant import get_tenant_db
from app.db.models import Asset
from app.api.auth import get_current_active_user
from app.services.oee_calculator import oee_calculator, OEEMetrics

import structlog

logger = structlog.get_logger()

router = APIRouter()


class OEEResponse(BaseModel):
    """OEE metrics response"""
    asset_id: str
    timestamp: str
    availability: float = Field(..., ge=0, le=100, description="Percentage")
    performance: float = Field(..., ge=0, le=100, description="Percentage")
    quality: float = Field(..., ge=0, le=100, description="Percentage")
    oee: float = Field(..., ge=0, le=100, description="Overall OEE percentage")
    runtime_minutes: float
    planned_downtime_minutes: float
    unplanned_downtime_minutes: float
    total_parts: int
    good_parts: int
    rejected_parts: int


class OEEHistoricalRequest(BaseModel):
    """Request for historical OEE data"""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    hours: int = Field(default=24, ge=1, le=168)
    aggregation: str = Field(default="hourly", pattern="^(hourly|daily|shift)$")


@router.get("/current/{asset_id}", response_model=OEEResponse)
async def get_current_oee(
    asset_id: str,
    time_window_hours: float = Query(default=1.0, ge=0.5, le=24),
    current_user = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Get current OEE metrics for an asset.
    
    Calculates OEE from PackML state history:
    - Availability: Production time vs planned time
    - Performance: Ideal vs actual cycle time
    - Quality: Good parts vs total parts
    """
    # `assets` is FORCE ROW LEVEL SECURITY (migration 011), and AsyncSessionLocal sets
    # no app.current_org_id — so this lookup used to return None for EVERY asset,
    # including the caller's own, and answered 404 to a request about an asset that
    # plainly exists. Verified against a real database before the fix. get_tenant_db
    # binds the GUC, which is what makes the row visible.
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset or asset.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Calculate OEE
    oee = await oee_calculator.calculate_oee(asset_id, time_window_hours)
    
    return {
        "asset_id": asset_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "availability": oee.availability,
        "performance": oee.performance,
        "quality": oee.quality,
        "oee": oee.oee,
        "runtime_minutes": oee.runtime_minutes,
        "planned_downtime_minutes": oee.planned_downtime_minutes,
        "unplanned_downtime_minutes": oee.unplanned_downtime_minutes,
        "total_parts": oee.total_parts,
        "good_parts": oee.good_parts,
        "rejected_parts": oee.rejected_parts
    }


@router.get("/historical/{asset_id}")
async def get_historical_oee(
    asset_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    aggregation: str = Query(default="hourly", pattern="^(hourly|daily|shift)$"),
    current_user = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Get historical OEE data with aggregation.
    
    - hourly: Per-hour averages
    - daily: Per-day averages
    - shift: Per-8-hour-shift averages
    """
    # `assets` is FORCE ROW LEVEL SECURITY (migration 011), and AsyncSessionLocal sets
    # no app.current_org_id — so this lookup used to return None for EVERY asset,
    # including the caller's own, and answered 404 to a request about an asset that
    # plainly exists. Verified against a real database before the fix. get_tenant_db
    # binds the GUC, which is what makes the row visible.
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset or asset.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    
    # Get historical data
    data = await oee_calculator.get_historical_oee(
        asset_id=asset_id,
        start_time=start_time,
        end_time=end_time,
        aggregation=aggregation
    )
    
    return {
        "asset_id": asset_id,
        "aggregation": aggregation,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "data": data
    }


@router.get("/dashboard/summary")
async def get_oee_dashboard_summary(
    current_user = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db)
):
    """
    Get OEE summary for all assets in organization.
    Used for dashboard overview.
    """
    # Get all assets for user
    result = await db.execute(
        select(Asset).where(
            Asset.organization_id == current_user.organization_id,
            Asset.is_active == True
        )
    )
    assets = result.scalars().all()
    
    summary = []
    for asset in assets:
        try:
            oee = await oee_calculator.calculate_oee(str(asset.id), time_window_hours=1.0)
            summary.append({
                "asset_id": str(asset.id),
                "asset_name": asset.name,
                "oee": oee.oee,
                "availability": oee.availability,
                "performance": oee.performance,
                "quality": oee.quality,
                "runtime_minutes": oee.runtime_minutes,
                "status": "healthy" if oee.oee > 60 else "at_risk" if oee.oee > 40 else "critical"
            })
        except Exception as exc:
            # A FAILED CALCULATION IS NOT A MACHINE AT ZERO. This branch used to append
            # oee/availability/performance/quality of 0 with status "no_data", which
            # renders as an asset in total outage — and "no_data" is the wrong word for
            # it either way: an asset that genuinely reported nothing goes through the
            # branch above, so this status was conflating a broken computation with an
            # idle machine. The values are None and the status says what happened.
            logger.warning(
                "oee_summary_asset_failed", asset_id=str(asset.id), error=str(exc)
            )
            summary.append({
                "asset_id": str(asset.id),
                "asset_name": asset.name,
                "oee": None,
                "availability": None,
                "performance": None,
                "quality": None,
                "runtime_minutes": None,
                "status": "unavailable"
            })

    # AND THE AGGREGATE MUST NOT AVERAGE THE PLACEHOLDERS. The old sum divided by
    # `len(summary)`, so every asset whose calculation raised entered the fleet mean as a
    # zero and dragged it down — one broken asset in twenty made the fleet look like it
    # was in a partial outage. Averaging over what was measured is the only mean that
    # means anything; how many that was is now reported rather than left to be inferred.
    measured = [s for s in summary if s["oee"] is not None]

    def _mean(key: str):
        # None, not 0, when nothing was measured. The average of an empty set is not
        # zero — zero is a reading, and a fleet-wide 0% OEE is an emergency.
        if not measured:
            return None
        return round(sum(s[key] for s in measured) / len(measured), 2)

    return {
        "organization_id": str(current_user.organization_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "aggregate": {
            "avg_oee": _mean("oee"),
            "avg_availability": _mean("availability"),
            "avg_performance": _mean("performance"),
            "avg_quality": _mean("quality"),
            "asset_count": len(summary),
            # The two numbers that let a reader tell a healthy fleet from an unread one.
            "assets_measured": len(measured),
            "assets_unavailable": len(summary) - len(measured),
        },
        "assets": summary
    }


@router.get("/losses/{asset_id}")
async def get_oee_losses(
    asset_id: str,
    hours: int = Query(default=8, ge=1, le=72),
    current_user = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Get OEE loss breakdown for an asset.
    
    Shows where OEE losses are occurring:
    - Availability losses (downtime)
    - Performance losses (speed)
    - Quality losses (defects)
    """
    # `assets` is FORCE ROW LEVEL SECURITY (migration 011), and AsyncSessionLocal sets
    # no app.current_org_id — so this lookup used to return None for EVERY asset,
    # including the caller's own, and answered 404 to a request about an asset that
    # plainly exists. Verified against a real database before the fix. get_tenant_db
    # binds the GUC, which is what makes the row visible.
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset or asset.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Get OEE for the period
    oee = await oee_calculator.calculate_oee(asset_id, hours)
    
    # Calculate losses
    availability_loss = 100 - oee.availability
    performance_loss = 100 - oee.performance
    quality_loss = 100 - oee.quality
    
    total_loss = availability_loss + performance_loss + quality_loss
    
    return {
        "asset_id": asset_id,
        "period_hours": hours,
        "oee": oee.oee,
        "losses": {
            "availability": {
                "percentage": availability_loss,
                "minutes": oee.planned_downtime_minutes + oee.unplanned_downtime_minutes,
                "category": "downtime"
            },
            "performance": {
                "percentage": performance_loss,
                "impact": f"Cycle time {oee.actual_cycle_time_seconds}s vs ideal {oee.ideal_cycle_time_seconds}s",
                "category": "speed"
            },
            "quality": {
                "percentage": quality_loss,
                "rejected_parts": oee.rejected_parts,
                "total_parts": oee.total_parts,
                "category": "defects"
            }
        },
        "total_loss_percentage": total_loss,
        "potential_oee": 100 - total_loss
    }
