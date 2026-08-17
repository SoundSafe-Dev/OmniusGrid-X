"""
Correlation AI Integration API Endpoints

API endpoints for integrating correlation AI analysis with registries and Kanban system.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.tenant import get_tenant_db, tenant_session
from app.api.auth import get_current_active_user
from app.db.models import User
from app.services.correlation_registry_integration import correlation_registry_integration
from app.services.correlation_ai_engine import correlation_ai_engine
import structlog

logger = structlog.get_logger()

from app.middleware.rbac import require_admin, require_operator_or_admin

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
    #: The ids created by integration, keyed by kind — `registry_items`, `kanban_tasks`,
    #: `correlations`, `alerts`. `process_correlation_analysis` returns exactly that shape.
    integration_result: Dict[str, List[str]]
    #: True when integration was handed to a background task, so the lists above are empty
    #: because the work has not run yet rather than because it produced nothing (FS-742).
    #:
    #: THIS FIELD EXISTS BECAUSE THE ROUTE USED TO LIE IN A WAY THAT 500'd. The background
    #: branch returned `integration_result={"message": "Integration processing in
    #: background"}` — a string where the model declares `List[str]` — so FastAPI failed to
    #: serialise its own response and the endpoint answered **500** for every well-formed
    #: request that took that path. One of the eight operations in the whole API still
    #: returning a 500 under the contract gate.
    #:
    #: Widening the type to `Dict[str, Any]` would have silenced it and cost the contract:
    #: rule 187 — a permissive response model is not a contract. The state being described
    #: is "queued", which is a different fact from "produced nothing", so it gets its own
    #: field and the shape stays honest.
    integration_queued: bool = False


class RegistryInitializationResponse(BaseModel):
    """Response from registry initialization"""
    organization_id: str
    registries_created: int
    registry_ids: Dict[str, str]
    items_created: int


# ==================== Endpoints ====================

@router.post("/analyze", response_model=CorrelationAnalysisResponse, dependencies=[Depends(require_operator_or_admin)])
async def analyze_and_integrate(
    request: CorrelationAnalysisRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_tenant_db),
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
    
    # Create operational metrics from input (schema: endpoint + payload_snapshot)
    operational_metrics = []
    for key, value in request.metrics.items():
        payload = value if isinstance(value, dict) else {"value": value}
        payload = {**payload, "metric_name": key}
        ts = value.get("timestamp") if isinstance(value, dict) else None
        metric = OperationalMetric(
            endpoint=f"/correlation/metrics/{key}",
            payload_snapshot=payload,
            timestamp=str(ts) if ts is not None else None,
        )
        operational_metrics.append(metric)
    
    # Create scenario
    scenario = CorrelationScenario(
        scenario_id=f"scenario-{current_user.id}-{int(datetime.now(timezone.utc).timestamp())}",
        active_domains=domain_types,
        ingested_metrics=operational_metrics,
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
    queued = bool(
        request.auto_create_tasks
        or request.auto_create_registry_items
        or request.auto_create_correlations
    )
    if queued:
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
        # The declared shape, empty — the work is queued, which `integration_queued` says.
        integration_result={
            "registry_items": [],
            "kanban_tasks": [],
            "correlations": [],
            "alerts": [],
        },
        integration_queued=queued,
    )


async def process_integration_background(
    analysis_result: Dict[str, Any],
    organization_id: UUID,
    user_id: str,
    create_tasks: bool,
    create_registry_items: bool,
    create_correlations: bool
):
    """Background task for processing integration.

    TENANT-BOUND (FS-742). This ran on `AsyncSessionLocal()`, which binds no
    `app.current_org_id` — and every table it writes is under FORCE ROW LEVEL SECURITY, so
    each INSERT was refused:

        InsufficientPrivilegeError: new row violates row-level security policy
        for table "actionable_registries"

    The route had already returned 200 by then, and the `except` below logged
    `background_integration_failed` and continued — so the caller was told their analysis
    was integrated, no registry item, task or correlation was ever created, and the only
    trace was one log line nobody reads. Absence presented as success, on the path whose
    entire purpose is the side effect. Fifth instance of this exact shape after FS-431's
    four; `tenant_session` exists because of them.

    Found by accident: the response-model fix above turned this route's 500 into a 200, and
    the 200 printed the swallowed RLS error underneath it. The 500 had been hiding it.
    """
    async with tenant_session(organization_id) as db:
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
            # STILL SWALLOWED, and now at `exception` with the traceback: a background task
            # that raises loses its error to the event loop, and this one has no caller to
            # return to. `error` -> `exception` is the difference between "one line saying
            # something failed" and "enough to fix it".
            logger.exception("background_integration_failed", error=str(e))


@router.post("/initialize-registries", response_model=RegistryInitializationResponse, dependencies=[Depends(require_admin)])
async def initialize_registries(
    request: RegistryInitializationRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Initialize registries for all 47 operational domains for the organization.
    
    This creates:
    - 47 actionable registries (one per operational domain)
    - Default registry items for each domain
    - Compliance standard mappings
    """
    # THE TOKEN, and only the token. This was
    #     request.organization_id or current_user.organization_id
    # which PREFERS the client's value and falls back to the authenticated one — so the
    # fallback made it look safe while the primary path let a caller initialise registries
    # for any organisation they named. A fallback to the right answer is not a guard; it is
    # the wrong answer with a safety net nobody reaches.
    organization_id = current_user.organization_id
    
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


@router.post("/test-integration", dependencies=[Depends(require_admin)])
async def test_integration(
    db: AsyncSession = Depends(get_tenant_db),
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
            endpoint="/api/v1/logistics/appointment-adherence",
            payload_snapshot={
                "metric_name": "appointment_adherence",
                "value": 24.03,
                "unit": "%",
                **(sample_metrics if isinstance(sample_metrics, dict) else {}),
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    ]
    
    scenario = CorrelationScenario(
        scenario_id=f"test-{current_user.id}-{int(datetime.now(timezone.utc).timestamp())}",
        active_domains=domain_types,
        ingested_metrics=operational_metrics,
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
from sqlalchemy import func, select
