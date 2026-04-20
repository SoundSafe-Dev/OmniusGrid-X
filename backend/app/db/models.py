"""Database models"""

import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, String, DateTime, Boolean, Numeric, JSON, ForeignKey, Text, BigInteger, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Organization(Base):
    __tablename__ = "organizations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    settings = Column(JSON, default={})
    
    assets = relationship("Asset", back_populates="organization")


class AssetType(Base):
    __tablename__ = "asset_types"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    category = Column(String(100), nullable=False)
    packml_config = Column(JSON, default={})
    telemetry_schema = Column(JSON, default={})
    action_space = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    assets = relationship("Asset", back_populates="asset_type")


class Asset(Base):
    __tablename__ = "assets"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    workcell_id = Column(UUID(as_uuid=True), ForeignKey("workcells.id"))
    asset_type_id = Column(UUID(as_uuid=True), ForeignKey("asset_types.id"), nullable=False)
    name = Column(String(255), nullable=False)
    serial_number = Column(String(255))
    vendor = Column(String(100))
    model = Column(String(100))
    current_packml_state = Column(String(50), default="Idle")
    connection_config = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    organization = relationship("Organization", back_populates="assets")
    asset_type = relationship("AssetType", back_populates="assets")


class PackMLState(Base):
    __tablename__ = "packml_states"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    state = Column(String(50), nullable=False)
    previous_state = Column(String(50))
    state_entered_at = Column(DateTime(timezone=True), nullable=False)
    state_exited_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Numeric)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Telemetry(Base):
    __tablename__ = "telemetry"
    
    time = Column(DateTime(timezone=True), primary_key=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), primary_key=True)
    metric_name = Column(String(100), primary_key=True)
    value = Column(Numeric, nullable=False)
    unit = Column(String(50))
    packml_state = Column(String(50))
    meta_data = Column(JSON, default={})
    sequence_num = Column(BigInteger)


class Alarm(Base):
    __tablename__ = "alarms"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    alarm_code = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(UUID(as_uuid=True))
    acknowledged_at = Column(DateTime(timezone=True))
    acknowledged_comment = Column(Text)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    cleared_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, default={})


class Operation(Base):
    __tablename__ = "operations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    operation_name = Column(String(255), nullable=False)
    job_id = Column(String(255))
    status = Column(String(50), nullable=False)
    packml_state_durations = Column(JSON, default={})
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    planned_duration = Column(Numeric)
    actual_duration = Column(Numeric)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Workcell(Base):
    __tablename__ = "workcells"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    location = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ==================== YMS Models ====================

