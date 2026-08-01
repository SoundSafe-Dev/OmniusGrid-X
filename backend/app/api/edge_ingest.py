"""Authenticated edge telemetry ingest endpoint (tasks 11-15).

`POST /api/v1/edge/ingest` receives a batch of readings from an enrolled agent,
authenticated by its client certificate (:func:`require_agent`), and runs the
five ingest guards in :mod:`app.services.edge_ingest`. The agent identity comes
from the verified certificate, not the request body, so an agent cannot spoof
another's telemetry. Accepted readings are handed downstream; over-rate agents
get 429 so their store-and-forward buffer retries with backoff.
"""

import asyncio
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.edge_enroll import require_agent
from app.core.tenant import tenant_session
from app.db.models import Asset
from app.services.edge_ca import AgentPrincipal
from app.services.edge_ingest import EdgeIngestGateway, RateLimited, RedpandaForwarder

router = APIRouter()

# Module-global gateway: holds per-agent dedup/sequence/rate state across requests.
_gateway = EdgeIngestGateway()
# Fire-and-forget Redpanda handoff (circuit-broken; safe without a broker).
_forwarder = RedpandaForwarder()


async def _owned_asset_ids(
    db: AsyncSession,
    asset_ids: set[UUID],
    organization_id: UUID,
    agent_id: str,
) -> set[str]:
    if not asset_ids:
        return set()
    owned = (await db.execute(
        select(Asset.id).where(
            Asset.id.in_(asset_ids),
            Asset.organization_id == organization_id,
            Asset.agent_id == agent_id,
        )
    )).scalars().all()
    return {str(asset_id) for asset_id in owned}


class IngestBatch(BaseModel):
    readings: List[Dict[str, Any]] = Field(default_factory=list)


class IngestSummary(BaseModel):
    accepted: int
    deduped: int
    quarantined: int
    out_of_order: int
    gaps: int


@router.post("/api/v1/edge/ingest", response_model=IngestSummary, tags=["Edge"])
async def ingest_batch(
    batch: IngestBatch,
    agent: AgentPrincipal = Depends(require_agent),
    x_organization_id: str = Header(default="", alias="X-Organization-ID"),
) -> IngestSummary:
    try:
        organization_id = UUID(x_organization_id)
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="X-Organization-ID must be a UUID",
        )

    # Validate ownership before the stateful gateway touches rate, dedupe, or
    # sequence state. Otherwise an unauthorized reading could be silently
    # dropped after being acknowledged and could poison a later legitimate
    # retry as a duplicate.
    asset_ids: set[UUID] = set()
    for reading in batch.readings:
        if not isinstance(reading, dict) or not reading.get("asset_id"):
            continue  # the gateway quarantines malformed readings
        try:
            asset_ids.add(UUID(str(reading["asset_id"])))
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="asset_id must be a UUID",
            )

    async with tenant_session(organization_id) as db:
        owned_ids = await _owned_asset_ids(
            db,
            asset_ids,
            organization_id,
            agent.agent_id,
        )
    if owned_ids != {str(asset_id) for asset_id in asset_ids}:
        # Keep unknown, foreign-tenant, and other-agent assets indistinguishable.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="batch contains an asset not assigned to this agent",
        )

    try:
        result = _gateway.ingest(agent.agent_id, batch.readings)
    except RateLimited as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    # Redpanda handoff (audit FIX #2): publish accepted readings to the
    # `telemetry.{org}.{asset}` topics the ingestion worker consumes. Grouped by
    # org and fired as a background task so the agent's request never blocks on
    # the broker; on broker outage the forwarder's circuit opens and the edge's
    # store-and-forward re-delivers later.
    # The header is only a routing hint. The verified certificate supplies the
    # agent identity, and the ownership check above binds every accepted asset
    # to that agent inside the hinted tenant before any reading is forwarded.
    org = str(organization_id)
    if result.accepted:
        asyncio.get_event_loop().create_task(
            _forwarder.forward(org, result.accepted)
        )

    return IngestSummary(**result.summary)
