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
    refresh_token: str


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


# ==================== Kanban Task Management Schemas ====================

class TaskBoardBase(BaseModel):
    name: str = "Main Operations Board"
    board_type: str = "unified"  # unified, production, maintenance, quality, safety, logistics
    default_view_config: Dict[str, Any] = {}


class TaskBoardCreate(TaskBoardBase):
    organization_id: str


class TaskBoardResponse(TaskBoardBase):
    id: str
    organization_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskColumnBase(BaseModel):
    name: str
    position: int
    wip_limit: int = 5
    column_type: str  # backlog, triage, in_progress, review, rejected, done
    color: str = "#6366F1"
    is_collapsed: bool = False
    auto_archive_days: int = 7


class TaskColumnCreate(TaskColumnBase):
    board_id: str


class TaskColumnResponse(TaskColumnBase):
    id: str
    board_id: str
    created_at: datetime
    updated_at: datetime
    task_count: Optional[int] = 0  # Computed field

    class Config:
        from_attributes = True


class TaskChecklistItem(BaseModel):
    text: str
    completed: bool = False


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    task_type: str  # production_job, maintenance_pm, maintenance_cm, quality_inspection, safety_check, alarm_response, command_execution, material_request, changeover, custom
    priority: str = "medium"  # low, medium, high, critical, emergency
    status: str = "draft"
    planned_start: Optional[datetime] = None
    planned_duration: Optional[int] = None  # minutes
    due_date: Optional[datetime] = None
    estimated_effort_minutes: Optional[int] = None
    tags: List[str] = []
    checklist_items: List[TaskChecklistItem] = []
    color_code: Optional[str] = None