class YardTrailer(Base):
    """Trailer inventory in the yard"""
    __tablename__ = "yard_trailers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    trailer_number = Column(String(50), nullable=False)
    carrier_id = Column(UUID(as_uuid=True), ForeignKey("carriers.id"))
    trailer_type = Column(String(50))  # dry_van, reefer, flatbed, etc.
    status = Column(String(50), default="checked_in")  # checked_in, docked, yard, checked_out
    yard_location = Column(String(100))  # grid position or zone
    seal_number = Column(String(50))
    seal_status = Column(String(20), default="intact")  # intact, broken, missing
    weight_lbs = Column(Numeric)
    check_in_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    check_out_at = Column(DateTime(timezone=True))
    dock_door_id = Column(UUID(as_uuid=True), ForeignKey("dock_doors.id"))
    driver_id = Column(UUID(as_uuid=True), ForeignKey("drivers.id"))
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"))
    temperature_setpoint = Column(Numeric)  # for reefers
    temperature_actual = Column(Numeric)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class DockDoor(Base):
    """Dock door scheduling and status"""
    __tablename__ = "dock_doors"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    door_number = Column(String(50), nullable=False)
    door_type = Column(String(50))  # inbound, outbound, cross_dock
    status = Column(String(50), default="available")  # available, occupied, maintenance
    equipment_capabilities = Column(JSON, default={})  # forklift, pallet_jack, etc.
    current_trailer_id = Column(UUID(as_uuid=True), ForeignKey("yard_trailers.id"))
    last_occupied_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class YardMove(Base):
    """Jockey/yard truck movements"""
    __tablename__ = "yard_moves"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    trailer_id = Column(UUID(as_uuid=True), ForeignKey("yard_trailers.id"), nullable=False)
    from_location = Column(String(100), nullable=False)
    to_location = Column(String(100), nullable=False)
    move_type = Column(String(50))  # check_in, dock, yard_relocate, check_out
    jockey_driver_id = Column(UUID(as_uuid=True), ForeignKey("drivers.id"))
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Numeric)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class DriverWaitTime(Base):
    """Track driver detention/wait times"""
    __tablename__ = "driver_wait_times"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    driver_id = Column(UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=False)
    trailer_id = Column(UUID(as_uuid=True), ForeignKey("yard_trailers.id"))
    check_in_at = Column(DateTime(timezone=True), nullable=False)
    docked_at = Column(DateTime(timezone=True))
    unloaded_at = Column(DateTime(timezone=True))
    check_out_at = Column(DateTime(timezone=True))
    total_wait_minutes = Column(Numeric)
    detention_minutes = Column(Numeric)  # billable detention time
    demurrage_minutes = Column(Numeric)  # billable demurrage time
    detention_rate = Column(Numeric)  # hourly rate
    demurrage_rate = Column(Numeric)
    detention_charge = Column(Numeric)  # calculated charge
    demurrage_charge = Column(Numeric)
    is_billed = Column(Boolean, default=False)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class YardCheckPoint(Base):
    """Gate and checkpoint tracking"""
    __tablename__ = "yard_checkpoints"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    trailer_id = Column(UUID(as_uuid=True), ForeignKey("yard_trailers.id"), nullable=False)
    checkpoint_type = Column(String(50), nullable=False)  # gate_in, guard_shack, weigh_station, gate_out
    checkpoint_name = Column(String(100))
    passed_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    weight_lbs = Column(Numeric)
    inspection_status = Column(String(50))  # passed, failed, pending
    inspector_id = Column(UUID(as_uuid=True))
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ==================== TMS Models ====================

