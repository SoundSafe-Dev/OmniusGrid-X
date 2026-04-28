"""Alarms API Routes"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Alarm, Asset
from app.api.auth import get_current_active_user
from app.models.schemas import AlarmCreate, AlarmResponse, AlarmAcknowledge

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get("/", response_model=List[AlarmResponse])
async def list_alarms(
    asset_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    severity: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """List alarms with filtering"""
    query = select(Alarm)
    
    if asset_id:
        query = query.where(Alarm.asset_id == asset_id)
    if is_active is not None:
        query = query.where(Alarm.is_active == is_active)
    if severity:
        query = query.where(Alarm.severity == severity)
    if acknowledged is not None:
        query = query.where(Alarm.is_acknowledged == acknowledged)
    if start_time:
        query = query.where(Alarm.occurred_at >= start_time)
    if end_time:
        query = query.where(Alarm.occurred_at <= end_time)
    
    # Default to last 24 hours if no time range
    if not start_time and not end_time:
        query = query.where(Alarm.occurred_at >= datetime.utcnow() - timedelta(hours=24))
    
    query = query.order_by(Alarm.occurred_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    alarms = result.scalars().all()
    
    return alarms


@router.get("/active")
async def get_active_alarms(
    organization_id: Optional[UUID] = None,
    severity: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get active (unacknowledged) alarms"""
    query = select(Alarm).where(
        and_(
            Alarm.is_active == True,
            Alarm.is_acknowledged == False
        )
    )
    
    if organization_id:
        query = query.join(Asset).where(Asset.organization_id == organization_id)
    if severity:
        query = query.where(Alarm.severity == severity)
    
    query = query.order_by(
        # Order by severity: critical first
        Alarm.severity,
        Alarm.occurred_at.desc()
    )
    
    result = await db.execute(query)
    alarms = result.scalars().all()
    
    return {
        "count": len(alarms),
        "by_severity": {
            "critical": len([a for a in alarms if a.severity == "critical"]),
            "high": len([a for a in alarms if a.severity == "high"]),
            "medium": len([a for a in alarms if a.severity == "medium"]),
            "low": len([a for a in alarms if a.severity == "low"]),
        },
        "alarms": alarms
    }


@router.get("/{alarm_id}", response_model=AlarmResponse)
async def get_alarm(
    alarm_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single alarm by ID"""
    result = await db.execute(
        select(Alarm).where(Alarm.id == alarm_id)
    )
    alarm = result.scalar_one_or_none()
    
    if not alarm:
        raise HTTPException(status_code=404, detail="Alarm not found")
    
    return alarm


@router.post("/{alarm_id}/acknowledge")
async def acknowledge_alarm(
    alarm_id: UUID,
    ack_data: AlarmAcknowledge,
    user_id: UUID = None,  # Would come from auth dependency
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge an alarm"""
    result = await db.execute(
        select(Alarm).where(Alarm.id == alarm_id)
    )
    alarm = result.scalar_one_or_none()
    
    if not alarm:
        raise HTTPException(status_code=404, detail="Alarm not found")
    
    if alarm.is_acknowledged:
        raise HTTPException(status_code=400, detail="Alarm already acknowledged")
    
    alarm.is_acknowledged = True
    alarm.acknowledged_by = user_id
    alarm.acknowledged_at = datetime.utcnow()
    alarm.acknowledged_comment = ack_data.comment
    
    await db.commit()
    await db.refresh(alarm)
    
    return alarm


@router.post("/{alarm_id}/clear")
async def clear_alarm(
    alarm_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Mark an alarm as cleared"""
    result = await db.execute(
        select(Alarm).where(Alarm.id == alarm_id)
    )
    alarm = result.scalar_one_or_none()
    
    if not alarm:
        raise HTTPException(status_code=404, detail="Alarm not found")
    
    alarm.is_active = False
    alarm.cleared_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(alarm)
    
    return alarm


@router.post("/acknowledge-all")
async def acknowledge_all_alarms(
    asset_id: Optional[UUID] = None,
    severity: Optional[str] = None,
    user_id: UUID = None,
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge all active alarms matching criteria"""
    query = select(Alarm).where(
        and_(
            Alarm.is_active == True,
            Alarm.is_acknowledged == False
        )
    )
    
    if asset_id:
        query = query.where(Alarm.asset_id == asset_id)
    if severity:
        query = query.where(Alarm.severity == severity)
    
    result = await db.execute(query)
    alarms = result.scalars().all()
    
    now = datetime.utcnow()
    for alarm in alarms:
        alarm.is_acknowledged = True
        alarm.acknowledged_by = user_id
        alarm.acknowledged_at = now
    
    await db.commit()
    
    return {
        "acknowledged_count": len(alarms),
        "message": f"Acknowledged {len(alarms)} alarms"
    }
