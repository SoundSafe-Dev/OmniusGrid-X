"""
Analysis Sessions API Endpoints

API endpoints for managing analysis sessions, data sources, and session-based chat.
"""

from typing import List, Dict, Any, Optional, Union
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from pydantic import BaseModel, Field
import structlog

from app.db.database import get_db
from app.api.auth import get_current_active_user
from app.db.models import User, AnalysisSession, SessionDataSource, SessionMessage, IntakeItem
from app.api.nlp_correlation import _process_uploaded_file
from app.services.correlation_ai_engine import correlation_ai_engine

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/nlp/sessions", tags=["Analysis Sessions"])

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


def _user_id_str(user: User) -> str:
    return str(user.id).strip().lower()


def _is_dev_user(user: User) -> bool:
    return _user_id_str(user) == DEV_USER_ID.lower()


def _session_id_str(session_id: Union[UUID, str]) -> str:
    return str(session_id).strip().lower()


async def _get_analysis_session(
    db: AsyncSession,
    session_id: Union[UUID, str],
    current_user: User,
) -> AnalysisSession:
    """Resolve a session for the current user (dev user can access any session)."""
    sid = _session_id_str(session_id)
    uid = _user_id_str(current_user)

    if _is_dev_user(current_user):
        query = select(AnalysisSession).where(AnalysisSession.id == sid)
    else:
        query = select(AnalysisSession).where(
            and_(AnalysisSession.id == sid, AnalysisSession.user_id == uid)
        )

    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if session is None:
        result = await db.execute(
            select(AnalysisSession).where(func.lower(AnalysisSession.id) == sid)
        )
        session = result.scalar_one_or_none()
        if session is not None and not _is_dev_user(current_user):
            if str(session.user_id).strip().lower() != uid:
                session = None

    if session is None:
        logger.warning(
            "analysis_session_not_found",
            session_id=sid,
            user_id=uid,
            dev_mode=_is_dev_user(current_user),
        )
        raise HTTPException(status_code=404, detail="Session not found")

    return session


def _is_lightweight_chat(message: str) -> bool:
    normalized = message.strip().lower()
    if not normalized:
        return True

    greetings = {
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "good morning",
        "good afternoon",
        "good evening",
    }
    if normalized in greetings:
        return True

    analysis_keywords = (
        "analyze",
        "analyse",
        "summarize",
        "summarise",
        "spreadsheet",
        "excel",
        "csv",
        "file",
        "columns",
        "rows",
        "risk",
        "risks",
        "root cause",
        "correlation",
        "recommend",
        "actions",
        "operational",
        "operations",
        "maintenance",
        "compliance",
        "inventory",
        "logistics",
        "production",
        "oee",
        "quality",
        "delay",
        "delays",
        "trend",
        "patterns",
    )
    if any(keyword in normalized for keyword in analysis_keywords):
        return False

    lightweight_prefixes = (
        "thanks",
        "thank you",
        "who are you",
        "what can you do",
        "what do you",
        "what are you",
        "what should i ask",
        "help",
        "how does this work",
        "explain yourself",
    )
    lightweight_phrases = (
        "help with",
        "really help",
        "can you help",
        "are you able",
        "what kind of assistant",
    )
    return normalized.startswith(lightweight_prefixes) or any(
        phrase in normalized for phrase in lightweight_phrases
    )


def _build_lightweight_chat_response(message: str, data_source_count: int) -> str:
    normalized = message.strip().lower()

    if normalized in {"hi", "hello", "hey", "yo", "sup", "good morning", "good afternoon", "good evening"}:
        if data_source_count:
            return (
                "Hi. I can help you inspect the uploaded file, explain what columns mean, "
                "spot patterns, summarize risks, or turn findings into next actions. "
                "Ask something like: \"summarize this file\" or \"what should I pay attention to here?\""
            )
        return (
            "Hi. I can help with operations questions, uploaded Excel/CSV files, risk summaries, "
            "root-cause analysis, and recommended next actions. Upload a file or ask a question to get started."
        )

    if normalized.startswith(("who are you", "what can you do", "what do you", "what are you", "help", "how does this work")) or "help with" in normalized or "really help" in normalized:
        return (
            "I can chat normally and also help with operations analysis. In this page, I'm best at "
            "looking at uploaded Excel/CSV files, explaining what the data seems to show, spotting possible "
            "risks or patterns, and turning findings into next actions. If the file is filler data, I can still "
            "summarize its columns and structure, but I won't pretend it proves a real operational issue."
        )

    return "You're welcome. What would you like to analyze or talk through next?"


# ==================== Request/Response Schemas ====================

class CreateSessionRequest(BaseModel):
    """Request for creating a new analysis session"""
    title: Optional[str] = Field(None, description="Session title (auto-generated if not provided)")
    description: Optional[str] = Field(None, description="Session description")


class UpdateSessionRequest(BaseModel):
    """Request for updating an analysis session"""
    title: Optional[str] = Field(None, description="Session title")
    description: Optional[str] = Field(None, description="Session description")