class Carrier(Base):
    """Carrier profiles and compliance"""
    __tablename__ = "carriers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    carrier_name = Column(String(255), nullable=False)
    dot_number = Column(String(50))
    mc_number = Column(String(50))
    ctpat_certified = Column(Boolean, default=False)
    ctpat_expires_at = Column(DateTime(timezone=True))
    insurance_on_file = Column(Boolean, default=False)
    insurance_expires_at = Column(DateTime(timezone=True))
    safety_rating = Column(String(20))  # satisfactory, conditional, unsatisfactory
    csa_score = Column(Numeric)
    contract_rate = Column(JSON, default={})  # negotiated rates
    is_active = Column(Boolean, default=True)
    contact_info = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Driver(Base):
    """Driver profiles and HOS compliance"""
    __tablename__ = "drivers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    carrier_id = Column(UUID(as_uuid=True), ForeignKey("carriers.id"))
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    license_number = Column(String(100))
    license_state = Column(String(50))
    cdl_class = Column(String(20))  # A, B, C
    hazmat_endorsed = Column(Boolean, default=False)
    medical_cert_expires = Column(DateTime(timezone=True))
    dq_file_complete = Column(Boolean, default=False)  # Driver Qualification file
    current_hos_status = Column(String(50))  # on_duty, driving, off_duty, sleeper
    hos_drive_hours_today = Column(Numeric, default=0)
    hos_on_duty_hours_today = Column(Numeric, default=0)
    hos_cycle_hours = Column(Numeric, default=0)
    eld_device_id = Column(String(100))
    phone = Column(String(50))
    email = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Shipment(Base):
    """Shipment lifecycle tracking"""
    __tablename__ = "shipments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    carrier_id = Column(UUID(as_uuid=True), ForeignKey("carriers.id"))
    driver_id = Column(UUID(as_uuid=True), ForeignKey("drivers.id"))
    trailer_id = Column(UUID(as_uuid=True), ForeignKey("yard_trailers.id"))
    shipment_number = Column(String(100), nullable=False)
    pro_number = Column(String(100))  # Progressive Rotating Order
    bol_number = Column(String(100))  # Bill of Lading
    shipment_type = Column(String(50))  # inbound, outbound, transfer
    status = Column(String(50), default="planned")  # planned, dispatched, in_transit, delivered, cancelled
    origin = Column(JSON, default={})
    destination = Column(JSON, default={})
    scheduled_pickup = Column(DateTime(timezone=True))
    actual_pickup = Column(DateTime(timezone=True))
    scheduled_delivery = Column(DateTime(timezone=True))
    actual_delivery = Column(DateTime(timezone=True))
    priority = Column(String(20), default="normal")  # low, normal, high, critical
    total_weight_lbs = Column(Numeric)
    total_pieces = Column(Integer)
    hazmat = Column(Boolean, default=False)
    temperature_required = Column(Boolean, default=False)
    temperature_min = Column(Numeric)
    temperature_max = Column(Numeric)
    route_id = Column(UUID(as_uuid=True), ForeignKey("routes.id"))
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Route(Base):
    """Optimized routes for shipments"""
    __tablename__ = "routes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    route_name = Column(String(255))
    origin = Column(JSON, default={}, nullable=False)
    destination = Column(JSON, default={}, nullable=False)
    waypoints = Column(JSON, default=[])
    total_distance_miles = Column(Numeric)
    estimated_duration_hours = Column(Numeric)
    fuel_cost_estimate = Column(Numeric)
    toll_cost_estimate = Column(Numeric)
    optimization_criteria = Column(String(50))  # fastest, cheapest, balanced
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class LoadPlan(Base):
    """Product-to-trailer load planning"""
    __tablename__ = "load_plans"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False)
    trailer_id = Column(UUID(as_uuid=True), ForeignKey("yard_trailers.id"))
    planned_by = Column(UUID(as_uuid=True))
    planned_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    load_sequence = Column(JSON, default=[])  # order of loading
    weight_distribution = Column(JSON, default={})  # axle weights
    space_utilization_percent = Column(Numeric)
    temperature_zones = Column(JSON, default=[])  # multi-temp loads
    special_instructions = Column(Text)
    is_executed = Column(Boolean, default=False)
    executed_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class FreightCharge(Base):
    """Freight billing and charges"""
    __tablename__ = "freight_charges"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False)
    carrier_id = Column(UUID(as_uuid=True), ForeignKey("carriers.id"))
    charge_type = Column(String(50), nullable=False)  # linehaul, fuel, detention, demurrage, accessorial
    charge_description = Column(String(255))
    rate_basis = Column(String(50))  # per_mile, per_pound, flat, hourly
    quantity = Column(Numeric)
    rate = Column(Numeric)
    amount = Column(Numeric, nullable=False)
    currency = Column(String(10), default="USD")
    is_billed = Column(Boolean, default=False)
    billed_at = Column(DateTime(timezone=True))
    invoice_number = Column(String(100))
    approved_by = Column(UUID(as_uuid=True))
    approved_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ==================== Correlation Models ====================

