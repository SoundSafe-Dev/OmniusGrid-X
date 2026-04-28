"""
Yard Management API Endpoints (YMS)
Trailer tracking, dock scheduling, yard operations
"""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import (
    YardTrailer, DockDoor, YardMove, DriverWaitTime, 
    DockAppointment, YardCheckPoint
)
from app.models.schemas import (
    YardTrailerCreate, YardTrailerUpdate, YardTrailerResponse,
    DockDoorCreate, DockDoorUpdate, DockDoorResponse,
    YardMoveCreate, YardMoveResponse,
    DriverWaitTimeCreate, DriverWaitTimeResponse,
    DockAppointmentCreate, DockAppointmentUpdate, DockAppointmentResponse,
    YardCheckPointCreate, YardCheckPointResponse,
    DwellTimeAnalytics
)
from app.services.yard_management import (
    yard_management_service, dock_scheduler, DetentionCalculator
)
from app.api.auth import get_current_active_user

router = APIRouter(
    prefix="/yard",
    tags=["yard_management"],
    dependencies=[Depends(get_current_active_user)],
)


# ==================== Yard Trailer Endpoints ====================

@router.post("/trailers/checkin", response_model=YardTrailerResponse)
async def trailer_check_in(
    data: YardTrailerCreate,
    db: AsyncSession = Depends(get_db)
):
    """Process trailer check-in to yard"""
    trailer = await yard_management_service.check_in_trailer(
        organization_id=data.organization_id,
        trailer_number=data.trailer_number,
        carrier_id=data.carrier_id,
        driver_id=data.driver_id,
        shipment_id=data.shipment_id,
        trailer_type=data.trailer_type,
        seal_number=data.seal_number,
        weight_lbs=data.weight_lbs,
        db=db
    )
    return trailer


