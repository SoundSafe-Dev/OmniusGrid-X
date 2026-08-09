"""Fleet agent visibility and bounded remote-operation APIs."""

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import Asset
from pydantic import BaseModel
from app.db.models import Asset, Command, User
from app.middleware.rate_limit import remote_operation_rate_limit
from app.middleware.rbac import require_operator_or_admin
from app.services.command_executor import command_executor
from app.services.remote_operations import (
    AGENT_DIAGNOSTICS,
    AGENT_EFFECTIVE_CONFIG,
    AGENT_FETCH_LOGS,
    COLLECTOR_RESTART,
    CollectorRestartRequest,
    DiagnosticsRequest,
    EffectiveConfigRequest,
    FetchLogsRequest,
    RemoteOperationAuditContext,
    normalize_remote_parameters,
    remote_result_from_command,
)

router = APIRouter()

_REMOTE_TIMEOUTS = {
    AGENT_FETCH_LOGS: 30,
    AGENT_DIAGNOSTICS: 30,
    AGENT_EFFECTIVE_CONFIG: 30,
    COLLECTOR_RESTART: 60,
}
_ACTIVE_COMMAND_STATUSES = {"pending", "executing"}
_RESTART_COOLDOWN = timedelta(seconds=60)


class RemoteOperationSubmission(BaseModel):
    command_id: str
    status: str
    action: str
    asset_id: str
    agent_id: str
    status_url: str


class RemoteOperationStatus(RemoteOperationSubmission):
    issued_at: str | None
    executed_at: str | None
    completed_at: str | None
    result: dict[str, Any] | None
    error: str | None


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


