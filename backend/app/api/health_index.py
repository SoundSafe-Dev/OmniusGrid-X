"""API routes for the Asset Health Index (a computed metric, not recommendations)."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_tenant_db
from app.db.models import Asset
from app.api.auth import get_current_active_user
from app.services.health_index import health_index_calculator

router = APIRouter()


class HealthResponse(BaseModel):
    asset_id: str
    health_score: float
    drivers: List[Dict[str, Any]]
    confidence: float
    computed_at: str


@router.get("/{asset_id}", response_model=HealthResponse)
async def get_asset_health(
    asset_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    current_user=Depends(get_current_active_user),
):
    """Compute the health index for a single asset from recent OEE + alarms."""
    result = await health_index_calculator.get_asset_health(asset_id, hours=hours)
    return result.as_dict()


@router.get("", response_model=List[HealthResponse])
async def list_asset_health(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=100, ge=1, le=500),
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Health index for the caller's organization's assets (metric only)."""
    # `assets` is FORCE ROW LEVEL SECURITY and AsyncSessionLocal binds no
    # app.current_org_id, so the policy matched NOTHING and this returned an empty
    # result for every organisation — a populated fleet reported as having no assets.
    #
    # The `organization_id` filter below was already correct and made no difference:
    # RLS had removed the rows before it ran. That is the sharper half of this class —
    # the application-layer check looks right, so nothing in review points at the
    # session. Same shape as gdpr.py in `test_tenant_session_guard.py`.
    org_id = getattr(current_user, "organization_id", None)
    stmt = select(Asset)
    if org_id is not None:
        stmt = stmt.where(Asset.organization_id == org_id)
    rows = (await db.execute(stmt.limit(limit))).scalars().all()

    results = []
    for asset in rows:
        result = await health_index_calculator.get_asset_health(str(asset.id), hours=hours)
        results.append(result.as_dict())
    return results
