"""Edge fleet API: heartbeat ingest + fleet status (tasks 16, 17).

`POST /api/v1/edge/heartbeat` — an authenticated agent reports its health; we
upsert its status row, publish metrics, and echo ``server_time`` so the agent's
clock-skew estimator (edge task 21) can sample the backend clock.

`GET /api/v1/edge/fleet` / `/{agent_id}` — operators list agents with computed
liveness (online/stale/offline). Read endpoints use the normal user auth; the
heartbeat uses agent-certificate auth so identity comes from the cert, not body.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import structlog

from app.api.edge_enroll import require_agent
from app.core.tenant import tenant_session
from app.db.models import User
from app.middleware.rbac import require_admin
from app.db.edge_fleet_models import EdgeAgentStatus
from app.services.wire_codec import ADVERTISED_CODECS
from app.services.edge_ca import AgentPrincipal
from app.services import edge_fleet, ingest_pressure

router = APIRouter()
logger = structlog.get_logger(__name__)


class HeartbeatPayload(BaseModel):
    agent_version: Optional[str] = None
    buffer_pending: int = 0
    dead_lettered: int = 0
    dropped: int = 0
    active_collectors: int = 0
    total_collectors: int = 0
    cert_expires_in_seconds: Optional[int] = None


class HeartbeatAck(BaseModel):
    ok: bool
    server_time: str
    #: FS-866. What the CLOUD is asking the agent to do about its send rate.
    #:
    #: Kafka gives a producer no view of consumer lag, so before this the agent drained its
    #: buffer as fast as the link allowed regardless of whether anything was keeping up —
    #: and the pipeline's only recourse when it fell behind was to SHED, destroying
    #: readings that had been sitting safely in a durable buffer on the device moments
    #: earlier. Slowing the producer leaves the data where it is safest.
    #:
    #: Defaulted, so an OLD AGENT IS UNAFFECTED: it ignores an unknown field and behaves
    #: exactly as it does today. The negotiation note below applies here too — this is a
    #: hint the agent may honour, never an instruction it must.
    ingest_pressure: str = "normal"
    #: FS-759. What THIS backend can decode on the uplink, so an agent knows whether it may
    #: compress. Negotiation is required in this direction and only this direction: a new
    #: backend reads an old agent's bare JSON unaided, but a new agent talking to an OLD
    #: backend would send bytes that backend cannot parse — and the buffer would mark them
    #: sent, turning a delay into permanent loss. An agent that sees no advertisement emits
    #: `raw`, so the absent field on an older deployment means "do not compress" rather than
    #: an unhandled case.
    wire_codecs: List[str] = Field(default_factory=lambda: list(ADVERTISED_CODECS))


class AgentStatusOut(BaseModel):
    agent_id: str
    liveness: str
    last_seen: Optional[str]
    buffer_pending: int
    dead_lettered: int
    #: FS-591. Declared last, and it was missing entirely. The agent counts discarded
    #: telemetry, sends it every heartbeat, `HeartbeatPayload` accepts it and the handler
    #: writes it to `edge_agent_status.dropped` — and this model omitted it, so FastAPI
    #: deleted it on the way out and no fleet view has ever shown how much data an agent
    #: has lost.
    #:
    #: `buffer_pending` is waiting to send and `dead_lettered` is replayable. **This one is
    #: gone.** It was the only unrecoverable figure of the three and the only one with no
    #: response field, no gauge and no alert.
    dropped: int = 0
    active_collectors: int
    total_collectors: int
    cert_expires_in_seconds: Optional[int]


def _claimed(agent: AgentPrincipal) -> HTTPException:
    logger.warning(
        "edge_agent_id_claimed_by_another_tenant",
        agent_id=agent.agent_id,
        claimant=str(agent.organization_id),
    )
    return HTTPException(409, detail="agent id is registered to another organization")


@router.post("/api/v1/edge/heartbeat", response_model=HeartbeatAck, tags=["Edge"])
async def heartbeat(
    payload: HeartbeatPayload,
    agent: AgentPrincipal = Depends(require_agent),
) -> HeartbeatAck:
    if not agent.organization_id:
        # No tenant to bind, and `edge_agent_status` is FORCE ROW LEVEL SECURITY as of
        # migration 057 — an unbound write is rejected by the policy regardless. Refusing here
        # turns that into a diagnosable 409 naming the remedy, and it refuses rather than
        # writing an unattributed row: such a row is invisible to every tenant, so accepting it
        # would be a 200 that discards the write.
        #
        # Only a certificate issued before agents carried an organisation reaches this. Agent
        # certificates have a 30-day TTL, so the window closes itself within one lifetime.
        logger.warning("edge_agent_heartbeat_unattributed", agent_id=agent.agent_id)
        raise HTTPException(
            409, detail="certificate carries no organization; re-enroll this agent"
        )

    now = datetime.now(timezone.utc)
    async with tenant_session(agent.organization_id) as session:
        row = await session.get(EdgeAgentStatus, agent.agent_id)
        if row is None:
            row = EdgeAgentStatus(agent_id=agent.agent_id)
            session.add(row)
        elif row.organization_id and row.organization_id != str(agent.organization_id):
            # `agent_id` is the PRIMARY KEY here — one global namespace across every tenant —
            # and the CA signs a certificate for whatever id is asked for. While the column was
            # never written this was inert: a second tenant enrolling the same id overwrote
            # counters on a row nobody could read. Attributing the row arms it, because the last
            # heartbeat would win the tenancy and move the agent off its owner's fleet page.
            # Fixing one half of a defect can arm the other half.
            #
            # Under the policy this branch is unreachable — the other tenant's row is filtered
            # out of the `get` above, so the collision surfaces as the primary-key violation
            # handled below. It is kept for the SQLite offline path, where RLS is a no-op and
            # this check is the only thing standing between the two tenants.
            raise _claimed(agent)

        # THE COLUMN NOBODY WROTE. The status row was created with an agent_id and nothing
        # else, so organization_id was NULL on every row ever written — while both read
        # endpoints filter on it. NULL never equals a uuid, so /admin/collectors was empty in
        # every deployment, for every tenant, since the endpoint was written, and read as
        # "no agents".
        #
        # Set on the UPDATE path too, not just on creation: an agent enrolled before
        # certificates carried a tenant already has a row, and a fix that only ran at creation
        # would leave every running fleet exactly as invisible as before while looking correct
        # in a fresh database.
        row.organization_id = str(agent.organization_id)
        row.agent_version = payload.agent_version
        row.last_seen = now
        row.buffer_pending = payload.buffer_pending
        row.dead_lettered = payload.dead_lettered
        row.dropped = payload.dropped
        row.active_collectors = payload.active_collectors
        row.total_collectors = payload.total_collectors
        row.cert_expires_in_seconds = payload.cert_expires_in_seconds
        try:
            await session.commit()
        except IntegrityError:
            # The id belongs to another tenant, whose row the policy hid from the `get` above.
            await session.rollback()
            raise _claimed(agent)

    edge_fleet.update_fleet_metrics(agent.agent_id, payload.model_dump(), "online")
    # FS-866. Read per heartbeat rather than pushed: the agent already polls this endpoint
    # on its own schedule, so the signal costs no new connection and inherits the retry
    # behaviour the heartbeat already has. `current()` answers "normal" whenever it cannot
    # say otherwise, so a Redis outage restores today's behaviour instead of throttling a
    # fleet on a guess.
    return HeartbeatAck(
        ok=True,
        server_time=now.isoformat(),
        ingest_pressure=await ingest_pressure.current(),
    )


def _to_out(row: EdgeAgentStatus, now: datetime) -> AgentStatusOut:
    return AgentStatusOut(
        agent_id=row.agent_id,
        liveness=edge_fleet.agent_liveness(row.last_seen, now),
        last_seen=row.last_seen.isoformat() if row.last_seen else None,
        buffer_pending=row.buffer_pending or 0,
        dead_lettered=row.dead_lettered or 0,
        dropped=row.dropped or 0,
        active_collectors=row.active_collectors or 0,
        total_collectors=row.total_collectors or 0,
        cert_expires_in_seconds=row.cert_expires_in_seconds,
    )


@router.get("/api/v1/edge/fleet", response_model=List[AgentStatusOut], tags=["Edge"])
async def list_fleet(user: User = Depends(require_admin)) -> List[AgentStatusOut]:
    """List this organization's agents. Backs the /admin/collectors page.

    Was gated on get_current_active_user with an unscoped `select(...)`. At the time
    `edge_agent_status` had no policy AND this ran on AsyncSessionLocal rather than the
    tenant session, so every authenticated user saw every tenant's agents — ids, versions,
    cert expiry and buffer stats. Now admin-only, organization-scoped, and migration 057
    added the policy underneath it.
    """
    now = datetime.now(timezone.utc)
    # Both layers, in migration 051's order: the explicit filter AND the policy. The filter is
    # what works on the SQLite offline path, where RLS is a no-op; the policy is what holds when
    # a future handler forgets the filter, which is how this table's sibling tables got here.
    async with tenant_session(user.organization_id) as session:
        rows = (
            await session.execute(
                select(EdgeAgentStatus).where(
                    EdgeAgentStatus.organization_id == str(user.organization_id)
                )
            )
        ).scalars().all()
    return [_to_out(r, now) for r in rows]


@router.get("/api/v1/edge/fleet/{agent_id}", response_model=AgentStatusOut, tags=["Edge"])
async def get_agent(agent_id: str, user: User = Depends(require_admin)) -> AgentStatusOut:
    async with tenant_session(user.organization_id) as session:
        row = await session.get(EdgeAgentStatus, agent_id)
    # 404 rather than 403 for another tenant's agent: distinguishing the two
    # would confirm the agent id exists.
    if row is None or row.organization_id != str(user.organization_id):
        raise HTTPException(404, detail="unknown agent")
    return _to_out(row, datetime.now(timezone.utc))
