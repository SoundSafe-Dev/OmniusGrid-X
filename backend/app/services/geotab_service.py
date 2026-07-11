"""
GeoTab Integration Service
Handles fleet telematics, HOS compliance, and vehicle diagnostics
"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from uuid import UUID
import structlog
import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import Driver, Carrier, GeoTabTrip, GeoTabDiagnostic, GeoTabException
from app.core.config import settings


class GeoTabLiveModeNotConfigured(RuntimeError):
    """Raised when GEOTAB_SIMULATED is false but no live MyGeotab client exists.

    Making this loud (instead of silently returning random data) is the point of
    FS-25: simulated telematics must be an explicit opt-in, never a fallback that
    ships fake fleet data to a production dashboard.
    """


def _require_simulated(feature: str) -> None:
    if not settings.GEOTAB_SIMULATED:
        raise GeoTabLiveModeNotConfigured(
            f"GeoTab '{feature}' has no live MyGeotab client wired yet. "
            f"Set GEOTAB_SIMULATED=true for demo data, or implement the live "
            f"client (GEOTAB_DATABASE/USERNAME/PASSWORD)."
        )

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
        _require_simulated("exceptions")
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
        _require_simulated("diagnostics")
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
        """Persist a live position so the fleet map reflects it.

        Updates the device's most recent trip end-point (or opens a new one),
        which is exactly what /api/v1/fleet/vehicles/locations reads back.
        """
        device_id = webhook_data.get("device_id")
        location = webhook_data.get("location")
        org_id = webhook_data.get("organization_id")
        if not device_id or not location:
            logger.warning("geotab_location_update_incomplete", device_id=device_id)
            return

        # Parse the timestamp defensively: webhooks are external input, and a
        # malformed value must degrade to "now", not 500 the whole webhook.
        ts_raw = webhook_data.get("timestamp")
        try:
            ts = (datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                  if ts_raw else datetime.utcnow())
        except (ValueError, TypeError):
            logger.warning("geotab_location_bad_timestamp", device_id=device_id, raw=ts_raw)
            ts = datetime.utcnow()
        # Store naive-UTC uniformly (matches the models' utcnow defaults) so
        # rows never mix naive and aware values in one column.
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)

        try:
            # Scope the lookup to the SAME org as the payload: a webhook caller
            # must never mutate another tenant's trip via a device-id collision.
            trip_stmt = (
                select(GeoTabTrip)
                .where(GeoTabTrip.device_id == device_id,
                       GeoTabTrip.status == "active")
                .order_by(GeoTabTrip.start_time.desc())
                .limit(1)
            )
            if org_id:
                trip_stmt = trip_stmt.where(GeoTabTrip.organization_id == org_id)
            latest = (await db.execute(trip_stmt)).scalar_one_or_none()

            if latest is not None:
                # Extend the active trip to the new position (keyed on
                # status='active', so successive pings extend one row instead of
                # inserting a new trip per ping).
                latest.end_location = location
                latest.end_time = ts
            else:
                db.add(GeoTabTrip(
                    device_id=device_id,
                    vehicle_id=webhook_data.get("vehicle_id"),
                    organization_id=org_id,
                    start_time=ts,
                    end_time=ts,
                    start_location=location,
                    end_location=location,
                    status="active",
                ))
            await db.commit()
            logger.info("geotab_location_persisted", device_id=device_id)
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("geotab_location_store_failed", device_id=device_id, error=str(e))
    
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
        _require_simulated("driver HOS")
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
    
    async def get_devices(
        self,
        organization_id: Optional[UUID] = None,
        db: AsyncSession = None
    ) -> List[Dict[str, Any]]:
        """List GeoTab devices: drivers' ELD assignments (DB) + the device registry.

        The DB is the source of truth for device→driver pairing; the registry
        stands in for the GeoTab API's device inventory.
        """
        devices: Dict[str, Dict[str, Any]] = {}

        def _blank(device_id: str) -> Dict[str, Any]:
            return {
                "id": device_id,
                "device_type": "GO9",
                "serial_number": None,
                "vehicle_id": None,
                "driver_id": None,
                "is_active": True,
                "last_communication": None,
                "firmware_version": None,
            }

        if db is not None:
            stmt = select(Driver).where(Driver.eld_device_id.isnot(None))
            if organization_id:
                stmt = stmt.where(Driver.organization_id == organization_id)
            result = await db.execute(stmt)
            for driver in result.scalars().all():
                entry = _blank(driver.eld_device_id)
                entry["driver_id"] = str(driver.id)
                entry["is_active"] = bool(driver.is_active)
                devices[driver.eld_device_id] = entry

            # Enrich with the latest trip per device (vehicle + last comms).
            trip_stmt = select(GeoTabTrip).order_by(GeoTabTrip.start_time.desc())
            if organization_id:
                trip_stmt = trip_stmt.where(GeoTabTrip.organization_id == organization_id)
            trips = (await db.execute(trip_stmt.limit(500))).scalars().all()
            for trip in trips:
                entry = devices.setdefault(trip.device_id, _blank(trip.device_id))
                if entry["vehicle_id"] is None:
                    entry["vehicle_id"] = trip.vehicle_id
                if entry["last_communication"] is None:
                    last = trip.end_time or trip.start_time
                    entry["last_communication"] = last.isoformat() if last else None

        # The demo device registry is only merged in simulated mode; live mode
        # serves DB-known devices exclusively (no phantom vehicles).
        if settings.GEOTAB_SIMULATED:
            for device_id, info in self.mock_devices.items():
                entry = devices.setdefault(device_id, _blank(device_id))
                entry["is_active"] = entry["is_active"] and info["status"] == "active"
                if entry["last_communication"] is None:
                    entry["last_communication"] = info["last_seen"].isoformat()

        return sorted(devices.values(), key=lambda d: d["id"])

    async def get_device_location(
        self,
        device_id: str,
        organization_id: Optional[UUID] = None,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Latest known position for a device.

        Prefers real data (most recent trip endpoint, then most recent
        exception fix); falls back to a simulated position in the same
        region the mock exception generator uses.
        """
        # The mock registry only counts as "known devices" in simulated mode.
        known_ids = set(self.mock_devices) if settings.GEOTAB_SIMULATED else set()
        location: Optional[Dict[str, Any]] = None
        timestamp: Optional[datetime] = None

        if db is not None:
            trip_stmt = (
                select(GeoTabTrip)
                .where(GeoTabTrip.device_id == device_id)
                .order_by(GeoTabTrip.start_time.desc())
                .limit(1)
            )
            trip = (await db.execute(trip_stmt)).scalar_one_or_none()
            if trip:
                known_ids.add(device_id)
                location = trip.end_location or trip.start_location
                timestamp = trip.end_time or trip.start_time

            if location is None:
                exc_stmt = (
                    select(GeoTabException)
                    .where(GeoTabException.device_id == device_id)
                    .order_by(GeoTabException.timestamp.desc())
                    .limit(1)
                )
                exc = (await db.execute(exc_stmt)).scalar_one_or_none()
                if exc and exc.location:
                    known_ids.add(device_id)
                    location = exc.location
                    timestamp = exc.timestamp

        if device_id not in known_ids:
            raise ValueError(f"Device {device_id} not found")

        if location is None:
            if not settings.GEOTAB_SIMULATED:
                # Live mode: no real fix on record -> 404, never an invented one.
                raise ValueError(f"No known location for device {device_id}")
            location = {
                "latitude": round(random.uniform(40.0, 42.0), 6),
                "longitude": round(random.uniform(-88.0, -86.0), 6),
            }
            timestamp = datetime.utcnow()

        return {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "speed": location.get("speed"),
            "heading": location.get("heading"),
            "timestamp": (timestamp or datetime.utcnow()).isoformat(),
            "address": location.get("address"),
        }

    async def get_device_trips(
        self,
        device_id: str,
        from_time: datetime,
        to_time: datetime,
        organization_id: Optional[UUID] = None,
        db: AsyncSession = None
    ) -> List[Dict[str, Any]]:
        """Trips for a device in [from_time, to_time], frontend-shaped.

        Distances are km and durations/idle minutes (the TS GeoTabTrip
        contract); the trips table stores miles and seconds.
        """
        trips: List[Dict[str, Any]] = []
        if db is None:
            return trips

        stmt = (
            select(GeoTabTrip)
            .where(
                GeoTabTrip.device_id == device_id,
                GeoTabTrip.start_time >= from_time,
                GeoTabTrip.start_time <= to_time,
            )
            .order_by(GeoTabTrip.start_time.desc())
        )
        if organization_id:
            stmt = stmt.where(GeoTabTrip.organization_id == organization_id)
        rows = (await db.execute(stmt)).scalars().all()

        for trip in rows:
            distance_km = (
                round(float(trip.distance_miles) * 1.60934, 1)
                if trip.distance_miles is not None else 0.0
            )
            duration_min = (trip.duration_seconds or 0) // 60
            idle_min = (trip.idle_time_seconds or 0) // 60
            meta = trip.meta_data or {}

            # Event counts come from exceptions recorded during the trip window.
            counts = {"harsh_braking": 0, "harsh_acceleration": 0, "speeding": 0}
            exc_stmt = select(GeoTabException).where(
                GeoTabException.device_id == device_id,
                GeoTabException.timestamp >= trip.start_time,
            )
            if trip.end_time:
                exc_stmt = exc_stmt.where(GeoTabException.timestamp <= trip.end_time)
            for exc in (await db.execute(exc_stmt)).scalars().all():
                if exc.exception_type in counts:
                    counts[exc.exception_type] += 1

            moving_min = max(duration_min - idle_min, 0)
            average_speed = (
                round(distance_km / (moving_min / 60), 1) if moving_min else None
            )

            trips.append({
                "id": str(trip.id),
                "device_id": trip.device_id,
                "driver_id": str(trip.driver_id) if trip.driver_id else None,
                "vehicle_id": trip.vehicle_id,
                "start_time": trip.start_time.isoformat(),
                "end_time": trip.end_time.isoformat() if trip.end_time else None,
                "distance": distance_km,
                "duration": duration_min,
                "start_location": trip.start_location,
                "end_location": trip.end_location,
                "max_speed": meta.get("max_speed"),
                "average_speed": average_speed,
                "idle_time": idle_min,
                "harsh_braking_events": counts["harsh_braking"],
                "harsh_acceleration_events": counts["harsh_acceleration"],
                "speeding_events": counts["speeding"],
            })

        return trips

    async def get_fleet_summary(
        self,
        organization_id: UUID,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Get fleet-wide summary"""
        _require_simulated("fleet summary")
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
