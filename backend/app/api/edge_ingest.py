"""Authenticated edge telemetry ingest endpoint (tasks 11-15).

`POST /api/v1/edge/ingest` receives a batch of readings from an enrolled agent,
authenticated by its client certificate (:func:`require_agent`), and runs the
five ingest guards in :mod:`app.services.edge_ingest`. The agent identity comes
from the verified certificate, not the request body, so an agent cannot spoof
another's telemetry. Accepted readings are handed downstream; over-rate agents
get 429 so their store-and-forward buffer retries with backoff.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.edge_enroll import require_agent
from app.db.database import get_db
from app.db.models import Asset
from app.services.edge_ca import AgentPrincipal
from app.services.edge_ingest import EdgeIngestGateway, RateLimited, RedpandaForwarder
from app.core.tasks import spawn

logger = structlog.get_logger()

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
    # ACCEPTED IS NOT FORWARDED, and the two used to be indistinguishable.
    #
    # `accepted` means a reading passed validation, dedup and sequencing. Forwarding is
    # a separate step that resolves each reading's organisation to pick a topic — and
    # that lookup reads `assets`, which is FORCE ROW LEVEL SECURITY, through a session
    # with no tenant GUC. It returns None for every asset, so `by_org` stays empty and
    # NOTHING is published, while the response still reported `accepted: N`.
    #
    # Verified against a real database: `_resolve_org` returns None for an asset that
    # demonstrably exists. Reporting the two counts separately means a caller can see
    # the difference instead of inferring delivery from acceptance.
    forwarded: int = 0


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
    #
    # `spawn`, NOT a bare `create_task` (FS-674). The event loop holds only a WEAK
    # reference to a task, so a discarded one may be collected mid-execution — here that
    # is a batch of accepted readings that is never forwarded, on a path whose response
    # has already told the agent how many were. `spawn` retains the reference and logs a
    # failure instead of leaving it as an unretrieved exception on the asyncio logger.
    by_org: Dict[str, List[Dict[str, Any]]] = {}
    unresolved = 0
    for reading in result.accepted:
        org = await _resolve_org(db, str(reading.get("asset_id")))
        if org is not None:
            by_org.setdefault(org, []).append(reading)
        else:
            unresolved += 1
    for org, readings in by_org.items():
        spawn(_forwarder.forward(org, readings), name="edge_ingest.forward")

    if unresolved:
        # Loud, because the alternative is a success response describing delivery that
        # did not happen. Two known causes, and the second is the live one:
        #   * the asset genuinely does not exist, or
        #   * `assets` is FORCE RLS and this route has no tenant context to read it
        #     with, so EVERY lookup returns None.
        # Nothing calls this endpoint today — the edge agent publishes straight to the
        # broker — which is why a total forwarding failure has never been noticed.
        logger.warning(
            "edge_ingest_unresolved_org",
            agent_id=agent.agent_id,
            unresolved=unresolved,
            accepted=len(result.accepted),
            detail=(
                "readings were accepted but could not be routed to a topic; if this is "
                "every reading, the asset lookup is running without tenant context"
            ),
        )

    # Dead-letter handoff. Without this the endpoint reported `quarantined: N`
    # for readings that had been discarded — the count was true and the word was
    # not. Same fire-and-forget shape as the accepted path, and keyed on the
    # certificate-verified agent_id because a reading that failed validation
    # cannot be trusted to say which asset it came from.
    if result.quarantined:
        spawn(
            _forwarder.forward_quarantined(agent.agent_id, result.quarantined),
            name="edge_ingest.forward_quarantined",
        )

    return IngestSummary(**result.summary, forwarded=sum(len(v) for v in by_org.values()))
