"""
Correlation AI Integration API Endpoints

API endpoints for integrating correlation AI analysis with registries and Kanban system.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.db.database import get_db
from app.api.auth import get_current_active_user
from app.db.models import User
from app.services.correlation_registry_integration import correlation_registry_integration
from app.services.correlation_ai_engine import correlation_ai_engine
import structlog

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/engines/correlation/integration", tags=["correlation-integration"])


# ==================== Request/Response Schemas ====================

class CorrelationAnalysisRequest(BaseModel):
    """Request for correlation analysis and integration"""
    metrics: Dict[str, Any] = Field(..., description="Operational metrics data")
    domains: List[str] = Field(default=[], description="Affected domains (auto-detected if empty)")
    auto_create_tasks: bool = Field(default=True, description="Automatically create Kanban tasks")
    auto_create_registry_items: bool = Field(default=True, description="Automatically create registry items")
    auto_create_correlations: bool = Field(default=True, description="Automatically create correlations")


class RegistryInitializationRequest(BaseModel):
    """Request for registry initialization"""
    organization_id: Optional[UUID] = Field(None, description="Organization ID (uses current user's org if not provided)")


class CorrelationAnalysisResponse(BaseModel):
    """Response from correlation analysis and integration"""
    scenario_id: str
    correlation_analysis: str
    risk_score: float
    recommended_kanban_tasks: List[Dict[str, Any]]
    recommended_actions: List[Dict[str, Any]]
    compliance_implications: Optional[List[str]]
    integration_result: Dict[str, List[str]]


class RegistryInitializationResponse(BaseModel):
    """Response from registry initialization"""
    organization_id: str
    registries_created: int
    registry_ids: Dict[str, str]
    items_created: int


# ==================== Endpoints ====================

@router.post("/analyze", response_model=CorrelationAnalysisResponse)
async def analyze_and_integrate(
    request: CorrelationAnalysisRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Run correlation AI analysis and automatically create registries, tasks, and correlations.
    
    This endpoint:
    1. Runs correlation AI analysis on the provided metrics
    2. Determines affected domains from the analysis
    3. Creates registry items for affected domains (if enabled)
    4. Creates Kanban tasks from recommendations (if enabled)
    5. Creates correlations between registry items and tasks (if enabled)
    6. Sends alert notifications for high-risk scenarios
    """
    logger.info("correlation_analysis_requested", user_id=str(current_user.id))
    
    # Create correlation scenario from metrics
    from app.models.domain_interaction import CorrelationScenario, DomainType, CrossDomainLink, OperationalMetric
    
    # Convert domains to DomainType enum
    domain_types = [DomainType(d) for d in request.domains] if request.domains else []
    
    # Create operational metrics from input
    operational_metrics = []
    for key, value in request.metrics.items():
        metric = OperationalMetric(
            metric_name=key,
            value=value.get("value", 0) if isinstance(value, dict) else value,
            unit=value.get("unit") if isinstance(value, dict) else None,
            timestamp=value.get("timestamp") if isinstance(value, dict) else None,
            meta_data=value
        )
        operational_metrics.append(metric)
    
    # Create scenario
    scenario = CorrelationScenario(
        scenario_id=f"scenario-{current_user.id}-{int(datetime.utcnow().timestamp())}",
        active_domains=domain_types,
        operational_metrics=operational_metrics,
        domain_links=[]  # Will be populated by AI
    )
    
    # Run AI analysis
    analysis_result = await correlation_ai_engine.analyze_scenario(scenario, db)
    
    # Parse analysis result
    correlation_analysis = analysis_result.get("predicted_root_cause", "")
    risk_score = analysis_result.get("risk_score", 0)
    recommended_tasks = analysis_result.get("target_kanban_tasks", [])
    recommended_actions = analysis_result.get("remediation_commands", [])
    compliance_implications = analysis_result.get("compliance_implications")
    
    # Format for integration
    integration_input = {
        "correlation_analysis": correlation_analysis,
        "risk_score": risk_score,
        "recommended_kanban_tasks": recommended_tasks,
        "recommended_actions": recommended_actions,
        "compliance_implications": compliance_implications
    }
    
    # Process integration in background
    if request.auto_create_tasks or request.auto_create_registry_items or request.auto_create_correlations:
        background_tasks.add_task(
            process_integration_background,
            integration_input,
            current_user.organization_id,
            str(current_user.id),
            request.auto_create_tasks,
            request.auto_create_registry_items,
            request.auto_create_correlations
        )
    
    return CorrelationAnalysisResponse(
        scenario_id=analysis_result.get("scenario_id", ""),
        correlation_analysis=correlation_analysis,
        risk_score=risk_score,
        recommended_kanban_tasks=recommended_tasks,
        recommended_actions=recommended_actions,
        compliance_implications=compliance_implications,
        integration_result={"message": "Integration processing in background"}
    )


