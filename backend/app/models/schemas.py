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
