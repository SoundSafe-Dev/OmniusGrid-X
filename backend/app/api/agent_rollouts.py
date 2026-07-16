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
    Asset,
    User,
)
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin
from app.services.command_executor import command_executor

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
    strategy: dict = Field(default_factory=dict)


class AgentRolloutTargetResponse(BaseModel):
    id: UUID
    asset_id: UUID
    wave_index: int
    status: str
    current_version: str | None
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
    created_by: UUID | None
    created_at: datetime | None
    updated_at: datetime | None
    targets: list[AgentRolloutTargetResponse] = Field(default_factory=list)
    events: list[AgentRolloutEventResponse] = Field(default_factory=list)


def _target_response(target: AgentRolloutTarget) -> AgentRolloutTargetResponse:
    return AgentRolloutTargetResponse(
        id=target.id,
        asset_id=target.asset_id,
        wave_index=target.wave_index,
        status=target.status,
        current_version=target.current_version,
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


async def _resolve_targets(
    selector: dict,
    org_id: UUID,
    db: AsyncSession,
) -> list[Asset]:
    if selector.get("all") is True:
        assets = (
            await db.execute(
                select(Asset).where(
                    Asset.organization_id == org_id,
                    Asset.is_active.is_(True),
                )
            )
        ).scalars().all()
    else:
        raw_asset_ids = selector.get("asset_ids") or []
        if not raw_asset_ids:
            raise HTTPException(
                status_code=400,
                detail="target_selector must include all=true or asset_ids",
            )
        asset_ids = [UUID(str(asset_id)) for asset_id in raw_asset_ids]
        assets = (
            await db.execute(
                select(Asset).where(
                    Asset.organization_id == org_id,
                    Asset.id.in_(asset_ids),
                    Asset.is_active.is_(True),
                )
            )
        ).scalars().all()
        if len(assets) != len(set(asset_ids)):
            raise HTTPException(
                status_code=404,
                detail="One or more target assets were not found",
            )

    if not assets:
        raise HTTPException(status_code=400, detail="No active target assets matched selector")
    return list(assets)


def _wave_for_position(position: int, total: int, strategy: dict) -> int:
    wave_size = strategy.get("wave_size")
    if isinstance(wave_size, int) and wave_size > 0:
        return position // wave_size

    canary_percentage = strategy.get("canary_percentage")
    if isinstance(canary_percentage, (int, float)) and 0 < canary_percentage < 100:
        canary_size = max(1, math.ceil(total * (canary_percentage / 100)))
        return 0 if position < canary_size else 1

    return 0


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

    assets = await _resolve_targets(payload.target_selector, org_id, db)
    rollout = AgentRollout(
        organization_id=org_id,
        release_id=release.id,
        name=payload.name,
        target_selector=payload.target_selector,
        strategy=payload.strategy,
        status="pending",
        created_by=current_user.id,
    )
    db.add(rollout)
    await db.flush()
    for position, asset in enumerate(assets):
        db.add(
            AgentRolloutTarget(
                rollout_id=rollout.id,
                organization_id=org_id,
                asset_id=asset.id,
                wave_index=_wave_for_position(position, len(assets), payload.strategy),
                status="pending",
            )
        )
    db.add(
        AgentRolloutEvent(
            rollout_id=rollout.id,
            organization_id=org_id,
            event_type="created",
            detail={"target_count": len(assets), "release_id": str(release.id)},
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