class DockAppointment(Base):
    """Link dock schedules to production"""
    __tablename__ = "dock_appointments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    dock_door_id = Column(UUID(as_uuid=True), ForeignKey("dock_doors.id"), nullable=False)
    trailer_id = Column(UUID(as_uuid=True), ForeignKey("yard_trailers.id"))
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"))
    operation_id = Column(UUID(as_uuid=True), ForeignKey("operations.id"))  # linked production job
    appointment_type = Column(String(50))  # pickup, delivery, transfer
    scheduled_start = Column(DateTime(timezone=True), nullable=False)
    scheduled_end = Column(DateTime(timezone=True), nullable=False)
    actual_start = Column(DateTime(timezone=True))
    actual_end = Column(DateTime(timezone=True))
    status = Column(String(50), default="scheduled")  # scheduled, in_progress, completed, cancelled, no_show
    carrier_id = Column(UUID(as_uuid=True), ForeignKey("carriers.id"))
    driver_id = Column(UUID(as_uuid=True), ForeignKey("drivers.id"))
    priority = Column(String(20), default="normal")
    compliance_required = Column(Boolean, default=False)  # FDA, etc.
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class TruckAssetCorrelation(Base):
    """Correlate truck arrivals with manufacturing asset readiness"""
    __tablename__ = "truck_asset_correlations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"))
    trailer_id = Column(UUID(as_uuid=True), ForeignKey("yard_trailers.id"))
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"))
    operation_id = Column(UUID(as_uuid=True), ForeignKey("operations.id"))
    truck_arrived_at = Column(DateTime(timezone=True))
    asset_ready_at = Column(DateTime(timezone=True))
    asset_completion_forecast = Column(DateTime(timezone=True))
    readiness_gap_minutes = Column(Numeric)  # positive = truck waiting, negative = asset waiting
    load_start_at = Column(DateTime(timezone=True))
    load_complete_at = Column(DateTime(timezone=True))
    detention_incurred = Column(Boolean, default=False)
    detention_charge = Column(Numeric)
    efficiency_score = Column(Numeric)  # 0-100 based on synchronization
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class LoadQualityLog(Base):
    """Track shipping defects and correlate to manufacturing"""
    __tablename__ = "load_quality_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"))
    trailer_id = Column(UUID(as_uuid=True), ForeignKey("yard_trailers.id"))
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"))  # source asset
    operation_id = Column(UUID(as_uuid=True), ForeignKey("operations.id"))
    defect_type = Column(String(100))  # wrong_product, damaged, short, over, temp_excursion
    severity = Column(String(20))  # minor, major, critical
    quantity_affected = Column(Numeric)
    root_cause_asset = Column(UUID(as_uuid=True), ForeignKey("assets.id"))
    root_cause_operation = Column(UUID(as_uuid=True), ForeignKey("operations.id"))
    manufacturing_correlation_score = Column(Numeric)  # confidence of manufacturing root cause
    carrier_liable = Column(Boolean, default=False)
    claim_filed = Column(Boolean, default=False)
    claim_amount = Column(Numeric)
    resolved_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class User(Base):
    """User authentication and authorization"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    role = Column(String(50), default="operator")
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ==================== Kanban Task Management Models ====================

class TaskBoard(Base):
    """Unified kanban board configuration per organization"""
    __tablename__ = "task_boards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(255), nullable=False, default="Main Operations Board")
    board_type = Column(String(50), default="unified")  # unified, production, maintenance, quality, safety, logistics
    default_view_config = Column(JSON, default={
        "default_filter": "all",
        "default_group_by": None,
        "show_wip_limits": True,
        "show_completed": False
    })
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class TaskColumn(Base):
    """Kanban columns (swimlanes) - standard 6 columns"""
    __tablename__ = "task_columns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    board_id = Column(UUID(as_uuid=True), ForeignKey("task_boards.id"), nullable=False)
    name = Column(String(100), nullable=False)
    position = Column(Integer, nullable=False)  # order in board
    wip_limit = Column(Integer, default=5)  # max tasks allowed
    column_type = Column(String(50), nullable=False)  # backlog, triage, in_progress, review, rejected, done
    color = Column(String(7), default="#6366F1")  # hex color
    is_collapsed = Column(Boolean, default=False)
    auto_archive_days = Column(Integer, default=7)  # auto-archive tasks after N days in Done
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Task(Base):
    """Central work item for actionable decision-making"""
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    board_id = Column(UUID(as_uuid=True), ForeignKey("task_boards.id"), nullable=False)
    column_id = Column(UUID(as_uuid=True), ForeignKey("task_columns.id"), nullable=False)
    position = Column(Integer, default=0)  # order within column

    # Basic info
    title = Column(String(500), nullable=False)
    description = Column(Text)
    task_type = Column(String(50), nullable=False)  # production_job, maintenance_pm, maintenance_cm, quality_inspection, safety_check, alarm_response, command_execution, material_request, changeover, custom
    priority = Column(String(20), default="medium")  # low, medium, high, critical, emergency
    status = Column(String(50), default="draft")  # draft, ready, in_progress, blocked, completed, cancelled

    # Assignments
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    assigned_at = Column(DateTime(timezone=True))

    # Scheduling
    planned_start = Column(DateTime(timezone=True))
    planned_duration = Column(Integer)  # minutes
    due_date = Column(DateTime(timezone=True))
    actual_start = Column(DateTime(timezone=True))
    actual_end = Column(DateTime(timezone=True))

    # Relationships to OmniusGrid entities
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"))
    operation_id = Column(UUID(as_uuid=True), ForeignKey("operations.id"))
    alarm_id = Column(UUID(as_uuid=True), ForeignKey("alarms.id"))
    command_id = Column(String(255))  # Command ID (string format)
    work_order_id = Column(UUID(as_uuid=True))
    parent_task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"))
    related_shipment_id = Column(UUID(as_uuid=True), ForeignKey("shipments.id"))
    rule_id = Column(UUID(as_uuid=True), ForeignKey("task_rules.id"))  # Rule that created this task

    # Progress tracking
    progress_percent = Column(Integer, default=0)  # 0-100
    time_logged_minutes = Column(Integer, default=0)
    estimated_effort_minutes = Column(Integer)

    # Metadata
    tags = Column(JSON, default=list)
    custom_fields = Column(JSON, default=dict)
    checklist_items = Column(JSON, default=list)  # [{"text": "...", "completed": true}]
    color_code = Column(String(7))  # hex

    # Approval workflow
    approval_status = Column(String(50), default="pending")  # pending, approved, rejected
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)

    # Completion actions (bidirectional integration)
    completion_actions = Column(JSON, default=dict)  # { "clear_alarm": true, "execute_command": {...} }
    completion_result = Column(JSON, default=dict)  # Log of what actions were taken

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True))
    completed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))


class TaskComment(Base):
    """Activity feed for tasks"""
    __tablename__ = "task_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    comment_type = Column(String(50), default="comment")  # comment, system, time_log, status_change, approval_action
    content = Column(Text)
    metadata = Column(JSON, default=dict)  # { "before_state": "...", "after_state": "..." }
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class TaskTimer(Base):
    """Time tracking for tasks"""
    __tablename__ = "task_timers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True))
    duration_minutes = Column(Integer, default=0)
    is_running = Column(Boolean, default=True)
    description = Column(Text)  # What was done during this time
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class TaskRule(Base):
    """Rules registry for automated task creation"""
    __tablename__ = "task_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    rule_name = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    is_system_rule = Column(Boolean, default=False)  # Premade vs custom

    # Trigger conditions
    trigger_type = Column(String(100), nullable=False)  # alarm_created, alarm_cleared, packml_state_change, oee_threshold, telemetry_threshold, scheduled_time, operation_completed, command_failed, maintenance_due
    trigger_conditions = Column(JSON, default=dict)  # { "severity": "critical", "asset_type": "3d_printer" }

    # Task template
    target_board_id = Column(UUID(as_uuid=True), ForeignKey("task_boards.id"))
    target_column_id = Column(UUID(as_uuid=True), ForeignKey("task_columns.id"))
    task_template = Column(JSON, default=dict)  # { "title": "...", "description": "...", "priority": "high", "task_type": "alarm_response" }

    # Automation settings
    auto_approve_emergency = Column(Boolean, default=False)
    auto_approve_timeout_minutes = Column(Integer, default=30)
    assignee_rule = Column(String(50), default="asset_owner")  # round_robin, asset_owner, supervisor, specific_user
    specific_assignee_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    notify_users = Column(JSON, default=list)  # User IDs to notify

    # Completion actions
    completion_actions = Column(JSON, default=dict)

    # Escalation config
    escalation_config = Column(JSON, default=dict)  # { "levels": [{"time_minutes": 15, "level": 1, "channels": ["push", "email"]}] }

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class TaskEscalation(Base):
    """Escalation log for tasks"""
    __tablename__ = "task_escalations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("task_rules.id"))
    escalation_level = Column(Integer, nullable=False)  # 1-5
    triggered_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at = Column(DateTime(timezone=True))
    notified_users = Column(JSON, default=list)  # User IDs notified
    actions_taken = Column(JSON, default=list)  # ["email_sent", "sms_sent", "reassigned"]
    notification_channels = Column(JSON, default=list)  # ["push", "email", "sms"]
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