async def process_integration_background(
    analysis_result: Dict[str, Any],
    organization_id: UUID,
    user_id: str,
    create_tasks: bool,
    create_registry_items: bool,
    create_correlations: bool
):
    """Background task for processing integration"""
    from app.db.database import AsyncSessionLocal
    
    async with AsyncSessionLocal() as db:
        try:
            user_uuid = UUID(user_id)
            
            if create_registry_items or create_tasks or create_correlations:
                result = await correlation_registry_integration.process_correlation_analysis(
                    analysis_result,
                    organization_id,
                    db,
                    user_uuid
                )
                logger.info("background_integration_complete", result=result)
        except Exception as e:
            logger.error("background_integration_failed", error=str(e))


@router.post("/initialize-registries", response_model=RegistryInitializationResponse)
async def initialize_registries(
    request: RegistryInitializationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Initialize registries for all 47 operational domains for the organization.
    
    This creates:
    - 47 actionable registries (one per operational domain)
    - Default registry items for each domain
    - Compliance standard mappings
    """
    organization_id = request.organization_id or current_user.organization_id
    
    logger.info("initializing_registries", organization_id=str(organization_id))
    
    # Initialize registries
    registry_ids = await correlation_registry_integration.initialize_registries_for_organization(
        organization_id,
        db,
        current_user.id
    )
    
    # Count total items created
    from app.db.models import ActionableRegistryItem
    result = await db.execute(
        select(func.count(ActionableRegistryItem.id)).where(
            ActionableRegistryItem.registry_id.in_(registry_ids.values())
        )
    )
    items_count = result.scalar() or 0
    
    return RegistryInitializationResponse(
        organization_id=str(organization_id),
        registries_created=len(registry_ids),
        registry_ids={k: str(v) for k, v in registry_ids.items()},
        items_created=items_count
    )


@router.get("/registry-mapping")
async def get_registry_mapping(
    current_user: User = Depends(get_current_active_user)
):
    """
    Get the domain to registry mapping configuration.
    
    Returns the mapping of all 47 operational domains to their registry configurations.
    """
    from app.services.correlation_registry_integration import DOMAIN_REGISTRY_MAPPING
    
    return {
        "domain_count": len(DOMAIN_REGISTRY_MAPPING),
        "mappings": DOMAIN_REGISTRY_MAPPING
    }


@router.get("/task-type-mapping")
async def get_task_type_mapping(
    current_user: User = Depends(get_current_active_user)
):
    """
    Get the Kanban task type mapping configuration.
    
    Returns the mapping of correlation AI task recommendations to Kanban task types.
    """
    from app.services.correlation_registry_integration import KANBAN_TASK_TYPE_MAPPING
    
    return {
        "task_type_count": len(KANBAN_TASK_TYPE_MAPPING),
        "mappings": KANBAN_TASK_TYPE_MAPPING
    }


@router.post("/test-integration")
async def test_integration(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Test the correlation integration with sample data.
    
    This endpoint:
    1. Uses sample metrics from the dataset
    2. Runs correlation AI analysis
    3. Creates registries, tasks, and correlations
    4. Returns the complete integration result
    """
    logger.info("testing_correlation_integration", user_id=str(current_user.id))
    
    # Sample metrics from dataset (Logistics Fleet example)
    sample_metrics = {
        "category": "appointment_adherence",
        "item": "45%",
        "value": 24.03,
        "status": "critical"
    }
    
    # Create request
    request = CorrelationAnalysisRequest(
        metrics=sample_metrics,
        domains=["LOGISTICS_FLEET"],
        auto_create_tasks=True,
        auto_create_registry_items=True,
        auto_create_correlations=True
    )
    
    # Process synchronously for testing
    from app.models.domain_interaction import CorrelationScenario, DomainType, CrossDomainLink, OperationalMetric
    from datetime import datetime
    
    domain_types = [DomainType("LOGISTICS_FLEET")]
    
    operational_metrics = [
        OperationalMetric(
            metric_name="appointment_adherence",
            value=24.03,
            unit="%",
            timestamp=datetime.utcnow(),
            meta_data=sample_metrics
        )
    ]
    
    scenario = CorrelationScenario(
        scenario_id=f"test-{current_user.id}-{int(datetime.utcnow().timestamp())}",
        active_domains=domain_types,
        operational_metrics=operational_metrics,
        domain_links=[]
    )
    
    # Run AI analysis
    analysis_result = await correlation_ai_engine.analyze_scenario(scenario, db)
    
    # Parse analysis result
    correlation_analysis = analysis_result.get("predicted_root_cause", "")
    risk_score = analysis_result.get("risk_score", 0)
    recommended_tasks = analysis_result.get("target_kanban_tasks", [])
    recommended_commands = analysis_result.get("remediation_commands", [])
    compliance_implications = analysis_result.get("compliance_implications")
    
    # Format for integration
    integration_input = {
        "correlation_analysis": correlation_analysis,
        "risk_score": risk_score,
        "recommended_kanban_tasks": recommended_tasks,
        "recommended_actions": recommended_commands,
        "compliance_implications": compliance_implications
    }
    
    # Process integration
    integration_result = await correlation_registry_integration.process_correlation_analysis(
        integration_input,
        current_user.organization_id,
        db,
        current_user.id
    )
    
    return {
        "analysis_result": analysis_result,
        "integration_result": integration_result,
        "test_status": "success"
    }


# Import for background task
from datetime import datetime
from sqlalchemy import func
