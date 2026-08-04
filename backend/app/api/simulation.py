"""API routes for the digital-twin / what-if simulation (numeric, no recommendations)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_tenant_db
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
    db: AsyncSession = Depends(get_tenant_db),
) -> Dict[str, Any]:
    """Fleet OEE rollup + bottleneck for the caller's organization (metric only)."""
    from app.services.oee_calculator import oee_calculator

    # `assets` is FORCE ROW LEVEL SECURITY and AsyncSessionLocal binds no
    # app.current_org_id, so the policy matched NOTHING and this returned an empty
    # result for every organisation — a populated fleet reported as having no assets.
    #
    # The `organization_id` filter below was already correct and made no difference:
    # RLS had removed the rows before it ran. That is the sharper half of this class —
    # the application-layer check looks right, so nothing in review points at the
    # session. Same shape as gdpr.py in `test_tenant_session_guard.py`.
    org_id = getattr(current_user, "organization_id", None)
    # ORDERED so the cap and the offset mean something (FS-429). Without an ORDER BY,
    # Postgres may return any rows it likes and different ones next time, so a paged
    # list can repeat rows on page 2 and skip others entirely.
    stmt = select(Asset).order_by(Asset.name)
    if org_id is not None:
        stmt = stmt.where(Asset.organization_id == org_id)
    assets = (await db.execute(stmt.limit(limit))).scalars().all()

    rows: List[Dict[str, Any]] = []
    for asset in assets:
        try:
            metrics = await oee_calculator.calculate_oee(str(asset.id))
            rows.append({"asset_id": str(asset.id), "oee": metrics.oee})
        except Exception:
            continue
    return simulation_engine.fleet_oee_rollup(rows)
