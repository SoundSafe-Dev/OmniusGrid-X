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
from pydantic import BaseModel
from sqlalchemy import select

from app.api.edge_enroll import require_agent
from app.db.models import User
from app.middleware.rbac import require_admin
from app.db.database import AsyncSessionLocal
from app.db.edge_fleet_models import EdgeAgentStatus
from app.services.edge_ca import AgentPrincipal
from app.services import edge_fleet

router = APIRouter()


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


class AgentStatusOut(BaseModel):
    agent_id: str
    liveness: str
    last_seen: Optional[str]
    buffer_pending: int
    dead_lettered: int
    active_collectors: int
    total_collectors: int
    cert_expires_in_seconds: Optional[int]


@router.post("/api/v1/edge/heartbeat", response_model=HeartbeatAck, tags=["Edge"])
async def heartbeat(
    payload: HeartbeatPayload,
    agent: AgentPrincipal = Depends(require_agent),
) -> HeartbeatAck:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        row = await session.get(EdgeAgentStatus, agent.agent_id)
        if row is None:
            row = EdgeAgentStatus(agent_id=agent.agent_id)
            session.add(row)
        row.agent_version = payload.agent_version
        row.last_seen = now
        row.buffer_pending = payload.buffer_pending
        row.dead_lettered = payload.dead_lettered
        row.dropped = payload.dropped
        row.active_collectors = payload.active_collectors
        row.total_collectors = payload.total_collectors
        row.cert_expires_in_seconds = payload.cert_expires_in_seconds
        await session.commit()

    edge_fleet.update_fleet_metrics(agent.agent_id, payload.model_dump(), "online")
    return HeartbeatAck(ok=True, server_time=now.isoformat())


def _to_out(row: EdgeAgentStatus, now: datetime) -> AgentStatusOut:
    return AgentStatusOut(
        agent_id=row.agent_id,
        liveness=edge_fleet.agent_liveness(row.last_seen, now),
        last_seen=row.last_seen.isoformat() if row.last_seen else None,
        buffer_pending=row.buffer_pending or 0,
        dead_lettered=row.dead_lettered or 0,
        active_collectors=row.active_collectors or 0,
        total_collectors=row.total_collectors or 0,
        cert_expires_in_seconds=row.cert_expires_in_seconds,
    )


@router.get("/api/v1/edge/fleet", response_model=List[AgentStatusOut], tags=["Edge"])
async def list_fleet(user: User = Depends(require_admin)) -> List[AgentStatusOut]:
    """List this organization's agents. Backs the /admin/collectors page.

    Was gated on get_current_active_user with an unscoped `select(...)`. Since
    edge_agent_status carries organization_id but has no RLS policy and this
    runs on AsyncSessionLocal rather than the tenant session, every
    authenticated user saw every tenant's agents — ids, versions, cert expiry
    and buffer stats. Now admin-only and organization-scoped.
    """
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
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
    async with AsyncSessionLocal() as session:
        row = await session.get(EdgeAgentStatus, agent_id)
    # 404 rather than 403 for another tenant's agent: distinguishing the two
    # would confirm the agent id exists.
    if row is None or row.organization_id != str(user.organization_id):
        raise HTTPException(404, detail="unknown agent")
    return _to_out(row, datetime.now(timezone.utc))
