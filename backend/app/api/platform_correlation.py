"""Attach live platform data to analysis sessions as correlation sources.

Separate router (does not edit analysis_sessions.py, owned on gemma-correlation-ai)
that reuses the SessionDataSource model. Attached rows appear in DataSourcesPanel
and are consumed by the existing correlate_session — so sensor/yard/transport data
becomes correlatable with no change to the correlation engine.
"""

from typing import Any, Dict, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.db.database import get_db
from app.db.models import AnalysisSession, SessionDataSource, User
from app.services import platform_correlation as pc

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/nlp", tags=["NLP Correlation"])


class AttachPlatformDataRequest(BaseModel):
    source_type: str = Field(..., description="asset_telemetry | yard | transportation")
    params: Dict[str, Any] = Field(default_factory=dict)


class PlatformSourceType(BaseModel):
    source_type: str
    label: str


class AttachedSource(BaseModel):
    id: str
    source_type: str
    source_id: Optional[str]
    file_name: Optional[str]
    data_type: Optional[str]
    row_count: int


@router.get("/platform-sources", response_model=list[PlatformSourceType])
async def list_platform_source_types(_user: User = Depends(get_current_active_user)):
    """The platform data sources that can be attached to a session (the toggles)."""
    return pc.available_source_types()


@router.post("/sessions/{session_id}/platform-data", response_model=AttachedSource)
async def attach_platform_data(
    session_id: UUID,
    body: AttachPlatformDataRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Pull data from a platform domain and attach it as a session data source."""
    session = (await db.execute(
        select(AnalysisSession).where(AnalysisSession.id == str(session_id))
    )).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    provider = pc.get_provider(body.source_type)
    if provider is None:
        raise HTTPException(
            status_code=400,
            detail=f"unknown source_type; available: {[s['source_type'] for s in pc.available_source_types()]}",
        )

    try:
        result = await provider(db, str(current_user.organization_id), body.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ds = SessionDataSource(
        session_id=str(session_id),
        source_type=body.source_type,
        source_id=str(body.params.get("asset_id") or body.params.get("id") or body.source_type),
        file_name=result.file_name,
        data_type="spreadsheet",  # engine's tabular path -> domain + key detection
        processed_data=result.to_processed_data(),
        meta_data={"platform_source": True, "source_type": body.source_type},
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    logger.info("platform_data_attached", session_id=str(session_id),
                source_type=body.source_type, rows=len(result.records))

    return AttachedSource(
        id=str(ds.id), source_type=ds.source_type, source_id=ds.source_id,
        file_name=ds.file_name, data_type=ds.data_type, row_count=len(result.records),
    )
