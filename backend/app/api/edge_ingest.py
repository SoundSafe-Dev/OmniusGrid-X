"""Authenticated edge telemetry ingest endpoint (tasks 11-15).

`POST /api/v1/edge/ingest` receives a batch of readings from an enrolled agent,
authenticated by its client certificate (:func:`require_agent`), and runs the
five ingest guards in :mod:`app.services.edge_ingest`. The agent identity comes
from the verified certificate, not the request body, so an agent cannot spoof
another's telemetry. Accepted readings are handed downstream; over-rate agents
get 429 so their store-and-forward buffer retries with backoff.
"""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.edge_enroll import require_agent
from app.db.database import get_db
from app.db.models import Asset
from app.services.edge_ca import AgentPrincipal
from app.services.edge_ingest import EdgeIngestGateway, RateLimited, RedpandaForwarder

router = APIRouter()

# Module-global gateway: holds per-agent dedup/sequence/rate state across requests.
_gateway = EdgeIngestGateway()
# Fire-and-forget Redpanda handoff (circuit-broken; safe without a broker).
_forwarder = RedpandaForwarder()
# asset_id -> organization_id cache for topic routing.
_org_cache: Dict[str, str] = {}


async def _resolve_org(db: AsyncSession, asset_id: str) -> Optional[str]:
    if asset_id in _org_cache:
        return _org_cache[asset_id]
    org = (await db.execute(
        select(Asset.organization_id).where(Asset.id == asset_id)
    )).scalar_one_or_none()
    if org is not None:
        _org_cache[asset_id] = str(org)
        return _org_cache[asset_id]
    return None


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
    db: AsyncSession = Depends(get_db),
) -> IngestSummary:
    try:
        result = _gateway.ingest(agent.agent_id, batch.readings)
    except RateLimited as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    # Redpanda handoff (audit FIX #2): publish accepted readings to the
    # `telemetry.{org}.{asset}` topics the ingestion worker consumes. Grouped by
    # org and fired as a background task so the agent's request never blocks on
    # the broker; on broker outage the forwarder's circuit opens and the edge's
    # store-and-forward re-delivers later.
    by_org: Dict[str, List[Dict[str, Any]]] = {}
    for reading in result.accepted:
        org = await _resolve_org(db, str(reading.get("asset_id")))
        if org is not None:
            by_org.setdefault(org, []).append(reading)
    for org, readings in by_org.items():
        asyncio.get_event_loop().create_task(_forwarder.forward(org, readings))

    # Dead-letter handoff. Without this the endpoint reported `quarantined: N`
    # for readings that had been discarded — the count was true and the word was
    # not. Same fire-and-forget shape as the accepted path, and keyed on the
    # certificate-verified agent_id because a reading that failed validation
    # cannot be trusted to say which asset it came from.
    if result.quarantined:
        asyncio.get_event_loop().create_task(
            _forwarder.forward_quarantined(agent.agent_id, result.quarantined)
        )

    return IngestSummary(**result.summary)
