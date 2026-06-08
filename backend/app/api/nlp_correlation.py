"""
NLP Correlation AI API Endpoints

API endpoints for natural language interaction with the correlation AI engine,
and Intake Inbox for data upload and analysis.
"""

import json
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
from app.db.models import IntakeItem as IntakeItemModel
from app.services.correlation_ai_engine import correlation_ai_engine
from app.services.correlation_registry_integration import correlation_registry_integration
from sqlalchemy import select, func

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
        ingested_metrics=operational_metrics,
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
    
    # Store in database
    import base64
    file_content_b64 = base64.b64encode(content).decode('utf-8')
    
    intake_item = IntakeItem(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        title=title or file.filename,
        description=description,
        data_type=data_type,
        category=category,
        file_name=file.filename,
        file_content=file_content_b64,
        processed_data=processed_data,
        status="pending"
    )
    
    db.add(intake_item)
    await db.commit()
    await db.refresh(intake_item)
    
    logger.info("intake_upload_complete", intake_id=str(intake_item.id))
    
    return {
        "id": str(intake_item.id),
        "title": intake_item.title,
        "description": intake_item.description,
        "data_type": intake_item.data_type,
        "category": intake_item.category,
        "file_name": intake_item.file_name,
        "status": intake_item.status,
        "created_at": intake_item.created_at.isoformat(),
        "analyzed_at": intake_item.analyzed_at.isoformat() if intake_item.analyzed_at else None
    }


