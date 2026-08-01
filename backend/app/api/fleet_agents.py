"""Fleet agent visibility APIs."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import Asset
from pydantic import BaseModel

router = APIRouter()


class AgentVersionRow(BaseModel):
    #: `coalesce(agent_version, 'unknown')` — an asset that has never reported one is
    #: bucketed under "unknown" rather than dropped, so the counts add up to the fleet.
    agent_version: str
    asset_count: int
    agent_count: int
    config_hash_count: int
    #: `max(agent_last_heartbeat)` for the bucket — a datetime, not a string, unlike most
    #: timestamps on this surface. `None` for a version nothing has checked in on.
    latest_heartbeat: Optional[datetime] = None


class AgentVersionDistribution(BaseModel):
    items: List[AgentVersionRow]
    total_assets: int


@router.get("/agents/versions", response_model=AgentVersionDistribution,
            summary="Get edge-agent version distribution")
async def get_agent_version_distribution(
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    version = func.coalesce(Asset.agent_version, "unknown").label("agent_version")
    rows = (
        await db.execute(
            select(
                version,
                func.count(Asset.id).label("asset_count"),
                func.count(func.distinct(Asset.agent_id)).label("agent_count"),
                func.count(func.distinct(Asset.agent_config_hash)).label(
                    "config_hash_count"
                ),
                func.max(Asset.agent_last_heartbeat).label("latest_heartbeat"),
            )
            .where(Asset.organization_id == org_id)
            .group_by(version)
            .order_by(version.asc())
        )
    ).mappings().all()

    items = [
        {
            "agent_version": row["agent_version"],
            "asset_count": row["asset_count"],
            "agent_count": row["agent_count"],
            "config_hash_count": row["config_hash_count"],
            "latest_heartbeat": row["latest_heartbeat"],
        }
        for row in rows
    ]
    return {
        "items": items,
        "total_assets": sum(item["asset_count"] for item in items),
    }
