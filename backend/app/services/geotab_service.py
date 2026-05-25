"""
GeoTab Integration Service
Handles fleet telematics, HOS compliance, and vehicle diagnostics
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from uuid import UUID
import structlog
import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import Driver, Carrier, GeoTabTrip, GeoTabDiagnostic, GeoTabException

logger = structlog.get_logger()


class GeoTabService:
    """Service for GeoTab fleet telematics integration"""
    
    def __init__(self):
        # In production, this would connect to actual GeoTab API
        # For now, providing mock implementation
        self.mock_devices = {
            "DEV-001": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-002": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-003": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-004": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-005": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-006": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-007": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-008": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-009": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-010": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-011": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-012": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-013": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-014": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-015": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
            "DEV-088": {"driver_id": None, "status": "active", "last_seen": datetime.utcnow()},
        }
    
    async def get_exceptions(
        self,
        organization_id: UUID,
        driver_id: Optional[UUID] = None,
        exception_type: Optional[str] = None,
        hours_back: int = 24,
        db: AsyncSession = None
    ) -> List[Dict[str, Any]]:
        """Get GeoTab exceptions for fleet"""
        # Mock implementation - in production would call GeoTab API
        exceptions = []
        
        exception_types = ["harsh_braking", "speeding", "hos_violation", "idle_time", "seat_belt"]
        
        # Generate some mock exceptions
        for i in range(random.randint(0, 10)):
            exc_type = exception_type or random.choice(exception_types)
            exceptions.append({
                "exception_id": f"EXC-{random.randint(1000, 9999)}",
                "exception_type": exc_type,
                "device_id": random.choice(list(self.mock_devices.keys())),
                "driver_id": str(driver_id) if driver_id else f"DRV-{random.randint(1, 100)}",
                "timestamp": (datetime.utcnow() - timedelta(hours=random.randint(0, hours_back))).isoformat(),
                "severity": random.choice(["low", "medium", "high", "critical"]),
                "location": {
                    "latitude": round(random.uniform(40.0, 42.0), 6),
                    "longitude": round(random.uniform(-88.0, -86.0), 6)
                },
                "details": {
                    "value": round(random.uniform(0, 100), 2),
                    "threshold": round(random.uniform(0, 100), 2)
                }
            })
        
        return exceptions
    
    async def get_device_diagnostics(
        self,
        device_id: str,
        organization_id: UUID,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Get device diagnostics including DTC codes"""
        if device_id not in self.mock_devices:
            raise ValueError(f"Device {device_id} not found")
        
        # Mock diagnostics data
        dtc_codes = ["P0115", "P0128", "P0171", "P0172", "P0300", "P0420", "P0440", "P0455"]
        
        return {
            "device_id": device_id,
            "status": "active",
            "last_seen": datetime.utcnow().isoformat(),
            "diagnostics": {
                "dtc_codes": random.sample(dtc_codes, random.randint(0, 3)),
                "check_engine_light": random.choice([True, False]),
                "battery_voltage": round(random.uniform(11.5, 14.5), 2),
                "fuel_level": round(random.uniform(0, 100), 1),
                "odometer": random.randint(50000, 200000),
                "engine_hours": round(random.uniform(1000, 10000), 1)
            },
            "reefer_status": {
                "temperature_setpoint": round(random.uniform(-10, 5), 1),
                "temperature_actual": round(random.uniform(-15, 10), 1),
                "status": random.choice(["normal", "warning", "critical"]),
                "defrost_cycle": random.choice([True, False])
            } if device_id in ["DEV-088", "DEV-0044"] else None
        }
    
    async def handle_webhook(
        self,
        webhook_data: Dict[str, Any],
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Handle incoming GeoTab webhook events"""
        event_type = webhook_data.get("type", "unknown")
        device_id = webhook_data.get("device_id")
        
        logger.info(
            "geotab_webhook_received",
            event_type=event_type,
            device_id=device_id
        )
        
        try:
            # Validate webhook data
            if not device_id:
                logger.warning("geotab_webhook_missing_device_id", data=webhook_data)
                return {"processed": False, "error": "Missing device_id"}
            
            # Process different event types
            if event_type == "exception":
                await self._process_exception_webhook(webhook_data, db)
            elif event_type == "status_change":
                await self._process_status_change_webhook(webhook_data, db)
            elif event_type == "location_update":
                await self._process_location_update_webhook(webhook_data, db)
            elif event_type == "diagnostic":
                await self._process_diagnostic_webhook(webhook_data, db)
            else:
                logger.warning("geotab_webhook_unknown_type", event_type=event_type)
            
            return {"processed": True, "event_type": event_type}
            
        except Exception as e:
            logger.error(
                "geotab_webhook_processing_failed",
                event_type=event_type,
                device_id=device_id,
                error=str(e)
            )
            return {"processed": False, "error": str(e)}
    
    async def _process_exception_webhook(self, webhook_data: Dict[str, Any], db: AsyncSession):
        """Process exception event webhook"""
        try:
            exception = GeoTabException(
                device_id=webhook_data.get("device_id"),
                driver_id=webhook_data.get("driver_id"),
                organization_id=webhook_data.get("organization_id"),
                exception_type=webhook_data.get("exception_type"),
                severity=webhook_data.get("severity", "medium"),
                timestamp=datetime.fromisoformat(webhook_data.get("timestamp", datetime.utcnow().isoformat())),
                location=webhook_data.get("location"),
                details=webhook_data.get("details", {})
            )
            
            db.add(exception)
            await db.commit()
            
            logger.info(
                "geotab_exception_stored",
                device_id=webhook_data.get("device_id"),
                exception_type=webhook_data.get("exception_type")
            )
            
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("geotab_exception_store_failed", error=str(e))
            raise
    
    async def _process_status_change_webhook(self, webhook_data: Dict[str, Any], db: AsyncSession):
        """Process status change webhook (e.g., HOS status)"""
        # Update driver HOS status if applicable
        driver_id = webhook_data.get("driver_id")
        if driver_id and db:
            try:
                result = await db.execute(
                    select(Driver).where(Driver.id == driver_id)
                )
                driver = result.scalar_one_or_none()
                if driver:
                    driver.hos_current_status = webhook_data.get("hos_status")
                    driver.hos_drive_hours_today = webhook_data.get("drive_hours_today", driver.hos_drive_hours_today)
                    driver.hos_on_duty_hours_today = webhook_data.get("on_duty_hours_today", driver.hos_on_duty_hours_today)
                    await db.commit()
                    logger.info("geotab_driver_status_updated", driver_id=driver_id)
            except SQLAlchemyError as e:
                await db.rollback()
                logger.error("geotab_status_update_failed", error=str(e))
    
    async def _process_location_update_webhook(self, webhook_data: Dict[str, Any], db: AsyncSession):
        """Process location update webhook for trip tracking"""
        # Could be used to update active trip or start new trip
        device_id = webhook_data.get("device_id")
        location = webhook_data.get("location")
        
        logger.debug(
            "geotab_location_update",
            device_id=device_id,
            location=location
        )
        # Trip tracking logic would go here
        # For now, just log the update
    
    async def _process_diagnostic_webhook(self, webhook_data: Dict[str, Any], db: AsyncSession):
        """Process diagnostic trouble code webhook"""
        try:
            diagnostic = GeoTabDiagnostic(
                device_id=webhook_data.get("device_id"),
                vehicle_id=webhook_data.get("vehicle_id"),
                organization_id=webhook_data.get("organization_id"),
                dtc_code=webhook_data.get("dtc_code"),
                severity=webhook_data.get("severity", "medium"),
                description=webhook_data.get("description"),
                battery_voltage=webhook_data.get("battery_voltage"),
                fuel_level=webhook_data.get("fuel_level"),
                odometer=webhook_data.get("odometer"),
                engine_hours=webhook_data.get("engine_hours")
            )
            
            db.add(diagnostic)
            await db.commit()
            
            logger.info(
                "geotab_diagnostic_stored",
                device_id=webhook_data.get("device_id"),
                dtc_code=webhook_data.get("dtc_code")
            )
            
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("geotab_diagnostic_store_failed", error=str(e))
            raise
    
    async def get_driver_hos(
        self,
        driver_id: UUID,
        organization_id: UUID,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Get driver HOS status"""
        # Get driver from database
        result = await db.execute(
            select(Driver).where(Driver.id == driver_id)
        )
        driver = result.scalar_one_or_none()
        
        if not driver:
            raise ValueError(f"Driver {driver_id} not found")
        
        # Mock HOS data
        return {
            "driver_id": str(driver_id),
            "current_status": random.choice(["on_duty", "driving", "off_duty", "sleeper"]),
            "drive_hours_today": round(random.uniform(0, 11), 2),
            "on_duty_hours_today": round(random.uniform(0, 14), 2),
            "cycle_hours": round(random.uniform(0, 70), 2),
            "drive_hours_remaining": round(random.uniform(0, 11), 2),
            "cycle_hours_remaining": round(random.uniform(0, 70), 2),
            "violations_today": 1 if driver.hos_drive_hours_today > 11 else 0,
            "next_break_required": (datetime.utcnow() + timedelta(hours=random.randint(0, 8))).isoformat()
        }
    
    async def get_fleet_summary(
        self,
        organization_id: UUID,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Get fleet-wide summary"""
        # Get total drivers
        result = await db.execute(
            select(Driver).where(Driver.organization_id == organization_id)
        )
        drivers = result.scalars().all()
        
        total_drivers = len(drivers)
        
        # Mock summary data
        return {
            "organization_id": str(organization_id),
            "total_devices": len(self.mock_devices),
            "active_devices": len([d for d in self.mock_devices.values() if d["status"] == "active"]),
            "total_drivers": total_drivers,
            "drivers_on_duty": random.randint(0, total_drivers),
            "drivers_driving": random.randint(0, total_drivers),
            "exceptions_today": random.randint(0, 20),
            "hos_violations_today": random.randint(0, 5),
            "average_fuel_efficiency": round(random.uniform(6, 12), 1),
            "total_miles_today": round(random.uniform(1000, 10000), 0)
        }


# Global instance
geotab_service = GeoTabService()

# Import random for mock data generation
import random