class TaskCreate(TaskBase):
    board_id: str
    column_id: str
    assigned_to: Optional[str] = None
    asset_id: Optional[str] = None
    operation_id: Optional[str] = None
    alarm_id: Optional[str] = None
    command_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    custom_fields: Dict[str, Any] = {}
    completion_actions: Dict[str, Any] = {}


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    column_id: Optional[str] = None
    position: Optional[int] = None
    progress_percent: Optional[int] = None
    checklist_items: Optional[List[TaskChecklistItem]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    due_date: Optional[datetime] = None
    color_code: Optional[str] = None


class TaskResponse(TaskBase):
    id: UUID
    board_id: UUID
    column_id: UUID
    position: int
    assigned_to: Optional[UUID]
    assigned_by: Optional[UUID]
    assigned_at: Optional[datetime]
    actual_start: Optional[datetime]
    actual_end: Optional[datetime]
    asset_id: Optional[UUID]
    operation_id: Optional[UUID]
    alarm_id: Optional[str]
    command_id: Optional[str]
    work_order_id: Optional[str]
    parent_task_id: Optional[UUID]
    rule_id: Optional[UUID]
    progress_percent: int
    time_logged_minutes: int
    custom_fields: Dict[str, Any]
    approval_status: str
    approved_by: Optional[UUID]
    approved_at: Optional[datetime]
    rejection_reason: Optional[str]
    completion_actions: Dict[str, Any]
    completion_result: Dict[str, Any]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    completed_by: Optional[UUID]

    class Config:
        from_attributes = True


class TaskMoveRequest(BaseModel):
    target_column_id: str
    position: Optional[int] = None


class TaskApprovalRequest(BaseModel):
    action: str  # approve, reject
    reason: Optional[str] = None  # Required for reject


class TaskCommentBase(BaseModel):
    content: str
    comment_type: str = "comment"  # comment, system, time_log, status_change, approval_action


class TaskCommentCreate(TaskCommentBase):
    task_id: UUID


class TaskCommentResponse(TaskCommentBase):
    id: UUID
    task_id: UUID
    user_id: Optional[UUID]
    extra_data: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class TaskTimerStart(BaseModel):
    description: Optional[str] = None


class TaskTimerStop(BaseModel):
    description: Optional[str] = None


class TaskTimerResponse(BaseModel):
    id: UUID
    task_id: UUID
    user_id: UUID
    started_at: datetime
    ended_at: Optional[datetime]
    duration_minutes: int
    is_running: bool
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class TaskRuleBase(BaseModel):
    rule_name: str
    description: Optional[str] = None
    trigger_type: str
    trigger_conditions: Dict[str, Any] = {}
    task_template: Dict[str, Any] = {}
    auto_approve_emergency: bool = False
    auto_approve_timeout_minutes: int = 30
    assignee_rule: str = "asset_owner"  # round_robin, asset_owner, supervisor, specific_user
    escalation_config: Dict[str, Any] = {}
    completion_actions: Dict[str, Any] = {}


class TaskRuleCreate(TaskRuleBase):
    organization_id: UUID
    target_board_id: Optional[UUID] = None
    target_column_id: Optional[UUID] = None
    specific_assignee_id: Optional[UUID] = None
    notify_users: List[UUID] = []


class TaskRuleUpdate(BaseModel):
    rule_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    trigger_conditions: Optional[Dict[str, Any]] = None
    task_template: Optional[Dict[str, Any]] = None
    auto_approve_emergency: Optional[bool] = None
    auto_approve_timeout_minutes: Optional[int] = None
    assignee_rule: Optional[str] = None
    escalation_config: Optional[Dict[str, Any]] = None


class TaskRuleResponse(TaskRuleBase):
    id: UUID
    organization_id: UUID
    is_active: bool
    is_system_rule: bool
    target_board_id: Optional[UUID]
    target_column_id: Optional[UUID]
    specific_assignee_id: Optional[UUID]
    notify_users: List[UUID]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskRuleTestRequest(BaseModel):
    sample_data: Dict[str, Any]  # Simulated trigger data to test against


class TaskRuleTestResponse(BaseModel):
    would_trigger: bool
    matched_conditions: List[str]
    generated_task_preview: Optional[Dict[str, Any]]


class KanbanViewFilter(BaseModel):
    view_type: str = "all"  # all, by_asset, by_workcell, by_type, by_priority, by_assignee
    asset_id: Optional[UUID] = None
    workcell_id: Optional[UUID] = None
    task_type: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[UUID] = None
    status: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class KanbanBoardData(BaseModel):
    board: TaskBoardResponse
    columns: List[TaskColumnResponse]
    tasks: List[TaskResponse]
    view_config: Dict[str, Any]


class KanbanMetrics(BaseModel):
    total_tasks: int
    tasks_by_column: Dict[str, int]
    tasks_by_priority: Dict[str, int]
    tasks_awaiting_approval: int
    overdue_tasks: int
    avg_cycle_time_minutes: Optional[float]
    tasks_completed_today: int
    active_escalations: int


class KanbanWorkloadItem(BaseModel):
    user_id: UUID
    user_name: str
    assigned_tasks: int
    in_progress_tasks: int
    overdue_tasks: int
    avg_completion_time: Optional[float]


class KanbanWorkloadResponse(BaseModel):
    workloads: List[KanbanWorkloadItem]


class TaskEscalationResponse(BaseModel):
    id: UUID
    task_id: UUID
    rule_id: Optional[UUID]
    escalation_level: int
    triggered_at: datetime
    resolved_at: Optional[datetime]
    notified_users: List[UUID]
    actions_taken: List[str]
    notification_channels: List[str]

    class Config:
        from_attributes = True


# ============ Actionable Registries Schemas ============

class ActionableRegistryBase(BaseModel):
    registry_name: str
    registry_type: str  # safety, quality, environmental, operational, regulatory
    registry_category: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    is_compliance: bool = False
    frequency: Optional[str] = None  # daily, weekly, monthly, quarterly, annually, as_needed
    next_due_date: Optional[datetime] = None
    last_completed_date: Optional[datetime] = None
    compliance_score: int = 0
    priority_level: str = "medium"  # low, medium, high, critical
    assigned_owner_id: Optional[UUID] = None
    assigned_team_id: Optional[UUID] = None
    reference_url: Optional[str] = None
    checklist_requirements: List[Dict[str, Any]] = []
    meta_data: Dict[str, Any] = {}


class ActionableRegistryCreate(ActionableRegistryBase):
    pass


class ActionableRegistryUpdate(BaseModel):
    registry_name: Optional[str] = None
    registry_type: Optional[str] = None
    registry_category: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_compliance: Optional[bool] = None
    frequency: Optional[str] = None
    next_due_date: Optional[datetime] = None
    last_completed_date: Optional[datetime] = None
    compliance_score: Optional[int] = None
    priority_level: Optional[str] = None
    assigned_owner_id: Optional[UUID] = None
    assigned_team_id: Optional[UUID] = None
    reference_url: Optional[str] = None
    checklist_requirements: Optional[List[Dict[str, Any]]] = None
    meta_data: Optional[Dict[str, Any]] = None


class ActionableRegistryResponse(ActionableRegistryBase):
    id: UUID
    organization_id: UUID
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ActionableRegistryItemBase(BaseModel):
    item_code: str
    item_name: str
    item_description: Optional[str] = None
    severity_level: str = "medium"  # low, medium, high, critical
    is_active: bool = True
    is_required: bool = True
    completion_criteria: Optional[str] = None
    verification_method: Optional[str] = None  # inspection, test, documentation, audit
    estimated_effort_minutes: Optional[int] = None
    related_task_id: Optional[UUID] = None
    last_completed_at: Optional[datetime] = None
    next_due_at: Optional[datetime] = None
    completion_frequency: Optional[str] = None  # daily, weekly, monthly, quarterly, annually
    compliance_score: int = 0
    risk_score: int = 0
    meta_data: Dict[str, Any] = {}


class ActionableRegistryItemCreate(ActionableRegistryItemBase):
    registry_id: UUID


class ActionableRegistryItemUpdate(BaseModel):
    item_code: Optional[str] = None
    item_name: Optional[str] = None
    item_description: Optional[str] = None
    severity_level: Optional[str] = None
    is_active: Optional[bool] = None
    is_required: Optional[bool] = None
    completion_criteria: Optional[str] = None
    verification_method: Optional[str] = None
    estimated_effort_minutes: Optional[int] = None
    related_task_id: Optional[UUID] = None
    last_completed_at: Optional[datetime] = None
    next_due_at: Optional[datetime] = None
    completion_frequency: Optional[str] = None
    compliance_score: Optional[int] = None
    risk_score: Optional[int] = None
    meta_data: Optional[Dict[str, Any]] = None


class ActionableRegistryItemResponse(ActionableRegistryItemBase):
    id: UUID
    registry_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DataCorrelationBase(BaseModel):
    correlation_type: str  # task_to_registry, task_to_asset, task_to_alarm, registry_to_asset
    source_type: str  # task, registry_item, asset, alarm, operation
    source_id: Optional[UUID] = None
    target_type: str  # task, registry_item, asset, alarm, operation
    target_id: Optional[UUID] = None
    correlation_strength: int = 50  # 0-100
    correlation_method: str = "manual"  # manual, automated, ai_suggested
    confidence_score: int = 0  # 0-100
    is_active: bool = True
    is_bidirectional: bool = False
    correlation_meta_data: Dict[str, Any] = {}


class DataCorrelationCreate(DataCorrelationBase):
    pass


class DataCorrelationUpdate(BaseModel):
    correlation_strength: Optional[int] = None
    confidence_score: Optional[int] = None
    is_active: Optional[bool] = None


class DataCorrelationResponse(DataCorrelationBase):
    id: UUID
    organization_id: UUID
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
