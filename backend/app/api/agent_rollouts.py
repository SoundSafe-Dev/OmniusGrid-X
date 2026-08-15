"""Fleet OTA rollout registry API."""


import math
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.responses import conflict_response
from app.api.auth import get_current_active_user
from app.workers.health_server import OTA_ROLLOUT_FAILURES
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import (
    AgentRelease,
    AgentRollout,
    AgentRolloutEvent,
    AgentRolloutTarget,
    FleetTargetPreview,
    MaintenanceWindow,
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
from app.services.maintenance_windows import (
    MaintenanceWindowValidationError,
    effective_scope_label,
    evaluate_rollout_groups,
    utc_datetime,
)

router = APIRouter()
logger = structlog.get_logger()

PAUSABLE_ROLLOUT_STATUSES = frozenset({"pending", "running", "paused"})
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
    scheduled_start_at: datetime | None = None
    enforce_maintenance_windows: bool = False


class AgentRolloutTargetResponse(BaseModel):
    id: UUID
    asset_id: UUID
    agent_id: str | None = None
    route_asset_id: UUID | None = None
    site_id: UUID | None = None
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
    scheduled_start_at: datetime | None = None
    enforce_maintenance_windows: bool = False
    pause_reason: str | None = None
    next_eligible_at: datetime | None = None
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
        site_id=target.site_id,
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
        scheduled_start_at=rollout.scheduled_start_at,
        enforce_maintenance_windows=bool(
            rollout.enforce_maintenance_windows
        ),
        pause_reason=rollout.pause_reason,
        next_eligible_at=rollout.next_eligible_at,
        created_by=rollout.created_by,
        created_at=rollout.created_at,
        updated_at=rollout.updated_at,
        targets=[_target_response(target) for target in targets],
        events=[_event_response(event) for event in events],
    )


async def _get_rollout(
    rollout_id: UUID | str,
    org_id: UUID | str,
    db: AsyncSession,
) -> AgentRollout:
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
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if rollout is None:
        raise HTTPException(status_code=404, detail="Agent rollout not found")
    return rollout


async def _response_before_commit(
    rollout_id: UUID | str,
    org_id: UUID | str,
    db: AsyncSession,
) -> AgentRolloutResponse:
    """Materialize the response while the tenant-bound connection is active."""

    await db.flush()
    return _rollout_response(await _get_rollout(rollout_id, org_id, db))


