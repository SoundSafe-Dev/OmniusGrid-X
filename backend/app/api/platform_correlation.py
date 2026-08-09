"""Attach live platform data to analysis sessions as correlation sources.

Separate router (does not edit analysis_sessions.py, owned on gemma-correlation-ai)
that reuses the SessionDataSource model. Attached rows appear in DataSourcesPanel
and are consumed by the existing correlate_session — so sensor/yard/transport data
becomes correlatable with no change to the correlation engine.

TENANT SESSION, NOT get_db. `analysis_sessions` is RLS-protected; on a session with no
`app.current_org_id` the policy matched nothing and this endpoint returned an empty
result.
"""

from typing import Any, Dict, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.db.database import get_db  # noqa: F401
from app.middleware.tenant_isolation import get_tenant_db
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


def _source_row_id(params: dict) -> Optional[str]:
    """The id of the row a platform source came from, or None when there is not one.

    None rather than a stand-in: "this source is the whole ERP" and "this source is asset
    X" are different facts, and the column is read as a uuid by every consumer.
    """
    row_id = (params or {}).get("asset_id") or (params or {}).get("id")
    return str(row_id) if row_id else None


@router.post("/sessions/{session_id}/platform-data", response_model=AttachedSource)
async def attach_platform_data(
    session_id: UUID,
    body: AttachPlatformDataRequest,
    db: AsyncSession = Depends(get_tenant_db),
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
        # `source_id` is the id of the ROW this source came from, and a platform-wide source
        # — the ERP as a whole, the yard as a whole — has no such row (FS-418). Falling back
        # to the source_type string wrote "erp" or "yard" into a column every consumer reads
        # as a uuid: both `AddDataSourceRequest` and `DataSourceResponse` declare
        # `Optional[UUID]`, so `GET /nlp/sessions/{id}/data` then 500s for that session
        # FOREVER and the data-sources panel on the Correlation AI page never loads again.
        #
        # One click to break a session, permanently, with no error at the point of the click.
        source_id=_source_row_id(body.params),
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
