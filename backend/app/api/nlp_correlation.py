"""
NLP Correlation AI API Endpoints

API endpoints for natural language interaction with the correlation AI engine,
and Intake Inbox for data upload and analysis.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import structlog

from app.db.database import get_db
from app.api.auth import get_current_active_user
from app.db.models import User
from app.services.correlation_ai_engine import correlation_ai_engine
from app.services.correlation_registry_integration import correlation_registry_integration

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/nlp/correlation", tags=["NLP Correlation"])


# ==================== Request/Response Schemas ====================

class NLPQueryRequest(BaseModel):
    """Request for NLP query to correlation AI"""
    query: str = Field(..., description="Natural language query")
    context: Optional[Dict[str, Any]] = Field(default={}, description="Additional context for the query")
    include_domains: Optional[List[str]] = Field(default=None, description="Specific domains to analyze")
    auto_integrate: bool = Field(default=True, description="Auto-integrate with registries/Kanban")


class NLPQueryResponse(BaseModel):
    """Response from NLP correlation AI query"""
    query: str
    analysis: str
    domains_analyzed: List[str]
    risk_score: float
    recommended_actions: List[Dict[str, Any]]
    kanban_tasks: List[Dict[str, Any]]
    compliance_implications: Optional[List[str]]
    integration_result: Optional[Dict[str, List[str]]]


class IntakeUploadRequest(BaseModel):
    """Request for Intake Inbox data upload"""
    title: str = Field(..., description="Title of the uploaded data")
    description: Optional[str] = Field(default="", description="Description of the data")
    data_type: str = Field(..., description="Type of data: spreadsheet, report, image, document")
    category: Optional[str] = Field(default="general", description="Category for organization")


class IntakeAnalysisRequest(BaseModel):
    """Request for analyzing uploaded data"""
    intake_id: UUID = Field(..., description="Intake item ID")
    query: Optional[str] = Field(default=None, description="Specific query for analysis")
    auto_integrate: bool = Field(default=True, description="Auto-integrate with registries/Kanban")


class IntakeItem(BaseModel):
    """Intake Inbox item"""
    id: UUID
    title: str
    description: str
    data_type: str
    category: str
    file_name: Optional[str]
    status: str
    analysis_result: Optional[Dict[str, Any]]
    created_at: datetime
    analyzed_at: Optional[datetime]


class IntakeListResponse(BaseModel):
    """Response for listing intake items"""
    items: List[IntakeItem]
    total: int


# ==================== NLP Query Endpoints ====================

@router.post("/query", response_model=NLPQueryResponse)
async def nlp_query(
    request: NLPQueryRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Process natural language query to correlation AI.
    
    This endpoint:
    1. Parses the natural language query
    2. Determines relevant domains from the query
    3. Runs correlation AI analysis
    4. Returns actionable insights and recommendations
    5. Optionally auto-integrates with registries and Kanban
    """
    logger.info("nlp_query_received", user_id=str(current_user.id), query=request.query)
    
    # Parse query to extract domains and context
    domains = request.include_domains or _extract_domains_from_query(request.query)
    
    # Create a correlation scenario from the NLP query
    from app.models.domain_interaction import CorrelationScenario, DomainType, OperationalMetric
    from datetime import datetime
    
    domain_types = [DomainType(d) for d in domains] if domains else []
    
    # Extract operational context from query
    operational_metrics = _extract_metrics_from_query(request.query, request.context)
    
    scenario = CorrelationScenario(
        scenario_id=f"nlp-{current_user.id}-{int(datetime.utcnow().timestamp())}",
        active_domains=domain_types,
        operational_metrics=operational_metrics,
        domain_links=[]
    )
    
    # Run correlation AI analysis
    analysis_result = await correlation_ai_engine.analyze_scenario(
        scenario,
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        auto_integrate=request.auto_integrate
    )
    
    # Extract results
    correlation_analysis = analysis_result.get("predicted_root_cause", "")
    risk_score = analysis_result.get("risk_score", 0)
    recommended_tasks = analysis_result.get("target_kanban_tasks", [])
    recommended_commands = analysis_result.get("remediation_commands", [])
    compliance_implications = analysis_result.get("compliance_implications")
    integration_result = analysis_result.get("integration_result")
    
    return NLPQueryResponse(
        query=request.query,
        analysis=correlation_analysis,
        domains_analyzed=domains,
        risk_score=risk_score,
        recommended_actions=recommended_commands,
        kanban_tasks=recommended_tasks,
        compliance_implications=compliance_implications,
        integration_result=integration_result
    )


