"""Alarms API Routes"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from types import SimpleNamespace
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.pagination import PaginatedResponse, paginate
from app.db.database import get_db
from app.db.models import Alarm, Asset
from app.models.schemas import AlarmCreate, AlarmResponse, AlarmAcknowledge
from app.middleware.rbac import require_operator_or_admin

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get("/", response_model=PaginatedResponse[AlarmResponse], summary="List alarms", description="Retrieve a paginated list of alarms with optional filtering by asset, severity, acknowledgment status, and time range. Defaults to last 24 hours if no time range specified. Returns a {items, meta} envelope with the true total count.")
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
        query = query.where(Alarm.occurred_at >= datetime.now(timezone.utc) - timedelta(hours=24))
    
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    query = query.order_by(Alarm.occurred_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return paginate(result.scalars().all(), total, SimpleNamespace(skip=skip, limit=limit))


@router.get("/active", summary="List active alarms", description="Retrieve all currently active (unacknowledged) alarms with severity-based ordering. Used for real-time monitoring dashboards.")
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


@router.get("/{alarm_id}", response_model=AlarmResponse, summary="Get alarm details", description="Retrieve detailed information about a specific alarm including its history, acknowledgment status, and related asset.")
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


@router.post("/{alarm_id}/acknowledge", summary="Acknowledge alarm", description="Mark an alarm as acknowledged with optional notes. Acknowledged alarms remain active but are tracked as reviewed by an operator.", dependencies=[Depends(require_operator_or_admin)])
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
    alarm.acknowledged_at = datetime.now(timezone.utc)
    alarm.acknowledged_comment = ack_data.comment
    
    await db.commit()
    await db.refresh(alarm)
    
    return alarm


@router.post("/{alarm_id}/clear", summary="Clear alarm", description="Mark an alarm as resolved/cleared. This should only be done when the underlying issue has been fixed.", dependencies=[Depends(require_operator_or_admin)])
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
    alarm.cleared_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(alarm)
    
    return alarm


@router.post("/acknowledge-all", summary="Acknowledge all active alarms", description="Bulk acknowledge all currently active alarms, optionally filtered by asset and severity. Used during shift handover or after maintenance.", dependencies=[Depends(require_operator_or_admin)])
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
    
    now = datetime.now(timezone.utc)
    for alarm in alarms:
        alarm.is_acknowledged = True
        alarm.acknowledged_by = user_id
        alarm.acknowledged_at = now
    
    await db.commit()
    
    return {
        "acknowledged_count": len(alarms),
        "message": f"Acknowledged {len(alarms)} alarms"
    }
