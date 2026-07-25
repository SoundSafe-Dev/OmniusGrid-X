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
    current_user = Depends(get_current_active_user)
):
    """
    Get current OEE metrics for an asset.
    
    Calculates OEE from PackML state history:
    - Availability: Production time vs planned time
    - Performance: Ideal vs actual cycle time
    - Quality: Good parts vs total parts
    """
    # Verify asset access
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Asset).where(Asset.id == asset_id)
        )
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
    current_user = Depends(get_current_active_user)
):
    """
    Get historical OEE data with aggregation.
    
    - hourly: Per-hour averages
    - daily: Per-day averages
    - shift: Per-8-hour-shift averages
    """
    # Verify asset access
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Asset).where(Asset.id == asset_id)
        )
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
        except Exception:
            summary.append({
                "asset_id": str(asset.id),
                "asset_name": asset.name,
                "oee": 0,
                "availability": 0,
                "performance": 0,
                "quality": 0,
                "runtime_minutes": 0,
                "status": "no_data"
            })
    
    # Calculate aggregate
    if summary:
        avg_oee = sum(s['oee'] for s in summary) / len(summary)
        avg_availability = sum(s['availability'] for s in summary) / len(summary)
        avg_performance = sum(s['performance'] for s in summary) / len(summary)
        avg_quality = sum(s['quality'] for s in summary) / len(summary)
    else:
        avg_oee = avg_availability = avg_performance = avg_quality = 0
    
    return {
        "organization_id": str(current_user.organization_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "aggregate": {
            "avg_oee": round(avg_oee, 2),
            "avg_availability": round(avg_availability, 2),
            "avg_performance": round(avg_performance, 2),
            "avg_quality": round(avg_quality, 2),
            "asset_count": len(summary)
        },
        "assets": summary
    }


@router.get("/losses/{asset_id}")
async def get_oee_losses(
    asset_id: str,
    hours: int = Query(default=8, ge=1, le=72),
    current_user = Depends(get_current_active_user)
):
    """
    Get OEE loss breakdown for an asset.
    
    Shows where OEE losses are occurring:
    - Availability losses (downtime)
    - Performance losses (speed)
    - Quality losses (defects)
    """
    # Verify asset access
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Asset).where(Asset.id == asset_id)
        )
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
