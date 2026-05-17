"""
Domain Interaction Component for OmniusGrid Correlation AI Engine
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class DomainType(str, Enum):
    EDGE = "EDGE_AI_TELEMETRY"
    PROD = "PRODUCTION_OEE"
    LOG = "LOGISTICS_FLEET"
    COMP = "COMPLIANCE_REGISTRIES"
    SYS = "SYSTEM_INFRASTRUCTURE"


class OperationalMetric(BaseModel):
    endpoint: str = Field(..., description="OmniusGrid API endpoint source")
    payload_snapshot: Dict[str, Any] = Field(..., description="Raw state data from endpoint")
    timestamp: Optional[str] = Field(None, description="ISO timestamp of data capture")


class CrossDomainLink(BaseModel):
    source_domain: DomainType
    target_domain: DomainType
    interaction_key: str = Field(..., description="Unifying token (asset_id, trailer_id, etc.)")
    severity_impact: float = Field(..., ge=0.0, le=1.0, description="Cascading risk factor (0-1)")
    correlation_type: Optional[str] = Field(None, description="Type of correlation")


class CorrelationScenario(BaseModel):
    scenario_id: str
    active_domains: List[DomainType]
    domain_links: List[CrossDomainLink]
    ingested_metrics: List[OperationalMetric]
    predicted_root_cause: Optional[str] = None
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    target_kanban_tasks: Optional[List[Dict[str, Any]]] = None
    remediation_commands: Optional[List[Dict[str, Any]]] = None
    compliance_implications: Optional[List[str]] = None


class FineTuningMessage(BaseModel):
    role: str = Field(..., description="Message role: system, user, or model")
    content: str = Field(..., description="Message content")


class FineTuningExample(BaseModel):
    messages: List[FineTuningMessage]
