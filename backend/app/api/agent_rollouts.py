"""Fleet OTA rollout registry API."""


import math
from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import (
    AgentRelease,
    AgentRollout,
    AgentRolloutEvent,
    AgentRolloutTarget,
    FleetTargetPreview,
    User,
)
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from app.services.command_executor import command_executor
from app.services.fleet_targeting import (
    TargetingValidationError,
    fleet_target_resolver,
    normalize_selector,
)

router = APIRouter()
logger = structlog.get_logger()

PAUSABLE_ROLLOUT_STATUSES = frozenset({"pending", "running"})
RESUMABLE_ROLLOUT_STATUSES = frozenset({"paused"})
CANCELLABLE_ROLLOUT_STATUSES = frozenset({"pending", "running", "paused"})
UNFINISHED_TARGET_STATUSES = frozenset({"pending", "updating"})
CANCELLED_TARGET_REASON = "Rollout cancelled by administrator"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentRolloutCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    release_id: UUID
    target_selector: dict = Field(default_factory=dict)
    preview_id: UUID
    membership_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    strategy: dict = Field(default_factory=dict)


class AgentRolloutTargetResponse(BaseModel):
    id: UUID
    asset_id: UUID
    agent_id: str | None = None
    route_asset_id: UUID | None = None
    wave_index: int
    status: str
    current_version: str | None
    attempted_version: str | None = None
    running_version: str | None = None
    local_rollback: bool = False
    attempts: int
    command_id: str | None = None
    rollback_command_id: str | None = None
    failure_reason: str | None = None
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None
    last_event_at: datetime | None


class AgentRolloutEventResponse(BaseModel):
    id: UUID
    event_type: str
    asset_id: UUID | None
    detail: dict
    created_at: datetime | None


class AgentRolloutResponse(BaseModel):
    id: UUID
    organization_id: UUID
    release_id: UUID
    name: str
    target_selector: dict
    strategy: dict
    status: str
    target_preview_id: UUID | None = None
    target_membership_hash: str | None = None
    created_by: UUID | None
    created_at: datetime | None
    updated_at: datetime | None
    targets: list[AgentRolloutTargetResponse] = Field(default_factory=list)
    events: list[AgentRolloutEventResponse] = Field(default_factory=list)


def _target_response(target: AgentRolloutTarget) -> AgentRolloutTargetResponse:
    return AgentRolloutTargetResponse(
        id=target.id,
        asset_id=target.asset_id,
        agent_id=target.agent_id,
        route_asset_id=target.route_asset_id,
        wave_index=target.wave_index,
        status=target.status,
        current_version=target.current_version,
        attempted_version=target.attempted_version,
        running_version=target.running_version,
        local_rollback=bool(target.local_rollback),
        attempts=target.attempts,
        command_id=target.command_id,
        rollback_command_id=target.rollback_command_id,
        failure_reason=target.failure_reason,
        dispatched_at=target.dispatched_at,
        completed_at=target.completed_at,
        last_event_at=target.last_event_at,
    )


def _event_response(event: AgentRolloutEvent) -> AgentRolloutEventResponse:
    return AgentRolloutEventResponse(
        id=event.id,
        event_type=event.event_type,
        asset_id=event.asset_id,
        detail=event.detail or {},
        created_at=event.created_at,
    )


def _rollout_response(rollout: AgentRollout) -> AgentRolloutResponse:
    targets = sorted(rollout.targets or [], key=lambda t: (t.wave_index, str(t.asset_id)))
    events = sorted(
        rollout.events or [],
        key=lambda e: e.created_at.isoformat() if e.created_at else "",
    )
    return AgentRolloutResponse(
        id=rollout.id,
        organization_id=rollout.organization_id,
        release_id=rollout.release_id,
        name=rollout.name,
        target_selector=rollout.target_selector or {},
        strategy=rollout.strategy or {},
        status=rollout.status,
        target_preview_id=rollout.target_preview_id,
        target_membership_hash=rollout.target_membership_hash,
        created_by=rollout.created_by,
        created_at=rollout.created_at,
        updated_at=rollout.updated_at,
        targets=[_target_response(target) for target in targets],
        events=[_event_response(event) for event in events],
    )


