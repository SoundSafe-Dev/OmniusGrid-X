"""API routes for the digital-twin / what-if simulation (numeric, no recommendations)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import Asset
from app.api.auth import get_current_active_user
from app.services.simulation import simulation_engine

router = APIRouter()


class MonteCarloRequest(BaseModel):
    horizon_hours: float = Field(default=168.0, gt=0, le=8760)
    cycle_time_seconds: float = Field(default=60.0, gt=0)
    mtbf_hours: float = Field(default=50.0, ge=0)
    mttr_hours: float = Field(default=2.0, ge=0)
    performance: float = Field(default=0.9, gt=0, le=1)
    quality: float = Field(default=0.98, gt=0, le=1)
    runs: int = Field(default=1000, ge=1, le=20000)
    seed: Optional[int] = None


@router.post("/monte-carlo")
async def run_monte_carlo(
    req: MonteCarloRequest,
    current_user=Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Run a seeded Monte-Carlo throughput/downtime what-if simulation."""
    return simulation_engine.monte_carlo_throughput(
        horizon_hours=req.horizon_hours,
        cycle_time_seconds=req.cycle_time_seconds,
        mtbf_hours=req.mtbf_hours,
        mttr_hours=req.mttr_hours,
        performance=req.performance,
        quality=req.quality,
        runs=req.runs,
        seed=req.seed,
    )


@router.get("/fleet-summary")
async def fleet_summary(
    limit: int = Query(default=200, ge=1, le=1000),
    current_user=Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Fleet OEE rollup + bottleneck for the caller's organization (metric only)."""
    from app.services.oee_calculator import oee_calculator

    org_id = getattr(current_user, "organization_id", None)
    async with AsyncSessionLocal() as session:
        stmt = select(Asset)
        if org_id is not None:
            stmt = stmt.where(Asset.organization_id == org_id)
        assets = (await session.execute(stmt.limit(limit))).scalars().all()

    rows: List[Dict[str, Any]] = []
    for asset in assets:
        try:
            metrics = await oee_calculator.calculate_oee(str(asset.id))
            rows.append({"asset_id": str(asset.id), "oee": metrics.oee})
        except Exception:
            continue
    return simulation_engine.fleet_oee_rollup(rows)
