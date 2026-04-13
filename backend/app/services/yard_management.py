"""
Yard Management System (YMS)
Trailer tracking, dock scheduling, detention calculation, and yard optimization
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from uuid import UUID
import structlog
from sqlalchemy import text, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.db.models import (
    YardTrailer, DockDoor, YardMove, DriverWaitTime,
    YardCheckPoint, DockAppointment
)

logger = structlog.get_logger()


class DetentionCalculator:
    """Calculate detention and demurrage charges"""
    
    DEFAULT_DETENTION_RATE = 50.0  # $50/hour
    DEFAULT_DEMURRAGE_RATE = 75.0  # $75/hour
    FREE_TIME_MINUTES = 120  # 2 hours free
    
    @staticmethod
    def calculate_detention(
        check_in_at: datetime,
        unloaded_at: Optional[datetime],
        check_out_at: Optional[datetime],
        hourly_rate: float = DEFAULT_DETENTION_RATE,
        free_minutes: int = FREE_TIME_MINUTES
    ) -> Dict[str, Any]:
        """Calculate detention charges (time at dock/facility)"""
        if not unloaded_at:
            return {
                'detention_minutes': 0,
                'detention_charge': 0.0,
                'is_detention': False
            }
        
        end_time = check_out_at or datetime.utcnow()
        total_minutes = (end_time - check_in_at).total_seconds() / 60
        
        if total_minutes <= free_minutes:
            return {
                'detention_minutes': 0,
                'detention_charge': 0.0,
                'is_detention': False
            }
        
        detention_minutes = total_minutes - free_minutes
        detention_hours = detention_minutes / 60
        detention_charge = round(detention_hours * hourly_rate, 2)
        
        return {
            'detention_minutes': round(detention_minutes, 2),
            'detention_charge': detention_charge,
            'is_detention': True,
            'free_time_used': free_minutes,
            'hourly_rate': hourly_rate
        }
    
    @staticmethod
    def calculate_demurrage(
        docked_at: Optional[datetime],
        unloaded_at: Optional[datetime],
        hourly_rate: float = DEFAULT_DEMURRAGE_RATE,
        free_minutes: int = 60
    ) -> Dict[str, Any]:
        """Calculate demurrage charges (time to unload after docked)"""
        if not docked_at or not unloaded_at:
            return {
                'demurrage_minutes': 0,
                'demurrage_charge': 0.0,
                'is_demurrage': False
            }
        
        total_minutes = (unloaded_at - docked_at).total_seconds() / 60
        
        if total_minutes <= free_minutes:
            return {
                'demurrage_minutes': 0,
                'demurrage_charge': 0.0,
                'is_demurrage': False
            }
        
        demurrage_minutes = total_minutes - free_minutes
        demurrage_hours = demurrage_minutes / 60
        demurrage_charge = round(demurrage_hours * hourly_rate, 2)
        
        return {
            'demurrage_minutes': round(demurrage_minutes, 2),
            'demurrage_charge': demurrage_charge,
            'is_demurrage': True,
            'free_time_used': free_minutes,
            'hourly_rate': hourly_rate
        }


class YardManagementService:
    """Core yard management operations"""
    
    def __init__(self):
        self.detention_calculator = DetentionCalculator()
    
    async def check_in_trailer(
        self,
        organization_id: UUID,
        trailer_number: str,
        carrier_id: Optional[UUID] = None,
        driver_id: Optional[UUID] = None,
        shipment_id: Optional[UUID] = None,
        trailer_type: Optional[str] = None,
        seal_number: Optional[str] = None,
        weight_lbs: Optional[float] = None,
        db: Optional[AsyncSession] = None
    ) -> YardTrailer:
        """Process trailer check-in to yard"""
        async with (db or AsyncSessionLocal()) as session:
            trailer = YardTrailer(
                organization_id=organization_id,
                trailer_number=trailer_number,
                carrier_id=carrier_id,
                driver_id=driver_id,
                shipment_id=shipment_id,
                trailer_type=trailer_type,
                seal_number=seal_number,
                weight_lbs=weight_lbs,
                status='checked_in',
                check_in_at=datetime.utcnow()
            )
            session.add(trailer)
            await session.commit()
            await session.refresh(trailer)
            
            logger.info(
                "trailer_checked_in",
                trailer_id=str(trailer.id),
                trailer_number=trailer_number,
                organization_id=str(organization_id)
            )
            return trailer
    
    async def assign_dock_door(
        self,
        trailer_id: UUID,
        dock_door_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Assign trailer to dock door and update statuses"""
        async with (db or AsyncSessionLocal()) as session:
            # Get trailer and door
            trailer_result = await session.execute(
                select(YardTrailer).where(YardTrailer.id == trailer_id)
            )
            trailer = trailer_result.scalar_one_or_none()
            
            door_result = await session.execute(
                select(DockDoor).where(DockDoor.id == dock_door_id)
            )
            door = door_result.scalar_one_or_none()
            
            if not trailer or not door:
                raise ValueError("Trailer or dock door not found")
            
            if door.status == 'occupied':
                raise ValueError(f"Dock door {door.door_number} is already occupied")
            
            # Update statuses
            trailer.status = 'docked'
            trailer.dock_door_id = dock_door_id
            trailer.yard_location = f"DOCK_{door.door_number}"
            
            door.status = 'occupied'
            door.current_trailer_id = trailer_id
            door.last_occupied_at = datetime.utcnow()
            
            # Create yard move record
            move = YardMove(
                organization_id=trailer.organization_id,
                trailer_id=trailer_id,
                from_location='yard',
                to_location=f"DOCK_{door.door_number}",
                move_type='dock',
                started_at=datetime.utcnow()
            )
            session.add(move)
            
            # Update driver wait time if exists
            wait_time_result = await session.execute(
                select(DriverWaitTime).where(
                    and_(
                        DriverWaitTime.trailer_id == trailer_id,
                        DriverWaitTime.check_out_at.is_(None)
                    )
                )
            )
            wait_time = wait_time_result.scalar_one_or_none()
            if wait_time:
                wait_time.docked_at = datetime.utcnow()
            
            await session.commit()
            
            logger.info(
                "trailer_assigned_to_dock",
                trailer_id=str(trailer_id),
                dock_door_id=str(dock_door_id),
                door_number=door.door_number
            )
            
            return {
                'trailer': trailer,
                'dock_door': door,
                'move': move
            }
    
    async def record_yard_move(
        self,
        organization_id: UUID,
        trailer_id: UUID,
        from_location: str,
        to_location: str,
        move_type: str,
        jockey_driver_id: Optional[UUID] = None,
        db: Optional[AsyncSession] = None
    ) -> YardMove:
        """Record a yard jockey move"""
        async with (db or AsyncSessionLocal()) as session:
            move = YardMove(
                organization_id=organization_id,
                trailer_id=trailer_id,
                from_location=from_location,
                to_location=to_location,
                move_type=move_type,
                jockey_driver_id=jockey_driver_id,
                started_at=datetime.utcnow()
            )
            session.add(move)
            await session.commit()
            await session.refresh(move)
            
            # Update trailer location
            trailer_result = await session.execute(
                select(YardTrailer).where(YardTrailer.id == trailer_id)
            )
            trailer = trailer_result.scalar_one_or_none()
            if trailer:
                trailer.yard_location = to_location
                await session.commit()
            
            logger.info(
                "yard_move_recorded",
                move_id=str(move.id),
                trailer_id=str(trailer_id),
                from_location=from_location,
                to_location=to_location
            )
            return move
    
    async def complete_yard_move(
        self,
        move_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> YardMove:
        """Mark yard move as completed"""
        async with (db or AsyncSessionLocal()) as session:
            result = await session.execute(
                select(YardMove).where(YardMove.id == move_id)
            )
            move = result.scalar_one_or_none()
            
            if not move:
                raise ValueError("Yard move not found")
            
            move.completed_at = datetime.utcnow()
            move.duration_seconds = (
                move.completed_at - move.started_at
            ).total_seconds()
            
            await session.commit()
            await session.refresh(move)
            return move
    
    async def check_out_trailer(
        self,
        trailer_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Process trailer check-out from yard"""
        async with (db or AsyncSessionLocal()) as session:
            result = await session.execute(
                select(YardTrailer).where(YardTrailer.id == trailer_id)
            )
            trailer = result.scalar_one_or_none()
            
            if not trailer:
                raise ValueError("Trailer not found")
            
            # Free up dock door if assigned
            if trailer.dock_door_id:
                door_result = await session.execute(
                    select(DockDoor).where(DockDoor.id == trailer.dock_door_id)
                )
                door = door_result.scalar_one_or_none()
                if door:
                    door.status = 'available'
                    door.current_trailer_id = None
            
            # Update trailer status
            trailer.status = 'checked_out'
            trailer.check_out_at = datetime.utcnow()
            trailer.dock_door_id = None
            
            # Create check-out move
            move = YardMove(
                organization_id=trailer.organization_id,
                trailer_id=trailer_id,
                from_location=trailer.yard_location or 'yard',
                to_location='gate_out',
                move_type='check_out',
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
            session.add(move)
            
            # Calculate and record detention
            await self._finalize_wait_time(session, trailer)
            
            await session.commit()
            
            logger.info(
                "trailer_checked_out",
                trailer_id=str(trailer_id),
                trailer_number=trailer.trailer_number,
                dwell_hours=self._calculate_dwell_hours(trailer)
            )
            
            return {
                'trailer': trailer,
                'move': move
            }
    
    async def _finalize_wait_time(self, session: AsyncSession, trailer: YardTrailer):
        """Finalize driver wait time and calculate charges"""
        result = await session.execute(
            select(DriverWaitTime).where(
                and_(
                    DriverWaitTime.trailer_id == trailer.id,
                    DriverWaitTime.check_out_at.is_(None)
                )
            )
        )
        wait_time = result.scalar_one_or_none()
        
        if wait_time and trailer.driver_id:
            wait_time.check_out_at = datetime.utcnow()
            
            # Calculate detention
            detention = self.detention_calculator.calculate_detention(
                check_in_at=wait_time.check_in_at,
                unloaded_at=wait_time.unloaded_at,
                check_out_at=wait_time.check_out_at,
                hourly_rate=wait_time.detention_rate or DetentionCalculator.DEFAULT_DETENTION_RATE
            )
            
            # Calculate demurrage
            demurrage = self.detention_calculator.calculate_demurrage(
                docked_at=wait_time.docked_at,
                unloaded_at=wait_time.unloaded_at,
                hourly_rate=wait_time.demurrage_rate or DetentionCalculator.DEFAULT_DEMURRAGE_RATE
            )
            
            wait_time.total_wait_minutes = (
                wait_time.check_out_at - wait_time.check_in_at
            ).total_seconds() / 60
            wait_time.detention_minutes = detention['detention_minutes']
            wait_time.detention_charge = detention['detention_charge']
            wait_time.demurrage_minutes = demurrage['demurrage_minutes']
            wait_time.demurrage_charge = demurrage['demurrage_charge']
    
    def _calculate_dwell_hours(self, trailer: YardTrailer) -> float:
        """Calculate total dwell time in hours"""
        end_time = trailer.check_out_at or datetime.utcnow()
        return round((end_time - trailer.check_in_at).total_seconds() / 3600, 2)
    
    async def get_yard_inventory(
        self,
        organization_id: UUID,
        status: Optional[str] = None,
        db: Optional[AsyncSession] = None
    ) -> List[YardTrailer]:
        """Get current yard inventory"""
        async with (db or AsyncSessionLocal()) as session:
            query = select(YardTrailer).where(
                and_(
                    YardTrailer.organization_id == organization_id,
                    YardTrailer.status != 'checked_out'
                )
            )
            
            if status:
                query = query.where(YardTrailer.status == status)
            
            result = await session.execute(query)
            return result.scalars().all()
    
    async def get_dwell_time_analytics(
        self,
        organization_id: UUID,
        start_date: datetime,
        end_date: datetime,
        db: Optional[AsyncSession] = None
    ) -> List[Dict[str, Any]]:
        """Get dwell time analytics for date range"""
        async with (db or AsyncSessionLocal()) as session:
            query = text("""
                SELECT 
                    yt.id as trailer_id,
                    yt.trailer_number,
                    yt.check_in_at,
                    yt.check_out_at,
                    COALESCE(
                        EXTRACT(EPOCH FROM (yt.check_out_at - yt.check_in_at)) / 3600,
                        EXTRACT(EPOCH FROM (NOW() - yt.check_in_at)) / 3600
                    ) as dwell_hours,
                    CASE 
                        WHEN dwt.detention_charge > 0 THEN true 
                        ELSE false 
                    END as is_detention,
                    dwt.detention_charge
                FROM yard_trailers yt
                LEFT JOIN driver_wait_times dwt ON dwt.trailer_id = yt.id
                WHERE yt.organization_id = :org_id
                AND yt.check_in_at >= :start_date
                AND yt.check_in_at <= :end_date
                ORDER BY yt.check_in_at DESC
            """)
            
            result = await session.execute(
                query,
                {
                    'org_id': str(organization_id),
                    'start_date': start_date,
                    'end_date': end_date
                }
            )
            
            rows = result.fetchall()
            return [
                {
                    'trailer_id': row.trailer_id,
                    'trailer_number': row.trailer_number,
                    'check_in_at': row.check_in_at,
                    'check_out_at': row.check_out_at,
                    'dwell_hours': round(float(row.dwell_hours or 0), 2),
                    'is_detention': row.is_detention,
                    'detention_charge': float(row.detention_charge or 0)
                }
                for row in rows
            ]
    
    async def create_driver_wait_time(
        self,
        organization_id: UUID,
        driver_id: UUID,
        trailer_id: Optional[UUID] = None,
        check_in_at: Optional[datetime] = None,
        detention_rate: Optional[float] = None,
        demurrage_rate: Optional[float] = None,
        db: Optional[AsyncSession] = None
    ) -> DriverWaitTime:
        """Create driver wait time record at check-in"""
        async with (db or AsyncSessionLocal()) as session:
            wait_time = DriverWaitTime(
                organization_id=organization_id,
                driver_id=driver_id,
                trailer_id=trailer_id,
                check_in_at=check_in_at or datetime.utcnow(),
                detention_rate=detention_rate or DetentionCalculator.DEFAULT_DETENTION_RATE,
                demurrage_rate=demurrage_rate or DetentionCalculator.DEFAULT_DEMURRAGE_RATE
            )
            session.add(wait_time)
            await session.commit()
            await session.refresh(wait_time)
            return wait_time
    
    async def record_checkpoint(
        self,
        organization_id: UUID,
        trailer_id: UUID,
        checkpoint_type: str,
        checkpoint_name: Optional[str] = None,
        weight_lbs: Optional[float] = None,
        inspection_status: Optional[str] = None,
        db: Optional[AsyncSession] = None
    ) -> YardCheckPoint:
        """Record trailer passing a checkpoint"""
        async with (db or AsyncSessionLocal()) as session:
            checkpoint = YardCheckPoint(
                organization_id=organization_id,
                trailer_id=trailer_id,
                checkpoint_type=checkpoint_type,
                checkpoint_name=checkpoint_name,
                weight_lbs=weight_lbs,
                inspection_status=inspection_status,
                passed_at=datetime.utcnow()
            )
            session.add(checkpoint)
            await session.commit()
            await session.refresh(checkpoint)
            
            logger.info(
                "checkpoint_recorded",
                checkpoint_id=str(checkpoint.id),
                trailer_id=str(trailer_id),
                checkpoint_type=checkpoint_type
            )
            return checkpoint


class DockScheduler:
    """Dock door scheduling and optimization"""
    
    def __init__(self):
        self.yard_service = YardManagementService()
    
    async def schedule_appointment(
        self,
        organization_id: UUID,
        dock_door_id: UUID,
        scheduled_start: datetime,
        scheduled_end: datetime,
        appointment_type: str,
        carrier_id: Optional[UUID] = None,
        trailer_id: Optional[UUID] = None,
        shipment_id: Optional[UUID] = None,
        operation_id: Optional[UUID] = None,
        priority: str = 'normal',
        db: Optional[AsyncSession] = None
    ) -> DockAppointment:
        """Schedule a dock appointment"""
        async with (db or AsyncSessionLocal()) as session:
            # Check for conflicts
            conflicts = await self._check_conflicts(
                session, dock_door_id, scheduled_start, scheduled_end
            )
            
            if conflicts:
                raise ValueError(
                    f"Dock door conflict: {len(conflicts)} overlapping appointments"
                )
            
            appointment = DockAppointment(
                organization_id=organization_id,
                dock_door_id=dock_door_id,
                trailer_id=trailer_id,
                shipment_id=shipment_id,
                operation_id=operation_id,
                appointment_type=appointment_type,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                carrier_id=carrier_id,
                priority=priority
            )
            session.add(appointment)
            await session.commit()
            await session.refresh(appointment)
            
            logger.info(
                "dock_appointment_scheduled",
                appointment_id=str(appointment.id),
                dock_door_id=str(dock_door_id),
                scheduled_start=scheduled_start.isoformat()
            )
            return appointment
    
    async def _check_conflicts(
        self,
        session: AsyncSession,
        dock_door_id: UUID,
        start: datetime,
        end: datetime,
        exclude_id: Optional[UUID] = None
    ) -> List[DockAppointment]:
        """Check for scheduling conflicts"""
        query = select(DockAppointment).where(
            and_(
                DockAppointment.dock_door_id == dock_door_id,
                DockAppointment.status.in_(['scheduled', 'in_progress']),
                or_(
                    and_(
                        DockAppointment.scheduled_start <= start,
                        DockAppointment.scheduled_end > start
                    ),
                    and_(
                        DockAppointment.scheduled_start < end,
                        DockAppointment.scheduled_end >= end
                    ),
                    and_(
                        DockAppointment.scheduled_start >= start,
                        DockAppointment.scheduled_end <= end
                    )
                )
            )
        )
        
        if exclude_id:
            query = query.where(DockAppointment.id != exclude_id)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    async def get_dock_schedule(
        self,
        organization_id: UUID,
        start_date: datetime,
        end_date: datetime,
        dock_door_id: Optional[UUID] = None,
        db: Optional[AsyncSession] = None
    ) -> List[DockAppointment]:
        """Get dock schedule for date range"""
        async with (db or AsyncSessionLocal()) as session:
            query = select(DockAppointment).where(
                and_(
                    DockAppointment.organization_id == organization_id,
                    DockAppointment.scheduled_start >= start_date,
                    DockAppointment.scheduled_start <= end_date
                )
            )
            
            if dock_door_id:
                query = query.where(DockAppointment.dock_door_id == dock_door_id)
            
            result = await session.execute(query.order_by(DockAppointment.scheduled_start))
            return result.scalars().all()
    
    async def start_appointment(
        self,
        appointment_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> DockAppointment:
        """Mark appointment as started"""
        async with (db or AsyncSessionLocal()) as session:
            result = await session.execute(
                select(DockAppointment).where(DockAppointment.id == appointment_id)
            )
            appointment = result.scalar_one_or_none()
            
            if not appointment:
                raise ValueError("Appointment not found")
            
            appointment.status = 'in_progress'
            appointment.actual_start = datetime.utcnow()
            
            await session.commit()
            await session.refresh(appointment)
            return appointment
    
    async def complete_appointment(
        self,
        appointment_id: UUID,
        db: Optional[AsyncSession] = None
    ) -> DockAppointment:
        """Mark appointment as completed"""
        async with (db or AsyncSessionLocal()) as session:
            result = await session.execute(
                select(DockAppointment).where(DockAppointment.id == appointment_id)
            )
            appointment = result.scalar_one_or_none()
            
            if not appointment:
                raise ValueError("Appointment not found")
            
            appointment.status = 'completed'
            appointment.actual_end = datetime.utcnow()
            
            await session.commit()
            await session.refresh(appointment)
            return appointment
    
    async def find_optimal_dock(
        self,
        organization_id: UUID,
        scheduled_start: datetime,
        scheduled_end: datetime,
        equipment_requirements: Optional[List[str]] = None,
        db: Optional[AsyncSession] = None
    ) -> Optional[UUID]:
        """Find optimal available dock door"""
        async with (db or AsyncSessionLocal()) as session:
            # Get all active doors
            doors_result = await session.execute(
                select(DockDoor).where(
                    and_(
                        DockDoor.organization_id == organization_id,
                        DockDoor.is_active == True
                    )
                )
            )
            doors = doors_result.scalars().all()
            
            for door in doors:
                conflicts = await self._check_conflicts(
                    session, door.id, scheduled_start, scheduled_end
                )
                if not conflicts:
                    # Check equipment capabilities
                    if equipment_requirements:
                        capabilities = door.equipment_capabilities or {}
                        if all(req in capabilities for req in equipment_requirements):
                            return door.id
                    else:
                        return door.id
            
            return None


# Global instances
yard_management_service = YardManagementService()
dock_scheduler = DockScheduler()