async def _get_rollout(rollout_id: UUID, org_id: UUID, db: AsyncSession) -> AgentRollout:
    rollout = (
        await db.execute(
            select(AgentRollout)
            .options(
                selectinload(AgentRollout.targets),
                selectinload(AgentRollout.events),
            )
            .where(
                AgentRollout.id == rollout_id,
                AgentRollout.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if rollout is None:
        raise HTTPException(status_code=404, detail="Agent rollout not found")
    return rollout


async def _lock_rollout(
    rollout_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> AgentRollout:
    rollout = (
        await db.execute(
            select(AgentRollout)
            .where(
                AgentRollout.id == rollout_id,
                AgentRollout.organization_id == org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if rollout is None:
        raise HTTPException(status_code=404, detail="Agent rollout not found")
    return rollout


def _require_rollout_status(
    rollout: AgentRollout,
    allowed_statuses: frozenset[str],
    action: str,
) -> None:
    if rollout.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Rollout in '{rollout.status}' state cannot be {action}",
        )


def _wave_for_position(position: int, total: int, strategy: dict) -> int:
    wave_size = strategy.get("wave_size")
    if isinstance(wave_size, int) and wave_size > 0:
        return position // wave_size

    canary_percentage = strategy.get("canary_percentage")
    if isinstance(canary_percentage, (int, float)) and 0 < canary_percentage < 100:
        canary_size = max(1, math.ceil(total * (canary_percentage / 100)))
        return 0 if position < canary_size else 1

    return 0


def _agent_group_signature(groups: list[dict]) -> list[dict]:
    signature = []
    for group in groups:
        signature.append(
            {
                "agent_key": group.get("agent_key"),
                "agent_id": group.get("agent_id"),
                "route_asset_id": str(group.get("route_asset_id")),
                "asset_ids": [str(asset_id) for asset_id in group.get("asset_ids", [])],
            }
        )
    return signature


@router.post("/rollouts", response_model=AgentRolloutResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
@rate_limit("30/hour")
async def create_rollout(
    request: Request,
    payload: AgentRolloutCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    release = (
        await db.execute(
            select(AgentRelease).where(
                AgentRelease.id == payload.release_id,
                AgentRelease.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if release is None:
        raise HTTPException(status_code=404, detail="Agent release not found")
    if release.status != "published":
        raise HTTPException(status_code=400, detail="Rollouts require a published release")

    preview = (
        await db.execute(
            select(FleetTargetPreview)
            .where(
                FleetTargetPreview.id == payload.preview_id,
                FleetTargetPreview.organization_id == org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if preview is None:
        raise HTTPException(status_code=404, detail="Target preview not found")
    if preview.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="Target preview not found")
    if preview.release_id != release.id:
        raise HTTPException(
            status_code=409,
            detail="Target preview was created for a different release",
        )
    expires_at = preview.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= _utcnow():
        raise HTTPException(status_code=409, detail="Target preview has expired")
    if payload.membership_hash != preview.membership_hash:
        raise HTTPException(status_code=409, detail="Target preview hash does not match")
    if payload.target_selector:
        try:
            submitted_selector = normalize_selector(payload.target_selector)
        except TargetingValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if submitted_selector != preview.selector:
            raise HTTPException(
                status_code=409,
                detail="Target selector changed after preview",
            )
    existing_rollout = (
        await db.execute(
            select(AgentRollout.id).where(
                AgentRollout.target_preview_id == preview.id,
                AgentRollout.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if existing_rollout is not None:
        raise HTTPException(status_code=409, detail="Target preview was already used")
    try:
        current_resolution = await fleet_target_resolver.resolve(
            selector=preview.selector,
            organization_id=org_id,
            release=release,
            db=db,
        )
    except TargetingValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Target preview is stale: {exc}",
        ) from exc
    if current_resolution.membership_hash != preview.membership_hash:
        raise HTTPException(
            status_code=409,
            detail="Target membership changed after preview; create a new preview",
        )
    if current_resolution.asset_ids != list(preview.ordered_asset_ids or []):
        raise HTTPException(
            status_code=409,
            detail="Target preview asset snapshot is inconsistent",
        )
    if _agent_group_signature(current_resolution.agents) != _agent_group_signature(
        list(preview.resolved_agents or [])
    ):
        raise HTTPException(
            status_code=409,
            detail="Target preview agent snapshot is inconsistent",
        )
    selector = dict(preview.selector)
    membership_hash = preview.membership_hash
    agent_groups = list(preview.resolved_agents or [])

    if not agent_groups:
        raise HTTPException(status_code=422, detail="No eligible agents matched selector")

    rollout = AgentRollout(
        organization_id=org_id,
        release_id=release.id,
        name=payload.name,
        target_selector=selector,
        strategy=payload.strategy,
        status="pending",
        created_by=current_user.id,
        target_preview_id=preview.id,
        target_membership_hash=membership_hash,
    )
    db.add(rollout)
    await db.flush()
    target_count = 0
    for position, agent_group in enumerate(agent_groups):
        wave_index = _wave_for_position(position, len(agent_groups), payload.strategy)
        try:
            route_asset_id = UUID(str(agent_group["route_asset_id"]))
            asset_ids = [UUID(str(asset_id)) for asset_id in agent_group["asset_ids"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="Target preview snapshot is invalid") from exc
        for asset_id in asset_ids:
            db.add(
                AgentRolloutTarget(
                    rollout_id=rollout.id,
                    organization_id=org_id,
                    asset_id=asset_id,
                    agent_id=agent_group.get("agent_id"),
                    route_asset_id=route_asset_id,
                    wave_index=wave_index,
                    status="pending",
                )
            )
            target_count += 1
    db.add(
        AgentRolloutEvent(
            rollout_id=rollout.id,
            organization_id=org_id,
            event_type="created",
            detail={
                "target_count": target_count,
                "agent_count": len(agent_groups),
                "release_id": str(release.id),
                "membership_hash": membership_hash,
                "preview_id": str(preview.id),
            },
        )
    )
    await db.commit()
    return _rollout_response(await _get_rollout(rollout.id, org_id, db))


@router.get("/rollouts", response_model=list[AgentRolloutResponse])
@rate_limit("100/minute")
async def list_rollouts(
    request: Request,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rollouts = (
        await db.execute(
            select(AgentRollout)
            .options(
                selectinload(AgentRollout.targets),
                selectinload(AgentRollout.events),
            )
            .where(AgentRollout.organization_id == org_id)
            .order_by(AgentRollout.created_at.desc())
        )
    ).scalars().all()
    return [_rollout_response(rollout) for rollout in rollouts]


@router.get("/rollouts/{rollout_id}", response_model=AgentRolloutResponse)
@rate_limit("100/minute")
async def get_rollout(
    request: Request,
    rollout_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    return _rollout_response(await _get_rollout(rollout_id, org_id, db))


@router.post("/rollouts/{rollout_id}/pause", response_model=AgentRolloutResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/hour")
async def pause_rollout(
    request: Request,
    rollout_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rollout = await _lock_rollout(rollout_id, org_id, db)
    _require_rollout_status(rollout, PAUSABLE_ROLLOUT_STATUSES, "paused")
    now = _utcnow()
    rollout.status = "paused"
    rollout.updated_at = now
    db.add(
        AgentRolloutEvent(
            rollout_id=rollout.id,
            organization_id=org_id,
            event_type="paused",
            detail={"by": str(current_user.id)},
        )
    )
    await db.commit()
    return _rollout_response(await _get_rollout(rollout_id, org_id, db))


@router.post("/rollouts/{rollout_id}/resume", response_model=AgentRolloutResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/hour")
async def resume_rollout(
    request: Request,
    rollout_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rollout = await _lock_rollout(rollout_id, org_id, db)
    _require_rollout_status(rollout, RESUMABLE_ROLLOUT_STATUSES, "resumed")
    now = _utcnow()
    rollout.status = "running"
    rollout.updated_at = now
    db.add(
        AgentRolloutEvent(
            rollout_id=rollout.id,
            organization_id=org_id,
            event_type="resumed",
            detail={"by": str(current_user.id)},
        )
    )
    await db.commit()
    return _rollout_response(await _get_rollout(rollout_id, org_id, db))


@router.post("/rollouts/{rollout_id}/cancel", response_model=AgentRolloutResponse, dependencies=[Depends(require_admin)])
@rate_limit("30/hour")
async def cancel_rollout(
    request: Request,
    rollout_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    rollout = await _lock_rollout(rollout_id, org_id, db)
    _require_rollout_status(rollout, CANCELLABLE_ROLLOUT_STATUSES, "cancelled")
    unfinished_targets = list(
        (
            await db.execute(
                select(AgentRolloutTarget)
                .where(
                    AgentRolloutTarget.rollout_id == rollout.id,
                    AgentRolloutTarget.organization_id == org_id,
                    AgentRolloutTarget.status.in_(UNFINISHED_TARGET_STATUSES),
                )
                .order_by(
                    AgentRolloutTarget.wave_index,
                    AgentRolloutTarget.asset_id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    now = _utcnow()
    command_ids = sorted(
        {target.command_id for target in unfinished_targets if target.command_id}
    )
    rollout.status = "cancelled"
    rollout.updated_at = now
    for target in unfinished_targets:
        target.status = "cancelled"
        target.completed_at = now
        target.last_event_at = now
        target.failure_reason = CANCELLED_TARGET_REASON
        db.add(
            AgentRolloutEvent(
                rollout_id=rollout.id,
                organization_id=org_id,
                event_type="device_cancelled",
                asset_id=target.asset_id,
                detail={
                    "command_id": target.command_id,
                    "reason": CANCELLED_TARGET_REASON,
                    "wave_index": target.wave_index,
                },
            )
        )
    db.add(
        AgentRolloutEvent(
            rollout_id=rollout.id,
            organization_id=org_id,
            event_type="cancelled",
            detail={
                "by": str(current_user.id),
                "target_count": len(unfinished_targets),
                "command_count": len(command_ids),
            },
        )
    )
    await db.commit()

    for command_id in command_ids:
        try:
            await command_executor.cancel_command(
                command_id,
                cancelled_by=str(current_user.id),
                organization_id=str(org_id),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ota_rollout_command_cancel_failed",
                rollout_id=str(rollout_id),
                command_id=command_id,
                error=str(exc),
            )

    return _rollout_response(await _get_rollout(rollout_id, org_id, db))
