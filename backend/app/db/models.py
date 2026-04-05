"""Database models"""

import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, String, DateTime, Boolean, Numeric, JSON, ForeignKey, Text, BigInteger
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
    metadata = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Telemetry(Base):
    __tablename__ = "telemetry"
    
    time = Column(DateTime(timezone=True), primary_key=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), primary_key=True)
    metric_name = Column(String(100), primary_key=True)
    value = Column(Numeric, nullable=False)
    unit = Column(String(50))
    packml_state = Column(String(50))
    metadata = Column(JSON, default={})
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
    metadata = Column(JSON, default={})


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
    metadata = Column(JSON, default={})
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