async def _lock_rollout(
    rollout_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> AgentRollout:
    rollout = (
        await db.execute(
            select(AgentRollout)
            .options(selectinload(AgentRollout.targets))
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
        asset_sites = []
        for asset in group.get("assets", []):
            asset_sites.append(
                {
                    "asset_id": str(asset.get("asset_id")),
                    "site_id": (
                        str(asset.get("site_id"))
                        if asset.get("site_id") is not None
                        else None
                    ),
                }
            )
        signature.append(
            {
                "agent_key": group.get("agent_key"),
                "agent_id": group.get("agent_id"),
                "route_asset_id": str(group.get("route_asset_id")),
                "asset_ids": [str(asset_id) for asset_id in group.get("asset_ids", [])],
                "asset_sites": sorted(
                    asset_sites,
                    key=lambda item: item["asset_id"],
                ),
            }
        )
    return signature


def _agent_group_site_map(
    agent_group: dict,
    asset_ids: list[UUID],
) -> dict[UUID, UUID | None]:
    raw_assets = agent_group.get("assets")
    if not isinstance(raw_assets, list):
        raise HTTPException(
            status_code=409,
            detail="Target preview is missing its site snapshot",
        )
    site_map: dict[UUID, UUID | None] = {}
    try:
        for raw_asset in raw_assets:
            asset_id = UUID(str(raw_asset["asset_id"]))
            raw_site_id = raw_asset.get("site_id")
            site_map[asset_id] = (
                UUID(str(raw_site_id)) if raw_site_id is not None else None
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Target preview site snapshot is invalid",
        ) from exc
    if set(site_map) != set(asset_ids):
        raise HTTPException(
            status_code=409,
            detail="Target preview site snapshot is inconsistent",
        )
    return site_map


def _preview_window_groups(agent_groups: list[dict]) -> dict[str, set[UUID | None]]:
    groups: dict[str, set[UUID | None]] = {}
    for agent_group in agent_groups:
        try:
            asset_ids = [
                UUID(str(asset_id))
                for asset_id in agent_group["asset_ids"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="Target preview snapshot is invalid",
            ) from exc
        site_map = _agent_group_site_map(agent_group, asset_ids)
        group_key = str(
            agent_group.get("agent_key")
            or agent_group.get("agent_id")
            or agent_group.get("route_asset_id")
        )
        groups[group_key] = set(site_map.values()) or {None}
    return groups


def _target_group_key(target: AgentRolloutTarget) -> str:
    if target.agent_id:
        return f"agent:{target.agent_id}"
    return f"asset:{target.route_asset_id or target.asset_id}"


def _target_window_groups(
    targets: list[AgentRolloutTarget],
    *,
    statuses: frozenset[str] | None = None,
) -> dict[str, set[UUID | None]]:
    groups: dict[str, set[UUID | None]] = {}
    for target in targets:
        if statuses is not None and target.status not in statuses:
            continue
        groups.setdefault(_target_group_key(target), set()).add(target.site_id)
    return groups


async def _enabled_windows(
    db: AsyncSession,
    org_id: UUID,
) -> list[MaintenanceWindow]:
    return list(
        (
            await db.execute(
                select(MaintenanceWindow).where(
                    MaintenanceWindow.organization_id == org_id,
                    MaintenanceWindow.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )


def _window_contract_error(window_eligibility) -> HTTPException | None:
    if window_eligibility.missing_groups:
        descriptions = []
        for group in window_eligibility.missing_groups[:5]:
            scopes = ", ".join(
                effective_scope_label(site_id)
                for site_id in group.eligibility.missing_site_ids
            )
            descriptions.append(f"{group.group_key}: {scopes}")
        return HTTPException(
            status_code=422,
            detail=(
                "Maintenance-window enforcement requires an applicable "
                "organization or site window for every target group. Missing: "
                + "; ".join(descriptions)
            ),
        )
    if window_eligibility.no_opening_groups:
        groups = ", ".join(
            group.group_key
            for group in window_eligibility.no_opening_groups[:5]
        )
        return HTTPException(
            status_code=422,
            detail=(
                "No shared maintenance-window opening exists in the next "
                f"15 days for target group(s): {groups}"
            ),
        )
    return None


@router.post("/rollouts", response_model=AgentRolloutResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)], responses={**conflict_response})
@rate_limit("30/hour")
async def create_rollout(
    request: Request,
    payload: AgentRolloutCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    scheduled_start_at = None
    if payload.scheduled_start_at is not None:
        try:
            scheduled_start_at = utc_datetime(payload.scheduled_start_at)
        except MaintenanceWindowValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
    # User IDs use the repo's cross-dialect UUIDString (read as str), while
    # preview.created_by is a native UUID column on PostgreSQL.
    if str(preview.created_by) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Target preview not found")
    if str(preview.release_id) != str(release.id):
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

    prepared_groups: list[
        tuple[dict, UUID, list[UUID], dict[UUID, UUID | None]]
    ] = []
    for agent_group in agent_groups:
        try:
            route_asset_id = UUID(str(agent_group["route_asset_id"]))
            asset_ids = [
                UUID(str(asset_id))
                for asset_id in agent_group["asset_ids"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="Target preview snapshot is invalid",
            ) from exc
        prepared_groups.append(
            (
                agent_group,
                route_asset_id,
                asset_ids,
                _agent_group_site_map(agent_group, asset_ids),
            )
        )

    now = _utcnow()
    next_eligible_at = (
        scheduled_start_at
        if scheduled_start_at is not None and scheduled_start_at > now
        else None
    )
    if payload.enforce_maintenance_windows:
        reference = max(now, scheduled_start_at or now)
        try:
            window_eligibility = evaluate_rollout_groups(
                await _enabled_windows(db, org_id),
                _preview_window_groups(agent_groups),
                at=reference,
            )
        except MaintenanceWindowValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        contract_error = _window_contract_error(window_eligibility)
        if contract_error is not None:
            raise contract_error
        next_eligible_at = window_eligibility.next_eligible_at

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
        scheduled_start_at=scheduled_start_at,
        enforce_maintenance_windows=payload.enforce_maintenance_windows,
        pause_reason=None,
        next_eligible_at=next_eligible_at,
    )
    db.add(rollout)
    await db.flush()
    target_count = 0
    for position, (
        agent_group,
        route_asset_id,
        asset_ids,
        site_map,
    ) in enumerate(prepared_groups):
        wave_index = _wave_for_position(position, len(agent_groups), payload.strategy)
        for asset_id in asset_ids:
            db.add(
                AgentRolloutTarget(
                    rollout_id=rollout.id,
                    organization_id=org_id,
                    asset_id=asset_id,
                    agent_id=agent_group.get("agent_id"),
                    route_asset_id=route_asset_id,
                    site_id=site_map[asset_id],
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
                "scheduled_start_at": (
                    scheduled_start_at.isoformat()
                    if scheduled_start_at is not None
                    else None
                ),
                "enforce_maintenance_windows": (
                    payload.enforce_maintenance_windows
                ),
                "next_eligible_at": (
                    next_eligible_at.isoformat()
                    if next_eligible_at is not None
                    else None
                ),
            },
        )
    )
    response = await _response_before_commit(rollout.id, org_id, db)
    await db.commit()
    return response


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
    if rollout.status == "paused" and rollout.pause_reason != "maintenance_window":
        raise HTTPException(
            status_code=400,
            detail="Rollout is already manually paused",
        )
    now = _utcnow()
    previous_reason = rollout.pause_reason
    rollout.status = "paused"
    rollout.pause_reason = "manual"
    rollout.next_eligible_at = None
    rollout.updated_at = now
    db.add(
        AgentRolloutEvent(
            rollout_id=rollout.id,
            organization_id=org_id,
            event_type="paused",
            detail={
                "by": str(current_user.id),
                "reason": "manual",
                "previous_reason": previous_reason,
            },
        )
    )
    response = await _response_before_commit(rollout_id, org_id, db)
    await db.commit()
    return response


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
    previous_reason = rollout.pause_reason
    scheduled_start_at = rollout.scheduled_start_at
    if scheduled_start_at is not None:
        scheduled_start_at = (
            scheduled_start_at.replace(tzinfo=timezone.utc)
            if scheduled_start_at.tzinfo is None
            else scheduled_start_at.astimezone(timezone.utc)
        )

    event_type = "resumed"
    detail: dict[str, Any] = {
        "by": str(current_user.id),
        "previous_reason": previous_reason,
    }
    if scheduled_start_at is not None and scheduled_start_at > now:
        rollout.status = "pending"
        rollout.pause_reason = None
        rollout.next_eligible_at = scheduled_start_at
        detail["status"] = "pending"
        detail["scheduled_start_at"] = scheduled_start_at.isoformat()
    elif rollout.enforce_maintenance_windows:
        groups = _target_window_groups(
            list(rollout.targets or []),
            statuses=UNFINISHED_TARGET_STATUSES,
        )
        if groups:
            try:
                eligibility = evaluate_rollout_groups(
                    await _enabled_windows(db, org_id),
                    groups,
                    at=now,
                )
            except MaintenanceWindowValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        else:
            eligibility = None
        if eligibility is not None and not eligibility.eligible_group_keys:
            rollout.status = "paused"
            rollout.pause_reason = "maintenance_window"
            rollout.next_eligible_at = eligibility.next_eligible_at
            event_type = "resume_deferred"
            detail.update(
                {
                    "status": "paused",
                    "reason": "maintenance_window",
                    "next_eligible_at": (
                        eligibility.next_eligible_at.isoformat()
                        if eligibility.next_eligible_at is not None
                        else None
                    ),
                }
            )
        else:
            rollout.status = "running"
            rollout.pause_reason = None
            rollout.next_eligible_at = None
            detail["status"] = "running"
    else:
        rollout.status = "running"
        rollout.pause_reason = None
        rollout.next_eligible_at = None
        detail["status"] = "running"
    rollout.updated_at = now
    db.add(
        AgentRolloutEvent(
            rollout_id=rollout.id,
            organization_id=org_id,
            event_type=event_type,
            detail=detail,
        )
    )
    response = await _response_before_commit(rollout_id, org_id, db)
    await db.commit()
    return response


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
    rollout.pause_reason = None
    rollout.next_eligible_at = None
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
    response = await _response_before_commit(rollout_id, org_id, db)
    await db.commit()

    for command_id in command_ids:
        try:
            await command_executor.cancel_command(
                command_id,
                cancelled_by=str(current_user.id),
                organization_id=str(org_id),
            )
        except Exception as exc:  # noqa: BLE001
            # Counted. Cancelling a rollout that leaves live commands behind is the one
            # outcome an operator must not learn about from a log file — the fleet keeps
            # executing an instruction the console says was cancelled.
            OTA_ROLLOUT_FAILURES.labels(stage="command_cancel").inc()
            logger.error(
                "ota_rollout_command_cancel_failed",
                rollout_id=str(rollout_id),
                command_id=command_id,
                error=str(exc),
            )

    return response