class SessionResponse(BaseModel):
    """Response for analysis session"""
    id: UUID
    user_id: UUID
    organization_id: UUID
    title: str
    description: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime
    context_snapshot: Dict[str, Any]
    goals_snapshot: Dict[str, Any]
    data_sources_count: int
    messages_count: int


class SessionListResponse(BaseModel):
    """Response for listing sessions"""
    sessions: List[SessionResponse]
    total: int


class AddDataSourceRequest(BaseModel):
    """Request for adding a data source to a session"""
    source_type: str = Field(..., description="intake, upload, system")
    source_id: Optional[UUID] = Field(None, description="ID from source table")
    data_type: Optional[str] = Field(None, description="spreadsheet, report, image, document")


class DataSourceResponse(BaseModel):
    """Response for data source"""
    id: UUID
    session_id: UUID
    source_type: str
    source_id: Optional[UUID]
    file_name: Optional[str]
    data_type: Optional[str]
    added_at: datetime


class SessionChatRequest(BaseModel):
    """Request for session-based chat"""
    message: str = Field(..., description="User message")
    auto_integrate: bool = Field(default=False, description="Auto-integrate with Kanban")


class SessionChatResponse(BaseModel):
    """Response for session-based chat"""
    role: str
    content: str
    analysis: Optional[Dict[str, Any]]
    risk_score: Optional[float]
    domains: Optional[List[str]]
    actions: Optional[List[Dict[str, Any]]]
    timestamp: datetime


class SessionMessageResponse(BaseModel):
    """Response for session message"""
    id: UUID
    session_id: UUID
    role: str
    content: str
    analysis: Optional[Dict[str, Any]]
    risk_score: Optional[float]
    domains: Optional[List[str]]
    actions: Optional[List[Dict[str, Any]]]
    timestamp: datetime


# ==================== Session Management Endpoints ====================