@router.post("/trailers/{trailer_id}/checkout", response_model=dict)
async def trailer_check_out(
    trailer_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Process trailer check-out from yard"""
    try:
        result = await yard_management_service.check_out_trailer(
            trailer_id=trailer_id,
            db=db
        )
        return {
            "message": "Trailer checked out successfully",
            "trailer_id": str(trailer_id),
            "trailer_number": result['trailer'].trailer_number
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/trailers", response_model=List[YardTrailerResponse])
async def get_yard_inventory(
    organization_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status: checked_in, docked, yard"),
    db: AsyncSession = Depends(get_db)
):
    """Get current yard inventory"""
    trailers = await yard_management_service.get_yard_inventory(
        organization_id=organization_id,
        status=status,
        db=db
    )
    return trailers


@router.get("/trailers/{trailer_id}", response_model=YardTrailerResponse)
async def get_trailer(
    trailer_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get trailer details"""
    from sqlalchemy import select
    result = await db.execute(
        select(YardTrailer).where(YardTrailer.id == trailer_id)
    )
    trailer = result.scalar_one_or_none()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    return trailer


@router.put("/trailers/{trailer_id}", response_model=YardTrailerResponse)
async def update_trailer(
    trailer_id: UUID,
    data: YardTrailerUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update trailer information"""
    from sqlalchemy import select
    result = await db.execute(
        select(YardTrailer).where(YardTrailer.id == trailer_id)
    )
    trailer = result.scalar_one_or_none()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(trailer, field, value)
    
    trailer.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(trailer)
    return trailer


# ==================== Dock Door Endpoints ====================

@router.post("/dock/doors", response_model=DockDoorResponse)
async def create_dock_door(
    data: DockDoorCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create new dock door"""
    door = DockDoor(**data.model_dump())
    db.add(door)
    await db.commit()
    await db.refresh(door)
    return door


@router.get("/dock/doors", response_model=List[DockDoorResponse])
async def get_dock_doors(
    organization_id: UUID,
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Get all dock doors"""
    from sqlalchemy import select
    query = select(DockDoor).where(DockDoor.organization_id == organization_id)
    if status:
        query = query.where(DockDoor.status == status)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/dock/doors/{door_id}/assign/{trailer_id}", response_model=dict)
async def assign_trailer_to_dock(
    door_id: UUID,
    trailer_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Assign trailer to dock door"""
    try:
        result = await yard_management_service.assign_dock_door(
            trailer_id=trailer_id,
            dock_door_id=door_id,
            db=db
        )
        return {
            "message": "Trailer assigned to dock",
            "dock_door_id": str(door_id),
            "trailer_id": str(trailer_id),
            "door_number": result['dock_door'].door_number
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Dock Appointment Endpoints ====================

@router.post("/dock/appointments", response_model=DockAppointmentResponse)
async def create_dock_appointment(
    data: DockAppointmentCreate,
    db: AsyncSession = Depends(get_db)
):
    """Schedule dock appointment"""
    try:
        appointment = await dock_scheduler.schedule_appointment(
            organization_id=data.organization_id,
            dock_door_id=data.dock_door_id,
            scheduled_start=data.scheduled_start,
            scheduled_end=data.scheduled_end,
            appointment_type=data.appointment_type,
            carrier_id=data.carrier_id,
            trailer_id=data.trailer_id,
            shipment_id=data.shipment_id,
            operation_id=data.operation_id,
            priority=data.priority,
            db=db
        )
        return appointment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dock/appointments", response_model=List[DockAppointmentResponse])
async def get_dock_schedule(
    organization_id: UUID,
    start_date: datetime = Query(default_factory=lambda: datetime.utcnow()),
    end_date: Optional[datetime] = Query(None),
    dock_door_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get dock schedule for date range"""
    if not end_date:
        end_date = start_date + timedelta(days=1)
    
    appointments = await dock_scheduler.get_dock_schedule(
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        dock_door_id=dock_door_id,
        db=db
    )
    return appointments


@router.post("/dock/appointments/{appointment_id}/start", response_model=DockAppointmentResponse)
async def start_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Mark appointment as started"""
    try:
        appointment = await dock_scheduler.start_appointment(
            appointment_id=appointment_id,
            db=db
        )
        return appointment
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/dock/appointments/{appointment_id}/complete", response_model=DockAppointmentResponse)
async def complete_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Mark appointment as completed"""
    try:
        appointment = await dock_scheduler.complete_appointment(
            appointment_id=appointment_id,
            db=db
        )
        return appointment
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== Yard Move Endpoints ====================

@router.post("/moves", response_model=YardMoveResponse)
async def record_yard_move(
    data: YardMoveCreate,
    db: AsyncSession = Depends(get_db)
):
    """Record yard jockey move"""
    move = await yard_management_service.record_yard_move(
        organization_id=data.organization_id,
        trailer_id=data.trailer_id,
        from_location=data.from_location,
        to_location=data.to_location,
        move_type=data.move_type or 'yard_relocate',
        jockey_driver_id=data.jockey_driver_id,
        db=db
    )
    return move


@router.post("/moves/{move_id}/complete", response_model=YardMoveResponse)
async def complete_yard_move(
    move_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Complete yard move"""
    try:
        move = await yard_management_service.complete_yard_move(
            move_id=move_id,
            db=db
        )
        return move
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== Driver Wait Time Endpoints ====================

@router.get("/dwell-times", response_model=List[DwellTimeAnalytics])
async def get_dwell_time_analytics(
    organization_id: UUID,
    start_date: datetime = Query(default_factory=lambda: datetime.utcnow() - timedelta(days=7)),
    end_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Get dwell time analytics"""
    if not end_date:
        end_date = datetime.utcnow()
    
    analytics = await yard_management_service.get_dwell_time_analytics(
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        db=db
    )
    return analytics


@router.post("/driver-wait-times", response_model=DriverWaitTimeResponse)
async def create_driver_wait_time(
    data: DriverWaitTimeCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create driver wait time record"""
    wait_time = await yard_management_service.create_driver_wait_time(
        organization_id=data.organization_id,
        driver_id=data.driver_id,
        trailer_id=data.trailer_id,
        check_in_at=data.check_in_at,
        detention_rate=data.detention_rate,
        demurrage_rate=data.demurrage_rate,
        db=db
    )
    return wait_time


# ==================== Checkpoint Endpoints ====================

@router.post("/checkpoints", response_model=YardCheckPointResponse)
async def record_checkpoint(
    data: YardCheckPointCreate,
    db: AsyncSession = Depends(get_db)
):
    """Record trailer checkpoint passage"""
    checkpoint = await yard_management_service.record_checkpoint(
        organization_id=data.organization_id,
        trailer_id=data.trailer_id,
        checkpoint_type=data.checkpoint_type,
        checkpoint_name=data.checkpoint_name,
        weight_lbs=data.weight_lbs,
        inspection_status=data.inspection_status,
        db=db
    )
    return checkpoint
