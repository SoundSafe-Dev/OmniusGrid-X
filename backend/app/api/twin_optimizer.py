"""Tenant-scoped digital-twin optimization API."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.db.models import Asset, User
from app.middleware.rbac import require_operator_or_admin
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from app.services.oee_calculator import oee_calculator
from app.services.twin_optimizer import (
    CandidateAction,
    OptimizationResult,
    SimulationPlan,
    twin_optimizer,
)

router = APIRouter()


class BaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_hours: float = Field(default=168.0, gt=0, le=8760)
    cycle_time_seconds: float = Field(default=60.0, gt=0)
    mtbf_hours: float = Field(default=50.0, ge=0)
    mttr_hours: float = Field(default=2.0, ge=0)
    performance: float = Field(default=0.9, gt=0, le=1)
    quality: float = Field(default=0.98, gt=0, le=1)


class ScenarioOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_time_seconds: float | None = Field(default=None, gt=0)
    mtbf_hours: float | None = Field(default=None, ge=0)
    mttr_hours: float | None = Field(default=None, ge=0)
    performance: float | None = Field(default=None, gt=0, le=1)
    quality: float | None = Field(default=None, gt=0, le=1)

    @model_validator(mode="after")
    def require_change(self) -> "ScenarioOverrides":
        if not self.model_dump(exclude_none=True):
            raise ValueError("At least one simulation override is required")
        return self


class CandidateActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    target_asset_id: UUID | None = None
    recommendation_type: Literal[
        "schedule_change", "parameter_tuning", "maintenance_window"
    ] = "parameter_tuning"
    overrides: ScenarioOverrides
    requires_approval: Literal[True] = True


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ids: list[UUID] = Field(default_factory=list, max_length=100)
    baseline: BaselineRequest = Field(default_factory=BaselineRequest)
    candidates: list[CandidateActionRequest] = Field(
        min_length=1, max_length=10
    )
    runs: int = Field(default=1000, ge=50, le=5000)
    seed: int = 0
    min_improvement_percent: float = Field(default=0.0, ge=0, le=1000)
    max_recommendations: int = Field(default=5, ge=1, le=10)
    emit_recommendations: bool = True
    valid_for_hours: int = Field(default=24, ge=1, le=168)

    @model_validator(mode="after")
    def unique_identifiers(self) -> "OptimizeRequest":
        asset_ids = [str(asset_id) for asset_id in self.asset_ids]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_ids must be unique")
        action_ids = [candidate.action_id for candidate in self.candidates]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("candidate action_id values must be unique")
        return self


class ExpectedImpactResponse(BaseModel):
    throughput_delta_parts: float
    throughput_improvement_percent: float
    downtime_reduction_hours: float
    availability_improvement_points: float
    objective_score: float


class RecommendationResponse(BaseModel):
    rank: int
    recommendation_id: str
    action_id: str
    name: str
    description: str
    asset_id: str | None
    recommendation_type: str
    priority: int
    confidence: float
    expected_impact: ExpectedImpactResponse
    scenario_inputs: dict[str, Any]
    scenario_metrics: dict[str, Any]
    simulation_basis: str
    requires_approval: bool
    strategic_engine_emitted: bool


class OptimizeResponse(BaseModel):
    organization_id: UUID
    objective: str
    evaluated_candidates: int
    baseline_simulation: dict[str, Any]
    fleet_summary: dict[str, Any]
    recommendations: list[RecommendationResponse]
    generated_at: datetime


def _response(result: OptimizationResult) -> OptimizeResponse:
    return OptimizeResponse.model_validate(result.as_dict())


async def _verify_owned_assets(
    db: AsyncSession,
    organization_id: UUID,
    asset_ids: set[UUID],
) -> None:
    if not asset_ids:
        return
    rows = (
        await db.execute(
            select(Asset.id).where(
                Asset.organization_id == organization_id,
                Asset.id.in_(asset_ids),
            )
        )
    ).scalars().all()
    if {str(asset_id) for asset_id in rows} != {
        str(asset_id) for asset_id in asset_ids
    }:
        raise HTTPException(status_code=404, detail="Asset not found")


async def _fleet_asset_ids(
    db: AsyncSession,
    organization_id: UUID,
    requested_asset_ids: list[UUID],
) -> list[str]:
    if requested_asset_ids:
        await _verify_owned_assets(
            db, organization_id, set(requested_asset_ids)
        )
        return [str(asset_id) for asset_id in requested_asset_ids]

    rows = (
        await db.execute(
            select(Asset.id)
            .where(
                Asset.organization_id == organization_id,
                Asset.is_active.is_(True),
            )
            .order_by(Asset.name.asc(), Asset.id.asc())
            .limit(100)
        )
    ).scalars().all()
    return [str(asset_id) for asset_id in rows]


async def _fleet_oee(asset_ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        try:
            metrics = await oee_calculator.calculate_oee(asset_id)
        except Exception:
            continue
        rows.append({"asset_id": asset_id, "oee": metrics.oee})
    return rows


@router.post("/optimize", response_model=OptimizeResponse, dependencies=[Depends(require_operator_or_admin)])
async def optimize_twin(
    payload: OptimizeRequest,
    current_user: User = Depends(get_current_active_user),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> OptimizeResponse:
    """Rank beneficial what-if actions for assets owned by the caller's tenant."""
    target_asset_ids = {
        candidate.target_asset_id
        for candidate in payload.candidates
        if candidate.target_asset_id is not None
    }
    await _verify_owned_assets(db, organization_id, target_asset_ids)
    fleet_asset_ids = await _fleet_asset_ids(
        db, organization_id, payload.asset_ids
    )
    fleet_assets = await _fleet_oee(fleet_asset_ids)

    baseline = SimulationPlan(
        **payload.baseline.model_dump(),
        runs=payload.runs,
        seed=payload.seed,
    )
    candidates = [
        CandidateAction(
            action_id=candidate.action_id,
            name=candidate.name,
            description=candidate.description,
            parameter_overrides=candidate.overrides.model_dump(
                exclude_none=True
            ),
            asset_id=(
                str(candidate.target_asset_id)
                if candidate.target_asset_id is not None
                else None
            ),
            recommendation_type=candidate.recommendation_type,
            requires_approval=candidate.requires_approval,
        )
        for candidate in payload.candidates
    ]
    result = await twin_optimizer.optimize(
        str(organization_id),
        baseline,
        candidates,
        fleet_assets,
        min_improvement_percent=payload.min_improvement_percent,
        max_recommendations=payload.max_recommendations,
        emit_recommendations=payload.emit_recommendations,
        valid_for_hours=payload.valid_for_hours,
    )
    return _response(result)
