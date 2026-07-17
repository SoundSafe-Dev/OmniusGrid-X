"""Fleet logistics models: vehicles, geofencing, maintenance (migration 025).

Backs the Transportation page panels that previously had frontend mocks only
(Fleet & Drivers vehicles grid, Geofencing, Maintenance). Kept in a separate
module reusing the shared Base — same pattern as notification_models.py — to
avoid touching the large shared models.py (a convergence hotspot).
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, String, Text

from app.db.models import Base, UUIDColumn


class Vehicle(Base):
    """Fleet vehicle (tractor/truck) — previously frontend-mock-only."""
    __tablename__ = "vehicles"

    id = UUIDColumn()
    organization_id = Column(String(36), index=True)
    carrier_id = Column(String(36), index=True)
    vehicle_number = Column(String(100), nullable=False)
    vin = Column(String(64))
    make = Column(String(100))
    model = Column(String(100))
    year = Column(Integer)
    status = Column(String(50), default="idle")  # moving | idle | stopped | offline | maintenance
    fuel_level_percent = Column(Float)
    odometer_miles = Column(Float)
    geotab_device_id = Column(String(100))
    current_driver_id = Column(String(36))
    last_location = Column(JSON, default={})  # {latitude, longitude, speed, heading, timestamp}
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class GeofenceZone(Base):
    """Geofence zone (circle or polygon) for fleet monitoring."""
    __tablename__ = "geofence_zones"

    id = UUIDColumn()
    organization_id = Column(String(36), index=True)
    name = Column(String(255), nullable=False)
    zone_type = Column(String(50), default="circle")  # circle | polygon
    center_lat = Column(Float)
    center_lng = Column(Float)
    radius_meters = Column(Float)
    polygon = Column(JSON)          # [[lat, lng], ...] when zone_type=polygon
    trigger_on = Column(String(20), default="both")  # entry | exit | both
    severity = Column(String(20), default="warning")  # info | warning | critical
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class GeofenceAlert(Base):
    """Entry/exit event against a geofence zone."""
    __tablename__ = "geofence_alerts"

    id = UUIDColumn()
    organization_id = Column(String(36), index=True)
    zone_id = Column(String(36), index=True, nullable=False)
    vehicle_id = Column(String(36), index=True)
    event_type = Column(String(20), nullable=False)  # entry | exit
    severity = Column(String(20), default="warning")
    location = Column(JSON, default={})
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(36))
    acknowledged_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)


class MaintenanceSchedule(Base):
    """Preventive maintenance schedule for a vehicle."""
    __tablename__ = "maintenance_schedules"

    id = UUIDColumn()
    organization_id = Column(String(36), index=True)
    vehicle_id = Column(String(36), index=True, nullable=False)
    maintenance_type = Column(String(100), nullable=False)  # oil_change | inspection | tires | brake_service | ...
    description = Column(Text)
    due_date = Column(DateTime(timezone=True))
    due_odometer_miles = Column(Float)
    status = Column(String(50), default="scheduled")  # scheduled | overdue | in_progress | completed | cancelled
    estimated_cost = Column(Float)
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class RepairOrder(Base):
    """Active/completed repair work on a vehicle."""
    __tablename__ = "repair_orders"

    id = UUIDColumn()
    organization_id = Column(String(36), index=True)
    vehicle_id = Column(String(36), index=True, nullable=False)
    schedule_id = Column(String(36))  # optional link to the PM schedule
    title = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(String(50), default="open")  # open | in_progress | awaiting_parts | completed | cancelled
    priority = Column(String(20), default="medium")  # low | medium | high | critical
    vendor = Column(String(255))
    cost = Column(Float)
    category = Column(String(100))  # engine | brakes | tires | electrical | body | other
    opened_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