@router.post(
    "/agents/{asset_id}/operations/logs",
    response_model=RemoteOperationSubmission,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Fetch bounded recent edge-agent logs",
)
@remote_operation_rate_limit("12/minute")
async def fetch_agent_logs(
    request: Request,
    asset_id: UUID,
    payload: FetchLogsRequest,
    current_user: User = Depends(require_operator_or_admin),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await _submit_remote_operation(
        request=request,
        asset_id=asset_id,
        action_id=AGENT_FETCH_LOGS,
        parameters=payload.model_dump(mode="json", exclude_none=True),
        current_user=current_user,
        org_id=org_id,
        db=db,
    )


@router.post(
    "/agents/{asset_id}/operations/diagnostics",
    response_model=RemoteOperationSubmission,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run fixed edge-agent diagnostics",
)
@remote_operation_rate_limit("8/minute")
async def run_agent_diagnostics(
    request: Request,
    asset_id: UUID,
    payload: DiagnosticsRequest,
    current_user: User = Depends(require_operator_or_admin),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await _submit_remote_operation(
        request=request,
        asset_id=asset_id,
        action_id=AGENT_DIAGNOSTICS,
        parameters=payload.model_dump(mode="json"),
        current_user=current_user,
        org_id=org_id,
        db=db,
    )


@router.post(
    "/agents/{asset_id}/operations/effective-config",
    response_model=RemoteOperationSubmission,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Fetch the redacted effective edge-agent config",
)
@remote_operation_rate_limit("8/minute")
async def fetch_agent_effective_config(
    request: Request,
    asset_id: UUID,
    payload: EffectiveConfigRequest,
    current_user: User = Depends(require_operator_or_admin),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await _submit_remote_operation(
        request=request,
        asset_id=asset_id,
        action_id=AGENT_EFFECTIVE_CONFIG,
        parameters=payload.model_dump(mode="json"),
        current_user=current_user,
        org_id=org_id,
        db=db,
    )


@router.post(
    "/agents/{asset_id}/operations/restart-collector",
    response_model=RemoteOperationSubmission,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Restart exactly one collector on an edge agent",
)
@remote_operation_rate_limit("3/hour")
async def restart_agent_collector(
    request: Request,
    asset_id: UUID,
    payload: CollectorRestartRequest,
    current_user: User = Depends(require_operator_or_admin),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    asset = await _owned_agent_asset(
        db,
        org_id,
        asset_id,
        lock=True,
    )
    active = (
        await db.execute(
            select(Command.id).where(
                Command.organization_id == org_id,
                Command.asset_id == asset_id,
                Command.action_id == COLLECTOR_RESTART,
                Command.status.in_(_ACTIVE_COMMAND_STATUSES),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A restart is already active for this collector",
        )

    latest_restart = (
        await db.execute(
            select(Command.issued_at, Command.completed_at)
            .where(
                Command.organization_id == org_id,
                Command.asset_id == asset_id,
                Command.action_id == COLLECTOR_RESTART,
            )
            .order_by(Command.issued_at.desc())
            .limit(1)
        )
    ).one_or_none()
    now = datetime.now(timezone.utc)
    if latest_restart is not None:
        issued_at, completed_at = latest_restart
        cooldown_anchor = completed_at or issued_at
        if cooldown_anchor.tzinfo is None:
            cooldown_anchor = cooldown_anchor.replace(tzinfo=timezone.utc)
        retry_at = cooldown_anchor + _RESTART_COOLDOWN
        if retry_at > now:
            retry_after = max(1, int((retry_at - now).total_seconds()))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Collector restart is in cooldown",
                headers={"Retry-After": str(retry_after)},
            )

    parameters = payload.model_dump(mode="json")
    parameters["collector_asset_id"] = str(asset_id)
    return await _submit_remote_operation(
        request=request,
        asset_id=asset_id,
        action_id=COLLECTOR_RESTART,
        parameters=parameters,
        current_user=current_user,
        org_id=org_id,
        db=db,
        asset=asset,
    )


@router.get(
    "/agents/{asset_id}/operations/{command_id}",
    response_model=RemoteOperationStatus,
    summary="Get a durable remote-operation result",
)
@remote_operation_rate_limit("120/minute")
async def get_remote_operation_status(
    request: Request,
    asset_id: UUID,
    command_id: UUID,
    _current_user: User = Depends(require_operator_or_admin),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    asset = await _owned_agent_asset(
        db,
        org_id,
        asset_id,
        require_active=False,
        require_agent=False,
    )
    command = await command_executor.get_command_status(
        str(command_id),
        organization_id=str(org_id),
    )
    if (
        command is None
        or command.get("asset_id") != str(asset_id)
        or command.get("action") not in _REMOTE_TIMEOUTS
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Remote operation not found",
        )

    result = remote_result_from_command(command)
    stored_result = command.get("result")
    edge_ack = (
        stored_result.get("edge_ack")
        if isinstance(stored_result, dict)
        else None
    )
    reported_agent_id = (
        edge_ack.get("agent_id")
        if isinstance(edge_ack, dict)
        else None
    )
    error = None
    if isinstance(result, dict):
        error = result.get("message") if command["status"] != "completed" else None
    elif command["status"] == "timeout":
        error = "The edge agent did not acknowledge the operation in time"
    elif command["status"] in {"failed", "cancelled"}:
        error = "The remote operation could not be completed"

    return {
        "command_id": command["command_id"],
        "status": command["status"],
        "action": command["action"],
        "asset_id": str(asset_id),
        "agent_id": str(reported_agent_id or asset.agent_id or "unknown"),
        "status_url": _status_url(asset_id, command_id),
        "issued_at": command.get("issued_at"),
        "executed_at": command.get("executed_at"),
        "completed_at": command.get("completed_at"),
        "result": result,
        "error": error,
    }


async def _submit_remote_operation(
    *,
    request: Request,
    asset_id: UUID,
    action_id: str,
    parameters: dict[str, Any],
    current_user: User,
    org_id: UUID,
    db: AsyncSession,
    asset: Asset | None = None,
) -> dict[str, str]:
    asset = asset or await _owned_agent_asset(db, org_id, asset_id)
    normalized = normalize_remote_parameters(action_id, parameters)
    command_id = await command_executor.submit_command(
        asset_id=str(asset.id),
        command_type="system",
        action_id=action_id,
        parameters=normalized,
        issued_by=str(current_user.id),
        organization_id=str(org_id),
        timeout_seconds=_REMOTE_TIMEOUTS[action_id],
        remote_audit=RemoteOperationAuditContext(
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            target_agent_id=str(asset.agent_id),
        ),
        db_session=db,
    )
    return {
        "command_id": command_id,
        "status": "pending",
        "action": action_id,
        "asset_id": str(asset.id),
        "agent_id": str(asset.agent_id),
        "status_url": _status_url(asset.id, UUID(command_id)),
    }


async def _owned_agent_asset(
    db: AsyncSession,
    org_id: UUID,
    asset_id: UUID,
    *,
    lock: bool = False,
    require_active: bool = True,
    require_agent: bool = True,
) -> Asset:
    query = select(Asset).where(
        Asset.id == asset_id,
        Asset.organization_id == org_id,
    )
    if require_active:
        query = query.where(Asset.is_active.is_(True))
    if lock:
        query = query.with_for_update()
    asset = (await db.execute(query)).scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )
    if require_agent and not asset.agent_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Asset is not assigned to a reporting edge agent",
        )
    return asset


def _status_url(asset_id: UUID, command_id: UUID) -> str:
    return f"/api/v1/fleet/agents/{asset_id}/operations/{command_id}"