@router.post("", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a new analysis session.
    
    If title is not provided, it will be auto-generated based on the first query.
    """
    logger.info("create_session", user_id=str(current_user.id))
    
    # Generate default title if not provided
    title = request.title or f"Analysis Session {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    
    # Create session
    session = AnalysisSession(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        title=title,
        description=request.description,
        status="active",
        context_snapshot={},  # Will be populated with user context
        goals_snapshot={}  # Will be populated with user goals
    )
    
    db.add(session)
    await db.commit()
    await db.refresh(session)
    
    # Ensure session is persisted by querying it back
    verify_query = select(AnalysisSession).where(AnalysisSession.id == session.id)
    verify_result = await db.execute(verify_query)
    verified_session = verify_result.scalar_one_or_none()
    if not verified_session:
        raise HTTPException(status_code=500, detail="Failed to persist session")
    session = verified_session
    
    # Get counts
    data_sources_count = 0
    messages_count = 0
    
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        organization_id=session.organization_id,
        title=session.title,
        description=session.description,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_accessed_at=session.last_accessed_at,
        context_snapshot=session.context_snapshot,
        goals_snapshot=session.goals_snapshot,
        data_sources_count=data_sources_count,
        messages_count=messages_count
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    List user's analysis sessions.
    """
    logger.info("list_sessions", user_id=str(current_user.id), status=status)
    
    # Build query (dev user sees all sessions for demo stability)
    if _is_dev_user(current_user):
        query = select(AnalysisSession)
    else:
        query = select(AnalysisSession).where(
            AnalysisSession.user_id == _user_id_str(current_user)
        )
    
    if status:
        query = query.where(AnalysisSession.status == status)
    
    query = query.order_by(AnalysisSession.last_accessed_at.desc())
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    sessions = result.scalars().all()
    
    logger.info("list_sessions_result", count=len(sessions), session_ids=[str(s.id) for s in sessions])
    
    # Get total count
    if _is_dev_user(current_user):
        count_query = select(func.count()).select_from(AnalysisSession)
    else:
        count_query = select(func.count()).select_from(AnalysisSession).where(
            AnalysisSession.user_id == _user_id_str(current_user)
        )
    if status:
        count_query = count_query.where(AnalysisSession.status == status)
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Build response with counts
    session_responses = []
    for session in sessions:
        # Get data sources count
        ds_query = select(SessionDataSource).where(SessionDataSource.session_id == str(session.id))
        ds_result = await db.execute(ds_query)
        data_sources_count = len(ds_result.scalars().all())
        
        # Get messages count
        msg_query = select(SessionMessage).where(SessionMessage.session_id == str(session.id))
        msg_result = await db.execute(msg_query)
        messages_count = len(msg_result.scalars().all())
        
        session_responses.append(SessionResponse(
            id=session.id,
            user_id=session.user_id,
            organization_id=session.organization_id,
            title=session.title,
            description=session.description,
            status=session.status,
            created_at=session.created_at,
            updated_at=session.updated_at,
            last_accessed_at=session.last_accessed_at,
            context_snapshot=session.context_snapshot,
            goals_snapshot=session.goals_snapshot,
            data_sources_count=data_sources_count,
            messages_count=messages_count
        ))
    
    return SessionListResponse(
        sessions=session_responses,
        total=total
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get details of a specific analysis session.
    """
    logger.info("get_session", user_id=str(current_user.id), session_id=str(session_id))
    
    session_id_str = _session_id_str(session_id)
    session = await _get_analysis_session(db, session_id, current_user)
    
    # Update last accessed
    session.last_accessed_at = datetime.utcnow()
    await db.commit()
    
    # Get counts
    ds_query = select(SessionDataSource).where(SessionDataSource.session_id == str(session.id))
    ds_result = await db.execute(ds_query)
    data_sources_count = len(ds_result.scalars().all())
    
    msg_query = select(SessionMessage).where(SessionMessage.session_id == session.id)
    msg_result = await db.execute(msg_query)
    messages_count = len(msg_result.scalars().all())
    
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        organization_id=session.organization_id,
        title=session.title,
        description=session.description,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_accessed_at=session.last_accessed_at,
        context_snapshot=session.context_snapshot,
        goals_snapshot=session.goals_snapshot,
        data_sources_count=data_sources_count,
        messages_count=messages_count
    )


@router.put("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: UUID,
    request: UpdateSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update an analysis session (title, description).
    """
    logger.info("update_session", user_id=str(current_user.id), session_id=str(session_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    
    # Get session
    query = select(AnalysisSession).where(
        and_(
            AnalysisSession.id == session_id_str,
            AnalysisSession.user_id == current_user.id
        )
    )
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update fields
    if request.title is not None:
        session.title = request.title
    if request.description is not None:
        session.description = request.description
    
    session.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(session)
    
    # Get counts
    ds_query = select(SessionDataSource).where(SessionDataSource.session_id == str(session.id))
    ds_result = await db.execute(ds_query)
    data_sources_count = len(ds_result.scalars().all())
    
    msg_query = select(SessionMessage).where(SessionMessage.session_id == session.id)
    msg_result = await db.execute(msg_query)
    messages_count = len(msg_result.scalars().all())
    
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        organization_id=session.organization_id,
        title=session.title,
        description=session.description,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_accessed_at=session.last_accessed_at,
        context_snapshot=session.context_snapshot,
        goals_snapshot=session.goals_snapshot,
        data_sources_count=data_sources_count,
        messages_count=messages_count
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete an analysis session (soft delete).
    """
    logger.info("delete_session", user_id=str(current_user.id), session_id=str(session_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    
    # Get session - in dev mode, allow deletion regardless of user_id
    if current_user.id == "00000000-0000-0000-0000-000000000001":
        # Dev mode: get session without user_id check
        query = select(AnalysisSession).where(AnalysisSession.id == session_id_str)
    else:
        # Normal mode: check ownership
        query = select(AnalysisSession).where(
            and_(
                AnalysisSession.id == session_id_str,
                AnalysisSession.user_id == current_user.id
            )
        )
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Soft delete
    session.status = "deleted"
    session.updated_at = datetime.utcnow()
    
    await db.commit()


@router.post("/cleanup-orphaned")
async def cleanup_orphaned_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Clean up orphaned sessions that exist in database but are inconsistent.
    This is a dev/debug endpoint to fix database corruption.
    """
    logger.info("cleanup_orphaned_sessions", user_id=str(current_user.id))
    
    # Only allow in dev mode
    if current_user.id != "00000000-0000-0000-0000-000000000001":
        raise HTTPException(status_code=403, detail="Cleanup only available in dev mode")
    
    # Hard delete all sessions for user to clear corruption
    from sqlalchemy import delete
    delete_stmt = delete(AnalysisSession).where(AnalysisSession.user_id == current_user.id)
    result = await db.execute(delete_stmt)
    deleted_count = result.rowcount
    await db.commit()
    
    logger.info("cleanup_orphaned_sessions_complete", deleted_count=deleted_count)
    
    return {
        "message": f"Deleted {deleted_count} sessions to clear database corruption",
        "deleted_count": deleted_count
    }


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def resume_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Resume an analysis session.
    """
    logger.info("resume_session", user_id=str(current_user.id), session_id=str(session_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    
    # Get session
    query = select(AnalysisSession).where(
        and_(
            AnalysisSession.id == session_id_str,
            AnalysisSession.user_id == current_user.id
        )
    )
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update last accessed
    session.last_accessed_at = datetime.utcnow()
    session.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(session)
    
    # Get counts
    ds_query = select(SessionDataSource).where(SessionDataSource.session_id == str(session.id))
    ds_result = await db.execute(ds_query)
    data_sources_count = len(ds_result.scalars().all())
    
    msg_query = select(SessionMessage).where(SessionMessage.session_id == session.id)
    msg_result = await db.execute(msg_query)
    messages_count = len(msg_result.scalars().all())
    
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        organization_id=session.organization_id,
        title=session.title,
        description=session.description,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_accessed_at=session.last_accessed_at,
        context_snapshot=session.context_snapshot,
        goals_snapshot=session.goals_snapshot,
        data_sources_count=data_sources_count,
        messages_count=messages_count
    )


# ==================== Data Source Management Endpoints ====================

@router.post("/{session_id}/data/intake", response_model=DataSourceResponse)
async def add_intake_data(
    session_id: UUID,
    intake_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Add data from Intake Inbox to session.
    """
    logger.info("add_intake_data", user_id=str(current_user.id), session_id=str(session_id), intake_id=str(intake_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    
    # Verify session ownership
    session_query = select(AnalysisSession).where(
        and_(
            AnalysisSession.id == session_id_str,
            AnalysisSession.user_id == current_user.id
        )
    )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Fetch intake item from database
    intake_query = select(IntakeItem).where(
        and_(
            IntakeItem.id == intake_id,
            IntakeItem.user_id == current_user.id
        )
    )
    intake_result = await db.execute(intake_query)
    intake_item = intake_result.scalar_one_or_none()
    
    if not intake_item:
        raise HTTPException(status_code=404, detail="Intake item not found")
    
    # Create data source from intake item
    data_source = SessionDataSource(
        session_id=session_id_str,
        source_type="intake",
        source_id=intake_id,
        file_name=intake_item.file_name,
        data_type=intake_item.data_type,
        processed_data=intake_item.processed_data
    )
    
    db.add(data_source)
    await db.commit()
    await db.refresh(data_source)
    
    return DataSourceResponse(
        id=data_source.id,
        session_id=data_source.session_id,
        source_type=data_source.source_type,
        source_id=data_source.source_id,
        file_name=data_source.file_name,
        data_type=data_source.data_type,
        added_at=data_source.added_at
    )


@router.post("/{session_id}/data/upload", response_model=DataSourceResponse)
async def upload_data_to_session(
    session_id: UUID,
    file: UploadFile = File(...),
    data_type: str = "document",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Upload new data to session.
    """
    logger.info("upload_data_to_session", user_id=str(current_user.id), session_id=str(session_id), filename=file.filename)
    
    session_id_str = _session_id_str(session_id)
    await _get_analysis_session(db, session_id, current_user)
    
    # Read file content
    content = await file.read()
    filename = file.filename or "upload"

    # Auto-detect spreadsheets so direct session uploads match Intake parsing.
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext in ("csv", "xlsx", "xls"):
        data_type = "spreadsheet"

    processed_data = await _process_uploaded_file(content, data_type, filename)
    processed_data["size"] = len(content)
    processed_data["filename"] = filename

    if processed_data.get("error"):
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse spreadsheet: {processed_data['error']}",
        )
    
    # Create data source
    data_source = SessionDataSource(
        session_id=session_id_str,
        source_type="upload",
        source_id=None,
        file_name=filename,
        data_type=data_type,
        processed_data=processed_data
    )
    
    db.add(data_source)
    await db.commit()
    await db.refresh(data_source)
    
    return DataSourceResponse(
        id=data_source.id,
        session_id=data_source.session_id,
        source_type=data_source.source_type,
        source_id=data_source.source_id,
        file_name=data_source.file_name,
        data_type=data_source.data_type,
        added_at=data_source.added_at
    )


@router.get("/{session_id}/data", response_model=List[DataSourceResponse])
async def list_session_data(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    List data sources in a session.
    """
    logger.info("list_session_data", user_id=str(current_user.id), session_id=str(session_id))
    
    session_id_str = _session_id_str(session_id)
    await _get_analysis_session(db, session_id, current_user)
    
    # Get data sources
    query = select(SessionDataSource).where(SessionDataSource.session_id == session_id_str)
    query = query.order_by(SessionDataSource.added_at.asc())
    result = await db.execute(query)
    data_sources = result.scalars().all()
    
    return [
        DataSourceResponse(
            id=ds.id,
            session_id=ds.session_id,
            source_type=ds.source_type,
            source_id=ds.source_id,
            file_name=ds.file_name,
            data_type=ds.data_type,
            added_at=ds.added_at
        )
        for ds in data_sources
    ]


@router.delete("/{session_id}/data/{source_id}")
async def remove_data_source(
    session_id: UUID,
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Remove a data source from session.
    """
    logger.info("remove_data_source", user_id=str(current_user.id), session_id=str(session_id), source_id=str(source_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    source_id_str = str(source_id)
    
    # Verify session ownership
    session_query = select(AnalysisSession).where(
        and_(
            AnalysisSession.id == session_id_str,
            AnalysisSession.user_id == current_user.id
        )
    )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get and delete data source
    query = select(SessionDataSource).where(
        and_(
            SessionDataSource.id == source_id_str,
            SessionDataSource.session_id == session_id_str
        )
    )
    result = await db.execute(query)
    data_source = result.scalar_one_or_none()
    
    if not data_source:
        raise HTTPException(status_code=404, detail="Data source not found")
    
    await db.delete(data_source)
    await db.commit()
    
    return {"message": "Data source removed successfully"}


# ==================== Session Chat Endpoints ====================

@router.post("/{session_id}/chat", response_model=SessionChatResponse)
async def session_chat(
    session_id: UUID,
    request: SessionChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Send message in session context.
    """
    logger.info("session_chat", user_id=str(current_user.id), session_id=str(session_id))
    
    session_id_str = _session_id_str(session_id)
    session = await _get_analysis_session(db, session_id, current_user)
    
    # Update session last accessed
    session.last_accessed_at = datetime.utcnow()
    
    # Save user message
    user_message = SessionMessage(
        session_id=session_id_str,
        role="user",
        content=request.message,
        timestamp=datetime.utcnow(),
        context_used={"session_id": str(session_id)}
    )
    db.add(user_message)
    
    # Get session data sources
    ds_query = select(SessionDataSource).where(SessionDataSource.session_id == session_id_str)
    ds_result = await db.execute(ds_query)
    data_sources = ds_result.scalars().all()

    # Get previous session messages for context
    msg_query = select(SessionMessage).where(SessionMessage.session_id == session_id_str)
    msg_query = msg_query.order_by(SessionMessage.timestamp.desc())
    msg_query = msg_query.limit(10)
    msg_result = await db.execute(msg_query)
    previous_messages = msg_result.scalars().all()
    
    # Build context for correlation AI
    context = {
        "session_id": str(session_id),
        "data_sources": [
            {
                "source_type": ds.source_type,
                "file_name": ds.file_name,
                "data_type": ds.data_type,
                "processed_data": ds.processed_data
            }
            for ds in data_sources
        ],
        "conversation_history": [
            {"role": msg.role, "content": msg.content}
            for msg in reversed(previous_messages)
        ],
        "user_context": session.context_snapshot,
        "user_goals": session.goals_snapshot
    }
    
    # Let the model handle the conversation naturally. It can still use uploaded
    # data context, but it does not force every response into risk/task format.
    try:
        analysis_result = await correlation_ai_engine.chat(request.message, context=context)
        ai_content = analysis_result.get("response_text") or analysis_result.get("predicted_root_cause", "")

        assistant_message = SessionMessage(
            session_id=session_id_str,
            role="assistant",
            content=ai_content,
            analysis=analysis_result,
            risk_score=analysis_result.get("risk_score"),
            domains=[],
            actions=analysis_result.get("remediation_commands", []),
            timestamp=datetime.utcnow(),
            context_used=context
        )
        db.add(assistant_message)

        await db.commit()
        await db.refresh(assistant_message)

        return SessionChatResponse(
            role=assistant_message.role,
            content=assistant_message.content,
            analysis=assistant_message.analysis,
            risk_score=assistant_message.risk_score,
            domains=assistant_message.domains,
            actions=assistant_message.actions,
            timestamp=assistant_message.timestamp
        )
    except Exception as e:
        logger.exception("correlation_chat_error", error=str(e))

    # Legacy structured analysis fallback for non-chat deployments.
    try:
        from app.api.nlp_correlation import _extract_domains_from_query
        from app.models.domain_interaction import CorrelationScenario, DomainType
        
        # Extract domains from query
        domains = _extract_domains_from_query(request.message)
        if not domains and data_sources:
            domains = ["DATA_ANALYTICS"]
        domain_types = [DomainType(d) for d in domains] if domains else []
        
        context["user_question"] = request.message
        
        # Create correlation scenario
        scenario = CorrelationScenario(
            scenario_id=f"session-{session_id}-{int(datetime.utcnow().timestamp())}",
            active_domains=domain_types,
            ingested_metrics=[],
            domain_links=[]
        )
        
        # Run correlation AI analysis
        analysis_result = await correlation_ai_engine.analyze_scenario(
            scenario,
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            auto_integrate=request.auto_integrate,
            context=context
        )
        
        # Extract results
        correlation_analysis = analysis_result.get("predicted_root_cause", "")
        risk_score = analysis_result.get("risk_score", 0)
        recommended_tasks = analysis_result.get("target_kanban_tasks", [])
        recommended_commands = analysis_result.get("remediation_commands", [])
        compliance_implications = analysis_result.get("compliance_implications")
        
        # Format AI response
        ai_content = analysis_result.get("response_text") or correlation_analysis
        if recommended_commands and not analysis_result.get("response_text"):
            ai_content += "\n\nRecommended Actions:\n" + "\n".join([
                f"- {cmd.get('description', cmd.get('command', str(cmd)))}"
                for cmd in recommended_commands
            ])
        
        # Extract domains from analysis
        domains_analyzed = domains
        
        # Save assistant message
        assistant_message = SessionMessage(
            session_id=session_id_str,
            role="assistant",
            content=ai_content,
            analysis=analysis_result,
            risk_score=risk_score,
            domains=domains_analyzed,
            actions=recommended_commands,
            timestamp=datetime.utcnow(),
            context_used=context
        )
        db.add(assistant_message)
        
        await db.commit()
        await db.refresh(assistant_message)
        
        return SessionChatResponse(
            role=assistant_message.role,
            content=assistant_message.content,
            analysis=assistant_message.analysis,
            risk_score=assistant_message.risk_score,
            domains=assistant_message.domains,
            actions=assistant_message.actions,
            timestamp=assistant_message.timestamp
        )
        
    except Exception as e:
        logger.exception("correlation_ai_error", error=str(e))
        
        # Fallback response if AI integration fails
        assistant_message = SessionMessage(
            session_id=session_id_str,
            role="assistant",
            content=f"I received your query: {request.message}\n\nI'm processing this with the context of {len(data_sources)} data sources. The correlation AI integration is being set up.",
            analysis={},
            risk_score=None,
            domains=[],
            actions=[],
            timestamp=datetime.utcnow(),
            context_used=context
        )
        db.add(assistant_message)
        
        await db.commit()
        await db.refresh(assistant_message)
        
        return SessionChatResponse(
            role=assistant_message.role,
            content=assistant_message.content,
            analysis=assistant_message.analysis,
            risk_score=assistant_message.risk_score,
            domains=assistant_message.domains,
            actions=assistant_message.actions,
            timestamp=assistant_message.timestamp
        )


@router.get("/{session_id}/messages", response_model=List[SessionMessageResponse])
async def get_session_messages(
    session_id: UUID,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get messages in a session.
    """
    logger.info("get_session_messages", user_id=str(current_user.id), session_id=str(session_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    
    # Verify session ownership - in dev mode, allow access regardless of user_id
    if current_user.id == "00000000-0000-0000-0000-000000000001":
        # Dev mode: get session without user_id check
        session_query = select(AnalysisSession).where(AnalysisSession.id == session_id_str)
    else:
        # Normal mode: check ownership
        session_query = select(AnalysisSession).where(
            and_(
                AnalysisSession.id == session_id_str,
                AnalysisSession.user_id == current_user.id
            )
        )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get messages
    query = select(SessionMessage).where(SessionMessage.session_id == session_id_str)
    query = query.order_by(SessionMessage.timestamp.asc())
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    messages = result.scalars().all()
    
    return [
        SessionMessageResponse(
            id=msg.id,
            session_id=msg.session_id,
            role=msg.role,
            content=msg.content,
            analysis=msg.analysis,
            risk_score=msg.risk_score,
            domains=msg.domains,
            actions=msg.actions,
            timestamp=msg.timestamp
        )
        for msg in messages
    ]


# ==================== Auto-Title Generation ====================

@router.post("/{session_id}/generate-title", response_model=SessionResponse)
async def generate_session_title(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Generate session title from context and queries.
    """
    logger.info("generate_session_title", user_id=str(current_user.id), session_id=str(session_id))
    
    # Get session
    query = select(AnalysisSession).where(
        and_(
            AnalysisSession.id == session_id,
            AnalysisSession.user_id == current_user.id
        )
    )
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get session messages to analyze for title generation
    msg_query = select(SessionMessage).where(
        and_(
            SessionMessage.session_id == session_id,
            SessionMessage.role == "user"
        )
    )
    msg_query = msg_query.order_by(SessionMessage.timestamp.asc())
    msg_query = msg_query.limit(5)  # Analyze first 5 user messages
    msg_result = await db.execute(msg_query)
    messages = msg_result.scalars().all()
    
    # Extract keywords and domains from messages
    domains_found = set()
    keywords = []
    
    for msg in messages:
        content_lower = msg.content.lower()
        
        # Extract domains
        domain_keywords = {
            "LOGISTICS_FLEET": ["trailer", "truck", "dock", "yard", "detention", "carrier", "driver", "shipment"],
            "MAINTENANCE": ["maintenance", "equipment", "vibration", "temperature", "repair"],
            "PRODUCTION_OEE": ["production", "oee", "throughput", "cycle time", "manufacturing"],
            "QUALITY_CONTROL": ["quality", "inspection", "defect", "first pass yield"],
            "SAFETY": ["safety", "incident", "hazard", "compliance"],
            "COMPLIANCE": ["compliance", "audit", "regulatory", "iso", "osha"]
        }
        
        for domain, keywords_list in domain_keywords.items():
            if any(keyword in content_lower for keyword in keywords_list):
                domains_found.add(domain)
        
        # Extract key phrases (simple implementation)
        if "production" in content_lower:
            keywords.append("Production")
        if "maintenance" in content_lower:
            keywords.append("Maintenance")
        if "logistics" in content_lower:
            keywords.append("Logistics")
        if "quality" in content_lower:
            keywords.append("Quality")
        if "safety" in content_lower:
            keywords.append("Safety")
    
    # Generate title
    if domains_found:
        primary_domain = list(domains_found)[0].replace("_", " ").title()
        if keywords:
            title = f"{primary_domain} Analysis - {', '.join(keywords[:2])}"
        else:
            title = f"{primary_domain} Analysis"
    elif keywords:
        title = f"{', '.join(keywords[:2])} Analysis"
    else:
        title = f"Analysis Session {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    
    # Update session title
    session.title = title
    session.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(session)
    
    # Get counts
    ds_query = select(SessionDataSource).where(SessionDataSource.session_id == str(session.id))
    ds_result = await db.execute(ds_query)
    data_sources_count = len(ds_result.scalars().all())
    
    msg_count_query = select(SessionMessage).where(SessionMessage.session_id == str(session.id))
    msg_count_result = await db.execute(msg_count_query)
    messages_count = len(msg_count_result.scalars().all())
    
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        organization_id=session.organization_id,
        title=session.title,
        description=session.description,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_accessed_at=session.last_accessed_at,
        context_snapshot=session.context_snapshot,
        goals_snapshot=session.goals_snapshot,
        data_sources_count=data_sources_count,
        messages_count=messages_count
    )


# ==================== Chat History and Search ====================

@router.get("/chat/history", response_model=List[SessionMessageResponse])
async def get_chat_history(
    limit: int = 100,
    offset: int = 0,
    session_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get full chat history across all sessions.
    """
    logger.info("get_chat_history", user_id=str(current_user.id))
    
    # Build query
    query = select(SessionMessage).join(AnalysisSession).where(
        AnalysisSession.user_id == current_user.id
    )
    
    if session_id:
        query = query.where(SessionMessage.session_id == session_id)
    
    query = query.order_by(SessionMessage.timestamp.desc())
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    messages = result.scalars().all()
    
    return [
        SessionMessageResponse(
            id=msg.id,
            session_id=msg.session_id,
            role=msg.role,
            content=msg.content,
            analysis=msg.analysis,
            risk_score=msg.risk_score,
            domains=msg.domains,
            actions=msg.actions,
            timestamp=msg.timestamp
        )
        for msg in messages
    ]


@router.get("/chat/search", response_model=List[SessionMessageResponse])
async def search_chat_history(
    q: str = Query(..., description="Search query"),
    limit: int = 50,
    offset: int = 0,
    session_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Search/filter historical chats.
    """
    logger.info("search_chat_history", user_id=str(current_user.id), query=q)
    
    # Build query with search
    query = select(SessionMessage).join(AnalysisSession).where(
        and_(
            AnalysisSession.user_id == current_user.id,
            SessionMessage.content.ilike(f"%{q}%")
        )
    )
    
    if session_id:
        query = query.where(SessionMessage.session_id == session_id)
    
    query = query.order_by(SessionMessage.timestamp.desc())
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    messages = result.scalars().all()
    
    return [
        SessionMessageResponse(
            id=msg.id,
            session_id=msg.session_id,
            role=msg.role,
            content=msg.content,
            analysis=msg.analysis,
            risk_score=msg.risk_score,
            domains=msg.domains,
            actions=msg.actions,
            timestamp=msg.timestamp
        )
        for msg in messages
    ]


# ==================== Real-Time Data Integration Endpoints ====================

@router.get("/{session_id}/context/telemetry")
async def get_session_telemetry_context(
    session_id: UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Fetch relevant telemetry for session context.
    """
    logger.info("get_session_telemetry_context", user_id=str(current_user.id), session_id=str(session_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    
    # Verify session ownership - in dev mode, allow access regardless of user_id
    if current_user.id == "00000000-0000-0000-0000-000000000001":
        # Dev mode: get session without user_id check
        session_query = select(AnalysisSession).where(AnalysisSession.id == session_id_str)
    else:
        # Normal mode: check ownership
        session_query = select(AnalysisSession).where(
            and_(
                AnalysisSession.id == session_id_str,
                AnalysisSession.user_id == current_user.id
            )
        )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Fetch recent telemetry from organization
    from app.db.models import Telemetry, Asset
    from datetime import datetime, timedelta
    
    # Get assets from organization
    asset_query = select(Asset).where(Asset.organization_id == current_user.organization_id)
    asset_result = await db.execute(asset_query)
    assets = asset_result.scalars().all()
    
    if not assets:
        return {
            "session_id": str(session_id),
            "telemetry": [],
            "message": "No assets found in organization"
        }
    
    # Get recent telemetry (last 1 hour)
    time_threshold = datetime.utcnow() - timedelta(hours=1)
    telemetry_data = []
    
    for asset in assets[:5]:  # Limit to 5 assets for performance
        telemetry_query = select(Telemetry).where(
            and_(
                Telemetry.asset_id == asset.id,
                Telemetry.time >= time_threshold
            )
        ).order_by(Telemetry.time.desc()).limit(limit)
        
        telemetry_result = await db.execute(telemetry_query)
        telemetry_items = telemetry_result.scalars().all()
        
        for item in telemetry_items:
            telemetry_data.append({
                "asset_id": str(item.asset_id),
                "asset_name": asset.name,
                "metric_name": item.metric_name,
                "value": float(item.value),
                "unit": item.unit,
                "timestamp": item.time.isoformat(),
                "packml_state": item.packml_state
            })
    
    return {
        "session_id": str(session_id),
        "telemetry": telemetry_data[:limit],
        "count": len(telemetry_data)
    }


@router.get("/{session_id}/context/alarms")
async def get_session_alarms_context(
    session_id: UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Fetch relevant alarms for session context.
    """
    logger.info("get_session_alarms_context", user_id=str(current_user.id), session_id=str(session_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    
    # Verify session ownership - in dev mode, allow access regardless of user_id
    if current_user.id == "00000000-0000-0000-0000-000000000001":
        # Dev mode: get session without user_id check
        session_query = select(AnalysisSession).where(AnalysisSession.id == session_id_str)
    else:
        # Normal mode: check ownership
        session_query = select(AnalysisSession).where(
            and_(
                AnalysisSession.id == session_id_str,
                AnalysisSession.user_id == current_user.id
            )
        )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Fetch recent alarms from organization
    from app.db.models import Alarm, Asset
    from datetime import datetime, timedelta
    
    # Get assets from organization
    asset_query = select(Asset).where(Asset.organization_id == current_user.organization_id)
    asset_result = await db.execute(asset_query)
    assets = asset_result.scalars().all()
    
    if not assets:
        return {
            "session_id": str(session_id),
            "alarms": [],
            "message": "No assets found in organization"
        }
    
    # Get recent alarms (last 24 hours)
    time_threshold = datetime.utcnow() - timedelta(hours=24)
    alarm_data = []
    
    for asset in assets[:5]:  # Limit to 5 assets for performance
        alarm_query = select(Alarm).where(
            and_(
                Alarm.asset_id == asset.id,
                Alarm.occurred_at >= time_threshold
            )
        ).order_by(Alarm.occurred_at.desc()).limit(limit)
        
        alarm_result = await db.execute(alarm_query)
        alarm_items = alarm_result.scalars().all()
        
        for item in alarm_items:
            alarm_data.append({
                "id": str(item.id),
                "asset_id": str(item.asset_id),
                "asset_name": asset.name,
                "alarm_code": item.alarm_code,
                "severity": item.severity,
                "is_active": item.is_active,
                "is_acknowledged": item.is_acknowledged,
                "occurred_at": item.occurred_at.isoformat(),
                "description": item.description
            })
    
    return {
        "session_id": str(session_id),
        "alarms": alarm_data[:limit],
        "count": len(alarm_data)
    }


@router.get("/{session_id}/context/kanban")
async def get_session_kanban_context(
    session_id: UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Fetch relevant Kanban tasks for session context.
    """
    logger.info("get_session_kanban_context", user_id=str(current_user.id), session_id=str(session_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    
    # Verify session ownership - in dev mode, allow access regardless of user_id
    if current_user.id == "00000000-0000-0000-0000-000000000001":
        # Dev mode: get session without user_id check
        session_query = select(AnalysisSession).where(AnalysisSession.id == session_id_str)
    else:
        # Normal mode: check ownership
        session_query = select(AnalysisSession).where(
            and_(
                AnalysisSession.id == session_id_str,
                AnalysisSession.user_id == current_user.id
            )
        )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Fetch Kanban tasks from organization
    from app.db.models import Task, TaskBoard
    
    # Get the organization's board first
    board_query = select(TaskBoard).where(
        TaskBoard.organization_id == current_user.organization_id
    )
    board_result = await db.execute(board_query)
    board = board_result.scalar_one_or_none()
    
    if not board:
        return {
            "session_id": str(session_id),
            "tasks": [],
            "message": "No kanban board found for organization"
        }
    
    # Get tasks from the board
    task_query = select(Task).where(
        Task.board_id == board.id
    ).order_by(Task.created_at.desc()).limit(limit)
    
    task_result = await db.execute(task_query)
    tasks = task_result.scalars().all()
    
    task_data = []
    for task in tasks:
        task_data.append({
            "id": str(task.id),
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "assigned_to": str(task.assigned_to) if task.assigned_to else None,
            "column_id": str(task.column_id) if task.column_id else None,
            "created_at": task.created_at.isoformat(),
            "progress_percent": task.progress_percent
        })
    
    return {
        "session_id": str(session_id),
        "tasks": task_data,
        "count": len(task_data)
    }


@router.get("/{session_id}/context/registries")
async def get_session_registries_context(
    session_id: UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Fetch relevant registry items for session context.
    """
    logger.info("get_session_registries_context", user_id=str(current_user.id), session_id=str(session_id))
    
    # Convert UUID to string to ensure proper comparison with String column
    session_id_str = str(session_id)
    
    # Verify session ownership - in dev mode, allow access regardless of user_id
    if current_user.id == "00000000-0000-0000-0000-000000000001":
        # Dev mode: get session without user_id check
        session_query = select(AnalysisSession).where(AnalysisSession.id == session_id_str)
    else:
        # Normal mode: check ownership
        session_query = select(AnalysisSession).where(
            and_(
                AnalysisSession.id == session_id_str,
                AnalysisSession.user_id == current_user.id
            )
        )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Fetch registry items from organization
    from app.db.models import ActionableRegistry, ActionableRegistryItem
    
    # Get registries
    registry_query = select(ActionableRegistry).where(
        ActionableRegistry.organization_id == current_user.organization_id
    )
    registry_result = await db.execute(registry_query)
    registries = registry_result.scalars().all()
    
    if not registries:
        return {
            "session_id": str(session_id),
            "registry_items": [],
            "message": "No registries found in organization"
        }
    
    # Get registry items
    registry_ids = [r.id for r in registries]
    items_query = select(ActionableRegistryItem).where(
        ActionableRegistryItem.registry_id.in_(registry_ids)
    ).order_by(ActionableRegistryItem.created_at.desc()).limit(limit)
    
    items_result = await db.execute(items_query)
    items = items_result.scalars().all()
    
    item_data = []
    for item in items:
        item_data.append({
            "id": str(item.id),
            "registry_id": str(item.registry_id),
            "title": item.title,
            "severity": item.severity,
            "status": item.status,
            "completion_criteria": item.completion_criteria,
            "created_at": item.created_at.isoformat(),
            "due_date": item.due_date.isoformat() if item.due_date else None
        })
    
    return {
        "session_id": str(session_id),
        "registry_items": item_data,
        "count": len(item_data)
    }