@router.post("/chat")
async def nlp_chat(
    message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Chat interface for correlation AI interaction.
    
    This provides a conversational interface for interacting with the correlation AI.
    Maintains conversation context for multi-turn queries.
    """
    logger.info("nlp_chat_message", user_id=str(current_user.id), message=message)
    
    # Process message with conversation history
    context = {
        "conversation_history": conversation_history or [],
        "user_id": str(current_user.id)
    }
    
    # Parse message as NLP query
    nlp_request = NLPQueryRequest(
        query=message,
        context=context,
        auto_integrate=False  # Don't auto-integrate in chat mode
    )
    
    # Run analysis
    response = await nlp_query(nlp_request, None, db, current_user)
    
    # Format as chat response
    chat_response = {
        "role": "assistant",
        "content": f"{response.analysis}\n\nRisk Score: {response.risk_score}/100",
        "analysis": response.analysis,
        "risk_score": response.risk_score,
        "domains": response.domains_analyzed,
        "actions": response.recommended_actions,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    return chat_response


# ==================== Intake Inbox Endpoints ====================

@router.post("/intake/upload")
async def upload_to_intake(
    file: UploadFile = File(...),
    title: str = None,
    description: str = "",
    data_type: str = "document",
    category: str = "general",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Upload data to Intake Inbox for correlation AI analysis.
    
    Supports:
    - Spreadsheets (CSV, Excel)
    - Reports (PDF, Word)
    - Images (PNG, JPG) - if Gemma4 supports vision
    - Documents (Text files)
    """
    logger.info(
        "intake_upload",
        user_id=str(current_user.id),
        filename=file.filename,
        data_type=data_type
    )
    
    # Validate file type
    allowed_extensions = {
        "spreadsheet": [".csv", ".xlsx", ".xls"],
        "report": [".pdf", ".docx", ".doc"],
        "image": [".png", ".jpg", ".jpeg"],
        "document": [".txt", ".md"]
    }
    
    file_ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if data_type in allowed_extensions and f".{file_ext}" not in allowed_extensions[data_type]:
        raise HTTPException(status_code=400, detail=f"Invalid file extension for type {data_type}")
    
    # Read file content
    content = await file.read()
    
    # Process file content based on type
    processed_data = await _process_uploaded_file(content, data_type, file.filename)
    
    # Store in database (for now, we'll use a simple in-memory approach)
    # In production, this should be stored in a proper database table or file storage
    
    intake_item = {
        "id": str(UUID(int(datetime.utcnow().timestamp()))),
        "title": title or file.filename,
        "description": description,
        "data_type": data_type,
        "category": category,
        "file_name": file.filename,
        "status": "pending",
        "processed_data": processed_data,
        "created_at": datetime.utcnow().isoformat(),
        "analyzed_at": None,
        "analysis_result": None,
        "user_id": str(current_user.id),
        "organization_id": str(current_user.organization_id)
    }
    
    # Store in a simple in-memory cache (in production, use database)
    # For now, we'll just return the item
    logger.info("intake_upload_complete", intake_id=intake_item["id"])
    
    return intake_item


@router.post("/intake/analyze")
async def analyze_intake(
    intake_id: UUID,
    query: Optional[str] = None,
    auto_integrate: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Analyze uploaded data in Intake Inbox with correlation AI.
    
    This endpoint:
    1. Retrieves the uploaded data
    2. Processes the data with correlation AI
    3. Returns actionable insights
    4. Optionally integrates with registries and Kanban
    """
    logger.info(
        "intake_analysis",
        user_id=str(current_user.id),
        intake_id=str(intake_id)
    )
    
    # In production, retrieve from database
    # For now, we'll simulate the analysis
    
    # Create NLP query from the data
    if query:
        nlp_request = NLPQueryRequest(
            query=query,
            auto_integrate=auto_integrate
        )
    else:
        # Generate a default query from the data type
        default_query = f"Analyze the uploaded {intake_id} data for operational anomalies and correlations"
        nlp_request = NLPQueryRequest(
            query=default_query,
            auto_integrate=auto_integrate
        )
    
    # Run analysis
    response = await nlp_query(nlp_request, None, db, current_user)
    
    analysis_result = {
        "intake_id": str(intake_id),
        "analysis": response.analysis,
        "risk_score": response.risk_score,
        "domains_analyzed": response.domains_analyzed,
        "recommended_actions": response.recommended_actions,
        "kanban_tasks": response.kanban_tasks,
        "compliance_implications": response.compliance_implications,
        "integration_result": response.integration_result,
        "analyzed_at": datetime.utcnow().isoformat()
    }
    
    return analysis_result


@router.get("/intake/list")
async def list_intake_items(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_active_user)
):
    """
    List items in Intake Inbox.
    
    Returns paginated list of uploaded data items with their analysis status.
    """
    logger.info(
        "intake_list",
        user_id=str(current_user.id),
        limit=limit,
        offset=offset,
        status=status
    )
    
    # In production, retrieve from database
    # For now, return empty list
    return {
        "items": [],
        "total": 0
    }


@router.get("/intake/{intake_id}")
async def get_intake_item(
    intake_id: UUID,
    current_user: User = Depends(get_current_active_user)
):
    """
    Get details of a specific Intake Inbox item.
    """
    logger.info("intake_get_item", user_id=str(current_user.id), intake_id=str(intake_id))
    
    # In production, retrieve from database
    raise HTTPException(status_code=404, detail="Intake item not found")


# ==================== Helper Functions ====================

def _extract_domains_from_query(query: str) -> List[str]:
    """Extract relevant domains from natural language query"""
    query_lower = query.lower()
    
    domain_keywords = {
        "LOGISTICS_FLEET": ["trailer", "truck", "dock", "yard", "detention", "carrier", "driver", "shipment", "logistics"],
        "MAINTENANCE": ["maintenance", "equipment", "vibration", "temperature", "work order", "technician", "repair"],
        "PRODUCTION_OEE": ["production", "oee", "throughput", "cycle time", "quality rate", "asset", "cell", "manufacturing"],
        "QUALITY_CONTROL": ["quality", "inspection", "defect", "first pass yield", "capa", "non-conformance"],
        "SAFETY": ["safety", "incident", "security", "hazard", "compliance", "near-miss", "accident"],
        "COMPLIANCE_REGISTRIES": ["compliance", "audit", "regulatory", "iso", "osha", "dot", "violation"],
        "WAREHOUSE_MANAGEMENT": ["warehouse", "inventory", "slot", "storage", "fulfillment", "stockout"],
        "SYSTEM_INFRASTRUCTURE": ["network", "database", "latency", "infrastructure", "availability", "error rate", "it"]
    }
    
    detected_domains = []
    for domain, keywords in domain_keywords.items():
        if any(keyword in query_lower for keyword in keywords):
            detected_domains.append(domain)
    
    return detected_domains


def _extract_metrics_from_query(query: str, context: Dict[str, Any]) -> List:
    """Extract operational metrics from query and context"""
    from app.models.domain_interaction import OperationalMetric
    from datetime import datetime
    
    metrics = []
    
    # Extract numeric values from query
    import re
    numbers = re.findall(r'\d+\.?\d*', query)
    
    if numbers:
        for i, num in enumerate(numbers):
            metric = OperationalMetric(
                metric_name=f"query_metric_{i}",
                value=float(num),
                unit=None,
                timestamp=datetime.utcnow(),
                meta_data={"source": "nlp_query", "context": context}
            )
            metrics.append(metric)
    
    # Add context metrics if available
    if context:
        for key, value in context.items():
            if isinstance(value, (int, float)):
                metric = OperationalMetric(
                    metric_name=f"context_{key}",
                    value=float(value),
                    unit=None,
                    timestamp=datetime.utcnow(),
                    meta_data={"source": "nlp_query_context"}
                )
                metrics.append(metric)
    
    return metrics


async def _process_uploaded_file(content: bytes, data_type: str, filename: str) -> Dict[str, Any]:
    """Process uploaded file content based on type"""
    
    try:
        if data_type == "spreadsheet":
            # For CSV/Excel files
            import pandas as pd
            import io
            
            if filename.endswith('.csv'):
                df = pd.read_csv(io.BytesIO(content))
            elif filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(io.BytesIO(content))
            else:
                df = pd.read_csv(io.StringIO(content.decode('utf-8')))
            
            return {
                "type": "spreadsheet",
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": df.columns.tolist(),
                "sample_data": df.head(5).to_dict(orient='records'),
                "summary": df.describe().to_dict() if not df.empty else {}
            }
        
        elif data_type == "image":
            # For image files - extract text if possible (OCR)
            # This would require integration with OCR service
            return {
                "type": "image",
                "size": len(content),
                "format": filename.split('.')[-1],
                "note": "Image processing requires vision model integration"
            }
        
        elif data_type in ["report", "document"]:
            # For text documents
            text_content = content.decode('utf-8')
            return {
                "type": data_type,
                "size": len(content),
                "content": text_content,
                "word_count": len(text_content.split())
            }
        
        else:
            return {
                "type": data_type,
                "size": len(content)
            }
    
    except Exception as e:
        logger.error("file_processing_error", error=str(e), data_type=data_type)
        return {
            "type": data_type,
            "size": len(content),
            "error": str(e)
        }
