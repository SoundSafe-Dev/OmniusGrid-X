"""Pydantic Schemas for API"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, Field


# Asset Schemas
class AssetBase(BaseModel):
    name: str
    serial_number: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    connection_config: Dict[str, Any] = {}
    is_active: bool = True


class AssetCreate(AssetBase):
    organization_id: UUID
    workcell_id: Optional[UUID] = None
    asset_type_id: UUID


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    serial_number: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    connection_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    current_packml_state: Optional[str] = None


class AssetResponse(AssetBase):
    id: UUID
    organization_id: UUID
    workcell_id: Optional[UUID]
    asset_type_id: UUID
    current_packml_state: str
    last_seen: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Asset Type Schemas
class AssetTypeCreate(BaseModel):
    name: str
    category: str
    packml_config: Dict[str, Any] = {}
    telemetry_schema: Dict[str, Any] = {}
    action_space: Dict[str, Any] = {}


class AssetTypeResponse(AssetTypeCreate):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# Alarm Schemas
class AlarmCreate(BaseModel):
    asset_id: UUID
    alarm_code: str
    severity: str  # critical, high, medium, low, info
    message: str
    description: Optional[str] = None
    metadata: Dict[str, Any] = {}


class AlarmResponse(AlarmCreate):
    id: UUID
    is_active: bool
    is_acknowledged: bool
    acknowledged_by: Optional[UUID]
    acknowledged_at: Optional[datetime]
    acknowledged_comment: Optional[str]
    occurred_at: datetime
    cleared_at: Optional[datetime]

    class Config:
        from_attributes = True


class AlarmAcknowledge(BaseModel):
    comment: Optional[str] = None


# Operation Schemas
class OperationCreate(BaseModel):
    asset_id: UUID
    operation_name: str
    job_id: Optional[str] = None
    planned_duration: Optional[int] = None  # seconds
    metadata: Dict[str, Any] = {}


class OperationResponse(OperationCreate):
    id: UUID
    status: str
    packml_state_durations: Dict[str, Any]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    actual_duration: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


# Telemetry Schemas
class TelemetryPoint(BaseModel):
    timestamp: datetime
    metric_name: str
    value: float
    unit: Optional[str] = None
    packml_state: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TelemetryBatch(BaseModel):
    asset_id: UUID
    data: List[TelemetryPoint]


# Dashboard Schemas
class DashboardOverview(BaseModel):
    total_assets: int
    active_assets: int
    assets_by_state: Dict[str, int]
    active_alarms: int
    critical_alarms: int


class OEEMetrics(BaseModel):
    asset_id: UUID
    availability: float
    performance: float
    quality: float
    oee: float
    time_range: str


# Auth Schemas
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserLogin(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None
    organization_id: Optional[UUID] = None
    role: str = "operator"


# ==================== YMS Schemas ====================

class YardTrailerBase(BaseModel):
    trailer_number: str
    trailer_type: Optional[str] = None  # dry_van, reefer, flatbed, etc.
    status: str = "checked_in"  # checked_in, docked, yard, checked_out
    yard_location: Optional[str] = None
    seal_number: Optional[str] = None
    seal_status: str = "intact"  # intact, broken, missing
    weight_lbs: Optional[float] = None
    temperature_setpoint: Optional[float] = None
    temperature_actual: Optional[float] = None
    metadata: Dict[str, Any] = {}


class YardTrailerCreate(YardTrailerBase):
    organization_id: UUID
    carrier_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None
    shipment_id: Optional[UUID] = None


class YardTrailerUpdate(BaseModel):
    status: Optional[str] = None
    yard_location: Optional[str] = None
    seal_status: Optional[str] = None
    weight_lbs: Optional[float] = None
    dock_door_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None
    temperature_actual: Optional[float] = None
    check_out_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class YardTrailerResponse(YardTrailerBase):
    id: UUID
    organization_id: UUID
    carrier_id: Optional[UUID]
    driver_id: Optional[UUID]
    shipment_id: Optional[UUID]
    dock_door_id: Optional[UUID]
    check_in_at: datetime
    check_out_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DockDoorBase(BaseModel):
    door_number: str
    door_type: Optional[str] = None  # inbound, outbound, cross_dock
    status: str = "available"  # available, occupied, maintenance
    equipment_capabilities: Dict[str, Any] = {}
    is_active: bool = True


class DockDoorCreate(DockDoorBase):
    organization_id: UUID


class DockDoorUpdate(BaseModel):
    status: Optional[str] = None
    equipment_capabilities: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    current_trailer_id: Optional[UUID] = None


class DockDoorResponse(DockDoorBase):
    id: UUID
    organization_id: UUID
    current_trailer_id: Optional[UUID]
    last_occupied_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class YardMoveBase(BaseModel):
    from_location: str
    to_location: str
    move_type: Optional[str] = None  # check_in, dock, yard_relocate, check_out
    duration_seconds: Optional[float] = None
    metadata: Dict[str, Any] = {}


class YardMoveCreate(YardMoveBase):
    organization_id: UUID
    trailer_id: UUID
    jockey_driver_id: Optional[UUID] = None


class YardMoveResponse(YardMoveBase):
    id: UUID
    organization_id: UUID
    trailer_id: UUID
    jockey_driver_id: Optional[UUID]
    started_at: datetime
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class DriverWaitTimeBase(BaseModel):
    check_in_at: datetime
    docked_at: Optional[datetime] = None
    unloaded_at: Optional[datetime] = None
    check_out_at: Optional[datetime] = None
    total_wait_minutes: Optional[float] = None
    detention_minutes: Optional[float] = None
    demurrage_minutes: Optional[float] = None
    detention_rate: Optional[float] = None
    demurrage_rate: Optional[float] = None
    detention_charge: Optional[float] = None
    demurrage_charge: Optional[float] = None
    is_billed: bool = False
    metadata: Dict[str, Any] = {}


class DriverWaitTimeCreate(DriverWaitTimeBase):
    organization_id: UUID
    driver_id: UUID
    trailer_id: Optional[UUID] = None


class DriverWaitTimeResponse(DriverWaitTimeBase):
    id: UUID
    organization_id: UUID
    driver_id: UUID
    trailer_id: Optional[UUID]
    updated_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class YardCheckPointBase(BaseModel):
    checkpoint_type: str  # gate_in, guard_shack, weigh_station, gate_out
    checkpoint_name: Optional[str] = None
    weight_lbs: Optional[float] = None
    inspection_status: Optional[str] = None  # passed, failed, pending
    inspector_id: Optional[UUID] = None
    metadata: Dict[str, Any] = {}


class YardCheckPointCreate(YardCheckPointBase):
    organization_id: UUID
    trailer_id: UUID


class YardCheckPointResponse(YardCheckPointBase):
    id: UUID
    organization_id: UUID
    trailer_id: UUID
    passed_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== TMS Schemas ====================

class CarrierBase(BaseModel):
    carrier_name: str
    dot_number: Optional[str] = None
    mc_number: Optional[str] = None
    ctpat_certified: bool = False
    ctpat_expires_at: Optional[datetime] = None
    insurance_on_file: bool = False
    insurance_expires_at: Optional[datetime] = None
    safety_rating: Optional[str] = None  # satisfactory, conditional, unsatisfactory
    csa_score: Optional[float] = None
    contract_rate: Dict[str, Any] = {}
    is_active: bool = True
    contact_info: Dict[str, Any] = {}


class CarrierCreate(CarrierBase):
    organization_id: UUID


class CarrierUpdate(BaseModel):
    carrier_name: Optional[str] = None
    dot_number: Optional[str] = None
    mc_number: Optional[str] = None
    ctpat_certified: Optional[bool] = None
    ctpat_expires_at: Optional[datetime] = None
    insurance_on_file: Optional[bool] = None
    insurance_expires_at: Optional[datetime] = None
    safety_rating: Optional[str] = None
    csa_score: Optional[float] = None
    contract_rate: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    contact_info: Optional[Dict[str, Any]] = None


class CarrierResponse(CarrierBase):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DriverBase(BaseModel):
    first_name: str
    last_name: str
    license_number: Optional[str] = None
    license_state: Optional[str] = None
    cdl_class: Optional[str] = None  # A, B, C
    hazmat_endorsed: bool = False
    medical_cert_expires: Optional[datetime] = None
    dq_file_complete: bool = False
    current_hos_status: Optional[str] = None  # on_duty, driving, off_duty, sleeper
    hos_drive_hours_today: float = 0
    hos_on_duty_hours_today: float = 0
    hos_cycle_hours: float = 0
    eld_device_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: bool = True


class DriverCreate(DriverBase):
    organization_id: UUID
    carrier_id: Optional[UUID] = None


class DriverUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    license_number: Optional[str] = None
    license_state: Optional[str] = None
    cdl_class: Optional[str] = None
    hazmat_endorsed: Optional[bool] = None
    medical_cert_expires: Optional[datetime] = None
    dq_file_complete: Optional[bool] = None
    current_hos_status: Optional[str] = None
    hos_drive_hours_today: Optional[float] = None
    hos_on_duty_hours_today: Optional[float] = None
    hos_cycle_hours: Optional[float] = None
    is_active: Optional[bool] = None


class DriverResponse(DriverBase):
    id: UUID
    organization_id: UUID
    carrier_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ShipmentBase(BaseModel):
    shipment_number: str
    pro_number: Optional[str] = None
    bol_number: Optional[str] = None
    shipment_type: str = "outbound"  # inbound, outbound, transfer
    status: str = "planned"  # planned, dispatched, in_transit, delivered, cancelled
    origin: Dict[str, Any] = {}
    destination: Dict[str, Any] = {}
    scheduled_pickup: Optional[datetime] = None
    actual_pickup: Optional[datetime] = None
    scheduled_delivery: Optional[datetime] = None
    actual_delivery: Optional[datetime] = None
    priority: str = "normal"  # low, normal, high, critical
    total_weight_lbs: Optional[float] = None
    total_pieces: Optional[int] = None
    hazmat: bool = False
    temperature_required: bool = False
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    metadata: Dict[str, Any] = {}


class ShipmentCreate(ShipmentBase):
    organization_id: UUID
    carrier_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None
    trailer_id: Optional[UUID] = None
    route_id: Optional[UUID] = None


class ShipmentUpdate(BaseModel):
    status: Optional[str] = None
    driver_id: Optional[UUID] = None
    trailer_id: Optional[UUID] = None
    actual_pickup: Optional[datetime] = None
    actual_delivery: Optional[datetime] = None
    priority: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ShipmentResponse(ShipmentBase):
    id: UUID
    organization_id: UUID
    carrier_id: Optional[UUID]
    driver_id: Optional[UUID]
    trailer_id: Optional[UUID]
    route_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RouteBase(BaseModel):
    route_name: Optional[str] = None
    origin: Dict[str, Any] = {}
    destination: Dict[str, Any] = {}
    waypoints: List[Dict[str, Any]] = []
    total_distance_miles: Optional[float] = None
    estimated_duration_hours: Optional[float] = None
    fuel_cost_estimate: Optional[float] = None
    toll_cost_estimate: Optional[float] = None
    optimization_criteria: str = "balanced"  # fastest, cheapest, balanced
    is_active: bool = True


class RouteCreate(RouteBase):
    organization_id: UUID


class RouteUpdate(BaseModel):
    route_name: Optional[str] = None
    waypoints: Optional[List[Dict[str, Any]]] = None
    total_distance_miles: Optional[float] = None
    estimated_duration_hours: Optional[float] = None
    is_active: Optional[bool] = None


class RouteResponse(RouteBase):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LoadPlanBase(BaseModel):
    load_sequence: List[Dict[str, Any]] = []
    weight_distribution: Dict[str, Any] = {}
    space_utilization_percent: Optional[float] = None
    temperature_zones: List[Dict[str, Any]] = []
    special_instructions: Optional[str] = None
    is_executed: bool = False
    executed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}


class LoadPlanCreate(LoadPlanBase):
    organization_id: UUID
    shipment_id: UUID
    trailer_id: Optional[UUID] = None
    planned_by: Optional[UUID] = None


class LoadPlanResponse(LoadPlanBase):
    id: UUID
    organization_id: UUID
    shipment_id: UUID
    trailer_id: Optional[UUID]
    planned_by: Optional[UUID]
    planned_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FreightChargeBase(BaseModel):
    charge_type: str  # linehaul, fuel, detention, demurrage, accessorial
    charge_description: Optional[str] = None
    rate_basis: Optional[str] = None  # per_mile, per_pound, flat, hourly
    quantity: Optional[float] = None
    rate: Optional[float] = None
    amount: float
    currency: str = "USD"
    is_billed: bool = False
    billed_at: Optional[datetime] = None
    invoice_number: Optional[str] = None
    approved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}


class FreightChargeCreate(FreightChargeBase):
    organization_id: UUID
    shipment_id: UUID
    carrier_id: Optional[UUID] = None
    approved_by: Optional[UUID] = None


class FreightChargeResponse(FreightChargeBase):
    id: UUID
    organization_id: UUID
    shipment_id: UUID
    carrier_id: Optional[UUID]
    approved_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==================== Correlation Schemas ====================

class DockAppointmentBase(BaseModel):
    appointment_type: str  # pickup, delivery, transfer
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    status: str = "scheduled"  # scheduled, in_progress, completed, cancelled, no_show
    priority: str = "normal"
    compliance_required: bool = False
    metadata: Dict[str, Any] = {}


class DockAppointmentCreate(DockAppointmentBase):
    organization_id: UUID
    dock_door_id: UUID
    trailer_id: Optional[UUID] = None
    shipment_id: Optional[UUID] = None
    operation_id: Optional[UUID] = None
    carrier_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None


class DockAppointmentUpdate(BaseModel):
    status: Optional[str] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    priority: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DockAppointmentResponse(DockAppointmentBase):
    id: UUID
    organization_id: UUID
    dock_door_id: UUID
    trailer_id: Optional[UUID]
    shipment_id: Optional[UUID]
    operation_id: Optional[UUID]
    carrier_id: Optional[UUID]
    driver_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TruckAssetCorrelationBase(BaseModel):
    truck_arrived_at: Optional[datetime] = None
    asset_ready_at: Optional[datetime] = None
    asset_completion_forecast: Optional[datetime] = None
    readiness_gap_minutes: Optional[float] = None
    load_start_at: Optional[datetime] = None
    load_complete_at: Optional[datetime] = None
    detention_incurred: bool = False
    detention_charge: Optional[float] = None
    efficiency_score: Optional[float] = None
    metadata: Dict[str, Any] = {}


class TruckAssetCorrelationCreate(TruckAssetCorrelationBase):
    organization_id: UUID
    shipment_id: Optional[UUID] = None
    trailer_id: Optional[UUID] = None
    asset_id: Optional[UUID] = None
    operation_id: Optional[UUID] = None


class TruckAssetCorrelationResponse(TruckAssetCorrelationBase):
    id: UUID
    organization_id: UUID
    shipment_id: Optional[UUID]
    trailer_id: Optional[UUID]
    asset_id: Optional[UUID]
    operation_id: Optional[UUID]
    created_at: datetime

    class Config:
        from_attributes = True


class LoadQualityLogBase(BaseModel):
    defect_type: Optional[str] = None  # wrong_product, damaged, short, over, temp_excursion
    severity: Optional[str] = None  # minor, major, critical
    quantity_affected: Optional[float] = None
    manufacturing_correlation_score: Optional[float] = None
    carrier_liable: bool = False
    claim_filed: bool = False
    claim_amount: Optional[float] = None
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}


class LoadQualityLogCreate(LoadQualityLogBase):
    organization_id: UUID
    shipment_id: Optional[UUID] = None
    trailer_id: Optional[UUID] = None
    asset_id: Optional[UUID] = None
    operation_id: Optional[UUID] = None
    root_cause_asset: Optional[UUID] = None
    root_cause_operation: Optional[UUID] = None


class LoadQualityLogResponse(LoadQualityLogBase):
    id: UUID
    organization_id: UUID
    shipment_id: Optional[UUID]
    trailer_id: Optional[UUID]
    asset_id: Optional[UUID]
    operation_id: Optional[UUID]
    root_cause_asset: Optional[UUID]
    root_cause_operation: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==================== Analytics Schemas ====================

class DwellTimeAnalytics(BaseModel):
    """Yard dwell time metrics"""
    trailer_id: UUID
    trailer_number: str
    check_in_at: datetime
    check_out_at: Optional[datetime]
    dwell_hours: float
    is_detention: bool
    detention_charge: Optional[float]


class DockScheduleCorrelationResponse(BaseModel):
    """Dock schedule aligned with production"""
    dock_appointment: DockAppointmentResponse
    operation: Optional[OperationResponse]
    asset: Optional[AssetResponse]
    readiness_status: str  # on_time, early, late, at_risk
    estimated_completion: Optional[datetime]
    detention_risk_score: float  # 0-100


class LogisticsCorrelationResponse(BaseModel):
    """Cross-domain correlation data"""
    truck_arrivals_today: int
    on_time_arrivals: int
    late_arrivals: int
    avg_dwell_time_hours: float
    total_detention_charges: float
    production_dock_sync_percent: float
    safety_incidents_today: int
    hos_violations: int


class DetentionRiskPrediction(BaseModel):
    """Predicted detention risk for upcoming appointments"""
    appointment_id: UUID
    risk_score: float  # 0-100
    risk_level: str  # low, medium, high, critical
    factors: List[str]
    predicted_detention_minutes: Optional[float]
    recommended_actions: List[str]
