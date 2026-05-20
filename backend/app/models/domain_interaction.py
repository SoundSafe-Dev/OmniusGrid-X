"""
Domain Interaction Component for OmniusGrid Correlation AI Engine
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class DomainType(str, Enum):
    # Original 5 domains
    EDGE = "EDGE_AI_TELEMETRY"
    PROD = "PRODUCTION_OEE"
    LOG = "LOGISTICS_FLEET"
    COMP = "COMPLIANCE_REGISTRIES"
    SYS = "SYSTEM_INFRASTRUCTURE"
    
    # First expansion (15)
    MAT = "MATERIAL_REPLENISHMENT"
    OUT = "PRODUCTION_OUTPUT"
    PKG = "PACKAGING"
    DST = "DISTRIBUTION"
    MNT = "MAINTENANCE"
    QUA = "QUALITY_CONTROL"
    ENG = "ENERGY_MANAGEMENT"
    WRK = "WORKFORCE_MANAGEMENT"
    SUP = "SUPPLY_CHAIN"
    WHS = "WAREHOUSE_MANAGEMENT"
    CUS = "CUSTOMER_SERVICE"
    FIN = "FINANCE"
    SAF = "SAFETY"
    ENV = "ENVIRONMENTAL"
    PLN = "PLANNING_SCHEDULING"
    
    # Second expansion (20)
    CYB = "CYBERSECURITY"
    DTW = "DIGITAL_TWIN"
    IOT = "IT_OT_INTEGRATION"
    DAN = "DATA_ANALYTICS"
    PRJ = "PROJECT_MANAGEMENT"
    HRO = "HR_ORGANIZATIONAL"
    RGA = "REGULATORY_AUDIT"
    RSK = "RISK_MANAGEMENT"
    IRD = "INNOVATION_RD"
    CTR = "CONTRACT_MANAGEMENT"
    ALF = "ASSET_LIFECYCLE"
    POP = "PROCESS_OPTIMIZATION"
    SRL = "SUPPLIER_RELATIONSHIP"
    INO = "INVENTORY_OPTIMIZATION"
    CHM = "CHANGE_MANAGEMENT"
    KMG = "KNOWLEDGE_MANAGEMENT"
    BI = "BUSINESS_INTELLIGENCE"
    CIM = "CONTINUOUS_IMPROVEMENT"
    PLC = "PRODUCT_LIFECYCLE"
    MES = "MANUFACTURING_EXECUTION_SYSTEM"
    
    # Third expansion (7)
    FAC = "FACILITIES_MANAGEMENT"
    TOL = "TOOL_MANAGEMENT"
    CAL = "CALIBRATION"
    SPT = "SPARE_PARTS"
    DOC = "DOCUMENT_MANAGEMENT"
    WFM = "WORKFLOW_MANAGEMENT"
    ESG = "ESG"


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
