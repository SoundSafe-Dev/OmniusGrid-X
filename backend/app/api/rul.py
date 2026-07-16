"""Tenant-scoped predictive-maintenance and RUL API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.services.rul import RULAssessment, rul_service

router = APIRouter()


class MaintenanceWindowResponse(BaseModel):
    start: datetime
    end: datetime
    urgency: str
    reason: str


class RULResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    asset_id: str
    health_score: float
    failure_probability: float
    probability_horizon_hours: int
    remaining_useful_life_hours: float
    risk_level: str
    confidence: float
    recommended_maintenance_window: MaintenanceWindowResponse
    drivers: list[dict[str, Any]]
    model_source: str
    computed_at: datetime
    notification_dispatched: bool
    notification_delivery_count: int


def _response(assessment: RULAssessment) -> RULResponse:
    return RULResponse.model_validate(assessment.as_dict())


async def _verify_asset(
    db: AsyncSession,
    asset_id: UUID,
    organization_id: UUID,
) -> None:
    result = await db.execute(
        select(Asset.id).where(
            Asset.id == asset_id,
            Asset.organization_id == organization_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Asset not found")


@router.get("", response_model=list[RULResponse])
async def list_rul_assessments(
    hours: int = Query(default=24, ge=1, le=168),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[RULResponse]:
    """Estimate RUL for a page of the caller's assets without alert fan-out."""
    asset_ids = (
        await db.execute(
            select(Asset.id)
            .where(Asset.organization_id == organization_id)
            .order_by(Asset.name.asc(), Asset.id.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    assessments = []
    for asset_id in asset_ids:
        assessment = await rul_service.assess_asset(
            str(asset_id),
            organization_id,
            health_window_hours=hours,
            dispatch_notification=False,
        )
        assessments.append(_response(assessment))
    return assessments


@router.get("/{asset_id}", response_model=RULResponse)
async def get_rul_assessment(
    asset_id: UUID,
    hours: int = Query(default=24, ge=1, le=168),
    notify: bool = Query(default=True),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> RULResponse:
    """Estimate one tenant-owned asset and optionally dispatch its recommendation."""
    await _verify_asset(db, asset_id, organization_id)
    assessment = await rul_service.assess_asset(
        str(asset_id),
        organization_id,
        health_window_hours=hours,
        dispatch_notification=notify,
    )
    return _response(assessment)
