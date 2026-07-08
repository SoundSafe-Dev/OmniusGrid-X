"""Authenticated edge telemetry ingest endpoint (tasks 11-15).

`POST /api/v1/edge/ingest` receives a batch of readings from an enrolled agent,
authenticated by its client certificate (:func:`require_agent`), and runs the
five ingest guards in :mod:`app.services.edge_ingest`. The agent identity comes
from the verified certificate, not the request body, so an agent cannot spoof
another's telemetry. Accepted readings are handed downstream; over-rate agents
get 429 so their store-and-forward buffer retries with backoff.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.edge_enroll import require_agent
from app.services.edge_ca import AgentPrincipal
from app.services.edge_ingest import EdgeIngestGateway, RateLimited

router = APIRouter()

# Module-global gateway: holds per-agent dedup/sequence/rate state across requests.
_gateway = EdgeIngestGateway()


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
) -> IngestSummary:
    try:
        result = _gateway.ingest(agent.agent_id, batch.readings)
    except RateLimited as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    # TODO(handoff): accepted readings are forwarded to Redpanda by the existing
    # ingestion worker (Hridyansh's workers/ingestion.py consumes downstream).
    return IngestSummary(**result.summary)
