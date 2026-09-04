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

from app.core.tenant import tenant_session

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


def simulated_provenance() -> Dict[str, Any]:
    """Provenance stamped into every simulated GeoTab payload (FS-233, widened FS-267).

    PUBLIC, because the exceptions ENVELOPE is built in `app/api/geotab.py` rather than
    here — see the note on `get_exceptions` below for why an envelope stamp is needed as
    well as a per-item one.

    `_require_simulated` already stops fabricated telematics reaching a live
    deployment — that gate landed in FS-25. What was still missing is that the
    payloads themselves did not SAY they were simulated, so nothing downstream
    could tell. That matters most for HOS: `drive_hours_today`, `cycle_hours` and
    `violations_today` are DOT-regulated figures, and a dashboard, an export or an
    audit response carrying them looked identical whether they were measured or
    invented.

    A consumer can now check one field instead of having to know which service
    produced the data and what mode it was in.
    """
    return {
        "simulated": True,
        "data_source": "geotab_simulator",
        "warning": (
            "Simulated telematics. Not measured from a device and not valid for "
            "DOT/ELD compliance reporting."
        ),
    }

logger = structlog.get_logger()


class GeoTabService:
    """Service for GeoTab fleet telematics integration"""
    
    def __init__(self):
        # In production, this would connect to actual GeoTab API
        # For now, providing mock implementation
        self.mock_devices = {
            "DEV-001": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-002": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-003": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-004": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-005": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-006": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-007": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-008": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-009": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-010": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-011": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-012": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-013": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-014": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-015": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
            "DEV-088": {"driver_id": None, "status": "active", "last_seen": datetime.now(timezone.utc)},
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
                "timestamp": (datetime.now(timezone.utc) - timedelta(hours=random.randint(0, hours_back))).isoformat(),
                "severity": random.choice(["low", "medium", "high", "critical"]),
                "location": {
                    "latitude": round(random.uniform(40.0, 42.0), 6),
                    "longitude": round(random.uniform(-88.0, -86.0), 6)
                },
                "details": {
                    # UNCORRELATED. `value` and the `threshold` it supposedly breached are
                    # two independent draws, so a "speeding" record can read 12 against a
                    # limit of 87. Left as-is deliberately: making the numbers agree would
                    # make fabricated data look MORE plausible, which is the opposite of
                    # what this endpoint needs.
                    "value": round(random.uniform(0, 100), 2),
                    "threshold": round(random.uniform(0, 100), 2)
                },
                # STAMPED PER ITEM, not just on the envelope. `exception_type` can be
                # "hos_violation", and a single exception is extracted and rendered as a row
                # on its own — a consumer holding one record must be able to tell. The
                # envelope is stamped as well (app/api/geotab.py), because
                # `random.randint(0, 10)` can return 0 and an empty simulated list would
                # otherwise carry no provenance anywhere.
                **simulated_provenance(),
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
            "last_seen": datetime.now(timezone.utc).isoformat(),
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
            } if device_id in ["DEV-088", "DEV-0044"] else None,
            # DTC codes and cold-chain temperatures are the same class of actionable figure
            # as HOS: a reefer reading drives a decision about a load, and a check-engine
            # code drives a decision about a vehicle. This function was gated by
            # `_require_simulated` from FS-25 and never stamped by FS-233 — the gate stops
            # it reaching a live deployment, the stamp is what lets a consumer of the demo
            # data tell. Both are needed.
            **simulated_provenance(),
        }
    
    async def handle_webhook(
        self,
        webhook_data: Dict[str, Any],
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Handle incoming GeoTab webhook events.

        THE SESSION IS REBOUND TO THE PAYLOAD'S TENANT, and without that none of this
        works (FS-734). The route takes `Depends(get_db)`, which sets no
        `app.current_org_id`; every table these handlers touch — `geotab_trips`,
        `geotab_exceptions`, `geotab_diagnostics`, `drivers` — has been **FORCE ROW LEVEL
        SECURITY since migration 011**. On an unbound session that means the SELECTs match
        nothing and the INSERTs are refused by the policy's WITH CHECK, and every handler
        here catches `SQLAlchemyError` and logs it. So the whole webhook receiver accepted
        events, answered 200, stored nothing, and said so only in a log line nobody reads.
        Verified against a real database: the insert fails with
        `new row violates row-level security policy for table "geotab_trips"`.

        FORCE is what makes this true everywhere rather than only on hardened deployments —
        the table owner is subject to the policy too, so no connection is exempt.

        A WEBHOOK WITH NO TENANT IS REFUSED rather than processed unscoped. The organisation
        arrives in the BODY, and the previous code used it only `if org_id:` — so an absent
        value did not narrow the lookup, it removed the narrowing, and a device-id collision
        would have rewritten another tenant's trip. `get_tenant_org_id` states the principle
        this follows: *we fail closed rather than fail open*. A position that cannot be
        attributed to a tenant is not a position that can be stored.
        """
        event_type = webhook_data.get("type", "unknown")
        device_id = webhook_data.get("device_id")
        org_id = webhook_data.get("organization_id")
        
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
            
            # NOT LOAD-BEARING, AND KEPT ANYWAY — the mutation says so, and rule 213 says
            # to record that rather than let the next reader delete it as noise. Removing
            # this branch changes no observable behaviour: `tenant_session(UUID(str(None)))`
            # raises `ValueError: badly formed hexadecimal UUID string`, the outer handler
            # catches it, and the caller still gets `processed: False`.
            #
            # It stays because "refused, for this reason" and "crashed on a malformed UUID"
            # are the same outcome only by accident. The log line here names the actual
            # condition, the error message names the missing field, and neither depends on
            # a parse failure continuing to happen further down. An invariant defended by a
            # coincidence is one the next refactor removes without noticing.
            if not org_id:
                logger.warning(
                    "geotab_webhook_untenanted",
                    event_type=event_type,
                    device_id=device_id,
                    reason="payload carried no organization_id; refusing rather than "
                           "processing against an unscoped session",
                )
                return {"processed": False, "error": "Missing organization_id"}

            # Every handler below writes a FORCE-RLS table, so they get a session bound to
            # this payload's tenant rather than the request's unbound one.
            async with tenant_session(UUID(str(org_id))) as scoped:
                if event_type == "exception":
                    await self._process_exception_webhook(webhook_data, scoped)
                elif event_type == "status_change":
                    await self._process_status_change_webhook(webhook_data, scoped)
                elif event_type == "location_update":
                    await self._process_location_update_webhook(webhook_data, scoped)
                elif event_type == "diagnostic":
                    await self._process_diagnostic_webhook(webhook_data, scoped)
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
                timestamp=datetime.fromisoformat(webhook_data.get("timestamp", datetime.now(timezone.utc).isoformat())),
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
                  if ts_raw else datetime.now(timezone.utc))
        except (ValueError, TypeError):
            logger.warning("geotab_location_bad_timestamp", device_id=device_id, raw=ts_raw)
            ts = datetime.now(timezone.utc)
        # Store naive-UTC uniformly (matches the models' utcnow defaults) so
        # rows never mix naive and aware values in one column.
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)

        # FAIL CLOSED WHEN THE TENANT IS UNKNOWN (FS-734). The scoping below used to be
        # `if org_id:` — so an absent `organization_id` did not narrow the lookup, it
        # REMOVED the narrowing, and the query matched any tenant's active trip for this
        # device id. The comment beside it already said this must never happen; the
        # condition made absence mean "unrestricted" instead of "refuse".
        #
        # That is the shape `core.tenant.get_tenant_org_id` exists to refuse, in the words
        # of its own docstring — *we fail closed rather than fail open* — and the shape the
        # notification handlers were fixed for: a filter applied only `if org is not None`
        # let a caller with no organisation read every organisation's rows.
        #
        # `organization_id` here is supplied in the webhook BODY. The route is secret-
        # guarded, so this is not open to the internet, but one shared secret across a
        # multi-tenant deployment makes the body the only thing deciding whose trip is
        # rewritten — and a genuine GeoTab callback carries no `organization_id` at all,
        # since it is our field rather than theirs. Dropping the event is the honest
        # outcome: a position that cannot be attributed to a tenant is not a position we
        # can store.
        if not org_id:
            logger.warning(
                "geotab_location_update_untenanted",
                device_id=device_id,
                reason="webhook payload carried no organization_id; refusing to match or "
                       "write a trip that cannot be attributed to a tenant",
            )
            return

        try:
            # Scope the lookup to the SAME org as the payload: a webhook caller
            # must never mutate another tenant's trip via a device-id collision.
            trip_stmt = (
                select(GeoTabTrip)
                .where(GeoTabTrip.device_id == device_id,
                       GeoTabTrip.status == "active",
                       GeoTabTrip.organization_id == org_id)
                .order_by(GeoTabTrip.start_time.desc())
                .limit(1)
            )
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
        
        # Simulated HOS. Two things were wrong beyond the data being fake.
        #
        # 1. `violations_today` was computed from the REAL
        #    `driver.hos_drive_hours_today` while every other field was random, so
        #    the response could report 11.9 simulated drive hours and 0 violations.
        #    Internally inconsistent numbers are worse than obviously fake ones:
        #    they look plausible and cannot be reconciled.
        # 2. Nothing in the payload said it was simulated.
        #
        # The remaining figures are now DERIVED from one another, so the response is
        # at least self-consistent: remaining = limit - used, and the violation flag
        # reflects the hours actually returned.
        drive_hours = round(random.uniform(0, 11), 2)
        on_duty_hours = round(max(drive_hours, random.uniform(0, 14)), 2)
        cycle_hours = round(random.uniform(on_duty_hours, 70), 2)

        # 49 CFR 395: 11h driving, 14h on-duty window, 70h/8-day cycle.
        DRIVE_LIMIT, CYCLE_LIMIT = 11.0, 70.0

        return {
            "driver_id": str(driver_id),
            "current_status": random.choice(["on_duty", "driving", "off_duty", "sleeper"]),
            "drive_hours_today": drive_hours,
            "on_duty_hours_today": on_duty_hours,
            "cycle_hours": cycle_hours,
            "drive_hours_remaining": round(max(0.0, DRIVE_LIMIT - drive_hours), 2),
            "cycle_hours_remaining": round(max(0.0, CYCLE_LIMIT - cycle_hours), 2),
            # Derived from the hours in THIS response, not from a different source.
            "violations_today": int(drive_hours > DRIVE_LIMIT or cycle_hours > CYCLE_LIMIT),
            "next_break_required": (
                datetime.now(timezone.utc) + timedelta(hours=random.randint(0, 8))
            ).isoformat(),
            **simulated_provenance(),
        }
    
    async def get_devices(
        self,
        organization_id: Optional[UUID] = None,
        db: AsyncSession = None,
        limit: int = 100,
        offset: int = 0,
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

        # FS-898. The merge above (DB drivers + a 500-trip enrichment window + the
        # optional simulated registry) has no natural SQL LIMIT of its own -- it is
        # paginated here, on the assembled result, rather than by bounding any one of
        # the three sources individually. limit + 1: the route's mark_truncated call
        # tells "exactly a full page" from "there is more" from the extra entry, the
        # same probe idiom every SQL-level page in this file uses.
        ordered = sorted(devices.values(), key=lambda d: d["id"])
        return ordered[offset : offset + limit + 1]

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

        # CONDITIONAL, unlike every other stamp in this file. This method PREFERS real
        # data — the most recent trip endpoint, then the most recent exception fix — and
        # only invents a position when neither exists. Stamping unconditionally would
        # label a genuine GPS fix as simulated, which is a different falsehood in the
        # other direction, and one that would teach a consumer to ignore the flag.
        invented = False

        if location is None:
            if not settings.GEOTAB_SIMULATED:
                # Live mode: no real fix on record -> 404, never an invented one.
                raise ValueError(f"No known location for device {device_id}")
            location = {
                "latitude": round(random.uniform(40.0, 42.0), 6),
                "longitude": round(random.uniform(-88.0, -86.0), 6),
            }
            timestamp = datetime.now(timezone.utc)
            invented = True

        return {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "speed": location.get("speed"),
            "heading": location.get("heading"),
            "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
            "address": location.get("address"),
            # A point inside a US Midwest bounding box, drawn fresh on every call. Without
            # this a map cannot tell it from a fix, and the device appears to be parked in
            # a field in Illinois.
            **(simulated_provenance() if invented else {}),
        }

    async def get_device_trips(
        self,
        device_id: str,
        from_time: datetime,
        to_time: datetime,
        organization_id: Optional[UUID] = None,
        db: AsyncSession = None,
        limit: int = 100,
        offset: int = 0,
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
            # FS-898. The default window is 24h, but both ends are caller-supplied --
            # nothing stopped a multi-year range from returning every trip a device
            # ever logged. limit + 1: the route's mark_truncated call tells "exactly a
            # full page" from "there is more" from the extra row.
            .offset(offset)
            .limit(limit + 1)
        )
        if organization_id:
            stmt = stmt.where(GeoTabTrip.organization_id == organization_id)
        rows = (await db.execute(stmt)).scalars().all()

        # Exceptions for the event counts, fetched ONCE rather than per trip
        # (was an N+1: one SELECT on geotab_exceptions per trip). Every trip's
        # window starts at or after the earliest trip start, so a single fetch of
        # this device's exceptions from that point captures everything any trip
        # could match; each trip then filters this list in Python with the exact
        # same predicate as before (timestamp >= start [and <= end]), preserving
        # the original semantics including overlap double-counting and the
        # no-upper-bound case when a trip has no end_time. Not org-filtered —
        # matching the original query, which keyed only on device_id + timestamp.
        device_exceptions: list = []
        if rows:
            earliest_start = min(t.start_time for t in rows)
            exc_stmt = (
                select(GeoTabException)
                .where(
                    GeoTabException.device_id == device_id,
                    GeoTabException.timestamp >= earliest_start,
                )
                .order_by(GeoTabException.timestamp)
            )
            device_exceptions = list((await db.execute(exc_stmt)).scalars().all())

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
            for exc in device_exceptions:
                if exc.timestamp < trip.start_time:
                    continue
                if trip.end_time and exc.timestamp > trip.end_time:
                    continue
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
            "total_miles_today": round(random.uniform(1000, 10000), 0),
            **simulated_provenance(),
        }


# Global instance
geotab_service = GeoTabService()

# Import random for mock data generation
import random
