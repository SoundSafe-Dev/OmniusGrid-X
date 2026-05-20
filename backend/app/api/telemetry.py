"""Telemetry API Routes"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Telemetry, Asset, PackMLState
from app.api.auth import get_current_active_user

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get("/{asset_id}/latest")
async def get_latest_telemetry(
    asset_id: UUID,
    metric_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get latest telemetry for an asset"""
    # Verify asset exists
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Build query
    query = select(Telemetry).where(Telemetry.asset_id == asset_id)
    
    if metric_name:
        query = query.where(Telemetry.metric_name == metric_name)
    
    query = query.order_by(Telemetry.time.desc()).limit(1)
    result = await db.execute(query)
    latest = result.scalar_one_or_none()
    
    if not latest:
        return {"message": "No telemetry data found"}
    
    return {
        "asset_id": str(asset_id),
        "timestamp": latest.time.isoformat(),
        "metric_name": latest.metric_name,
        "value": float(latest.value),
        "unit": latest.unit,
        "packml_state": latest.packml_state,
        "metadata": latest.meta_data
    }


@router.get("/{asset_id}/history")
async def get_telemetry_history(
    asset_id: UUID,
    metric_name: Optional[str] = None,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    aggregation: Optional[str] = Query(None, enum=["1min", "5min", "1hour"]),
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """Get telemetry history for an asset"""
    # Set default time range if not provided
    if not end_time:
        end_time = datetime.utcnow()
    if not start_time:
        start_time = end_time - timedelta(hours=24)
    
    # Verify asset exists
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Asset not found")
    
    if aggregation:
        # Use continuous aggregate table for aggregated data
        # This would query telemetry_1min view
        pass
    else:
        # Raw data query
        query = select(Telemetry).where(
            Telemetry.asset_id == asset_id,
            Telemetry.time >= start_time,
            Telemetry.time <= end_time
        )
        
        if metric_name:
            query = query.where(Telemetry.metric_name == metric_name)
        
        query = query.order_by(Telemetry.time.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        telemetry_data = result.scalars().all()
        
        return [
            {
                "timestamp": t.time.isoformat(),
                "metric_name": t.metric_name,
                "value": float(t.value),
                "unit": t.unit,
                "packml_state": t.packml_state,
                "metadata": t.meta_data
            }
            for t in telemetry_data
        ]


@router.get("/{asset_id}/metrics")
async def get_available_metrics(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get list of available metrics for an asset"""
    result = await db.execute(
        select(Telemetry.metric_name)
        .where(Telemetry.asset_id == asset_id)
        .distinct()
    )
    metrics = result.scalars().all()
    
    return {
        "asset_id": str(asset_id),
        "metrics": list(metrics)
    }