@router.post("/intake/analyze")
async def analyze_intake(
    intake_id: UUID,
    query: Optional[str] = None,
    auto_integrate: bool = True,
    mode: str = "window",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Analyze uploaded data in Intake Inbox with correlation AI.

    For spreadsheets/workbooks this:
    1. Retrieves the uploaded item and decodes the stored file
    2. Parses ALL tabs into DataFrames
    3. Builds cross-tab-linked CorrelationScenarios (mode: window|tab|row)
    4. Runs the correlation AI engine over every scenario (full coverage)
    5. Aggregates per-domain findings and cross-tab correlations
    6. Persists the combined analysis on the intake item
    """
    logger.info(
        "intake_analysis",
        user_id=str(current_user.id),
        intake_id=str(intake_id),
        mode=mode,
    )

    # Retrieve the intake item
    result = await db.execute(
        select(IntakeItemModel).where(
            IntakeItemModel.id == intake_id,
            IntakeItemModel.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Intake item not found")

    # Spreadsheet/workbook path: build scenarios from the actual tabs
    if item.data_type == "spreadsheet" and item.file_content:
        try:
            analysis_result = await _analyze_spreadsheet_item(
                item, query, auto_integrate, mode, db, current_user
            )
        except Exception as e:
            logger.error("intake_spreadsheet_analysis_failed", error=str(e), intake_id=str(intake_id))
            item.status = "error"
            item.analysis_result = {"error": str(e)}
            await db.commit()
            raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")
    else:
        # Non-spreadsheet: fall back to NLP query over a default/explicit prompt
        default_query = query or (
            f"Analyze the uploaded {item.data_type} '{item.title}' for operational "
            f"anomalies and correlations"
        )
        nlp_request = NLPQueryRequest(query=default_query, auto_integrate=auto_integrate)
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
        }

    # Persist results on the intake item
    item.analysis_result = analysis_result
    item.status = "analyzed"
    item.analyzed_at = datetime.utcnow()
    await db.commit()

    analysis_result["analyzed_at"] = item.analyzed_at.isoformat()
    return analysis_result


async def _analyze_spreadsheet_item(
    item: "IntakeItemModel",
    query: Optional[str],
    auto_integrate: bool,
    mode: str,
    db: AsyncSession,
    current_user: User,
) -> Dict[str, Any]:
    """Parse all tabs of a stored workbook and run correlation analysis per scenario."""
    import base64
    import io
    import pandas as pd
    from app.services.spreadsheet_scenario_builder import build_scenarios
    from app.services.spreadsheet_domain_mapper import map_workbook_domains

    # Decode the stored file
    content = base64.b64decode(item.file_content)
    filename = item.file_name or "upload.xlsx"

    if filename.endswith(".csv"):
        tabs = {"Sheet1": pd.read_csv(io.BytesIO(content))}
    elif filename.endswith((".xlsx", ".xls")):
        tabs = pd.read_excel(io.BytesIO(content), sheet_name=None)
    else:
        tabs = {"Sheet1": pd.read_csv(io.StringIO(content.decode("utf-8")))}

    # Domain mapping summary for transparency
    tab_columns = {name: [str(c) for c in df.columns] for name, df in tabs.items()}
    mapping = map_workbook_domains(tab_columns)

    # Build and analyze scenarios (full coverage)
    source_id = f"intake-{item.id}"
    domains_seen: List[str] = []
    risk_scores: List[float] = []
    kanban_tasks: List[Dict[str, Any]] = []
    commands: List[Dict[str, Any]] = []
    compliance: List[str] = []
    cross_tab_links = 0
    scenario_count = 0
    per_scenario: List[Dict[str, Any]] = []

    for scenario in build_scenarios(tabs, mode=mode, source_id=source_id):
        scenario_count += 1
        if len(scenario.active_domains) >= 2:
            cross_tab_links += len(scenario.domain_links)
        analysis = await correlation_ai_engine.analyze_scenario(
            scenario,
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            # Avoid creating hundreds of registry items; integrate only the summary later
            auto_integrate=False,
        )
        for d in scenario.active_domains:
            if d.value not in domains_seen:
                domains_seen.append(d.value)
        risk_scores.append(analysis.get("risk_score", 0.0))
        for t in (analysis.get("target_kanban_tasks") or []):
            if t not in kanban_tasks:
                kanban_tasks.append(t)
        for c in (analysis.get("remediation_commands") or []):
            if c not in commands:
                commands.append(c)
        for ci in (analysis.get("compliance_implications") or []):
            if ci not in compliance:
                compliance.append(ci)
        # Keep a bounded sample of per-scenario detail
        if len(per_scenario) < 100:
            per_scenario.append({
                "scenario_id": scenario.scenario_id,
                "domains": [d.value for d in scenario.active_domains],
                "risk_score": analysis.get("risk_score"),
                "root_cause": analysis.get("predicted_root_cause"),
            })

    overall_risk = round(max(risk_scores), 1) if risk_scores else 0.0
    summary_text = (
        f"Analyzed {scenario_count} cross-tab scenarios across "
        f"{len(domains_seen)} domains ({', '.join(domains_seen) or 'none'}). "
        f"{cross_tab_links} cross-domain links detected. "
        f"Peak risk score {overall_risk}/100."
    )

    return {
        "intake_id": str(item.id),
        "analysis": summary_text,
        "mode": mode,
        "tab_count": len(tabs),
        "tab_domain_mapping": mapping.to_dict(),
        "scenarios_analyzed": scenario_count,
        "cross_domain_links": cross_tab_links,
        "domains_analyzed": domains_seen,
        "risk_score": overall_risk,
        "recommended_actions": commands[:20],
        "kanban_tasks": kanban_tasks[:20],
        "compliance_implications": compliance or None,
        "scenario_samples": per_scenario,
    }


@router.get("/intake/list")
async def list_intake_items(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
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
    
    # Build query
    query = select(IntakeItemModel).where(IntakeItemModel.user_id == current_user.id)
    
    if status:
        query = query.where(IntakeItemModel.status == status)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Get items
    query = query.order_by(IntakeItemModel.created_at.desc())
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(item.id),
                "title": item.title,
                "description": item.description,
                "data_type": item.data_type,
                "category": item.category,
                "file_name": item.file_name,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
                "analyzed_at": item.analyzed_at.isoformat() if item.analyzed_at else None
            }
            for item in items
        ],
        "total": total
    }


@router.get("/intake/{intake_id}")
async def get_intake_item(
    intake_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get details of a specific Intake Inbox item.
    """
    logger.info("intake_get_item", user_id=str(current_user.id), intake_id=str(intake_id))
    
    # Retrieve from database
    from sqlalchemy import select
    query = select(IntakeItem).where(
        IntakeItem.id == intake_id,
        IntakeItem.user_id == current_user.id
    )
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Intake item not found")
    
    return {
        "id": str(item.id),
        "title": item.title,
        "description": item.description,
        "data_type": item.data_type,
        "category": item.category,
        "file_name": item.file_name,
        "status": item.status,
        "processed_data": item.processed_data,
        "analysis_result": item.analysis_result,
        "created_at": item.created_at.isoformat(),
        "analyzed_at": item.analyzed_at.isoformat() if item.analyzed_at else None
    }


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
    """Extract operational metrics from query and context.

    Returns OperationalMetric objects matching the domain_interaction schema
    (endpoint + payload_snapshot + timestamp).
    """
    from app.models.domain_interaction import OperationalMetric
    from datetime import datetime

    metrics = []
    timestamp = datetime.utcnow().isoformat()

    # Extract numeric values from query into a single metric payload
    import re
    numbers = re.findall(r'\d+\.?\d*', query)

    payload: Dict[str, Any] = {"source": "nlp_query"}
    if numbers:
        for i, num in enumerate(numbers):
            payload[f"query_metric_{i}"] = float(num)

    # Add scalar context values
    if context:
        for key, value in context.items():
            if isinstance(value, (int, float)):
                payload[f"context_{key}"] = float(value)

    if len(payload) > 1:  # more than just "source"
        metrics.append(OperationalMetric(
            endpoint="/nlp/query",
            payload_snapshot=payload,
            timestamp=timestamp,
        ))

    return metrics


async def _process_uploaded_file(content: bytes, data_type: str, filename: str) -> Dict[str, Any]:
    """Process uploaded file content based on type"""
    
    try:
        if data_type == "spreadsheet":
            # For CSV/Excel files
            import pandas as pd
            import io

            # Read ALL tabs/sheets. CSV is a single implicit sheet.
            if filename.endswith('.csv'):
                sheets = {"Sheet1": pd.read_csv(io.BytesIO(content))}
            elif filename.endswith(('.xlsx', '.xls')):
                # sheet_name=None returns an ordered dict of {sheet_name: DataFrame}
                sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
            else:
                sheets = {"Sheet1": pd.read_csv(io.StringIO(content.decode('utf-8')))}

            tabs = []
            total_rows = 0
            for sheet_name, df in sheets.items():
                total_rows += len(df)
                try:
                    summary = df.describe(include="all").to_dict() if not df.empty else {}
                    # Ensure JSON-serializable (describe can contain numpy/NaN)
                    summary = json.loads(pd.DataFrame(summary).to_json())
                except Exception:
                    summary = {}
                tabs.append({
                    "name": str(sheet_name),
                    "rows": len(df),
                    "columns": len(df.columns),
                    "column_names": [str(c) for c in df.columns.tolist()],
                    "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
                    "sample_data": json.loads(df.head(5).to_json(orient="records")),
                    "summary": summary,
                })

            return {
                "type": "spreadsheet",
                "tab_count": len(tabs),
                "rows": total_rows,
                "tab_names": [t["name"] for t in tabs],
                "tabs": tabs,
                # Backward-compatible top-level fields (first tab)
                "columns": tabs[0]["columns"] if tabs else 0,
                "column_names": tabs[0]["column_names"] if tabs else [],
                "sample_data": tabs[0]["sample_data"] if tabs else [],
                "summary": tabs[0]["summary"] if tabs else {},
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
