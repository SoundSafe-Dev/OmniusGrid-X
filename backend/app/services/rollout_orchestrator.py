"""Durable OTA rollout orchestration and health-gated promotion."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    AgentRelease,
    AgentRollout,
    AgentRolloutEvent,
    AgentRolloutTarget,
    Asset,
    Organization,
)
from app.services.agent_release_storage import issue_release_bundle_url
from app.services.command_executor import command_executor

logger = structlog.get_logger()

COMMAND_SUCCESS_STATUSES = {"completed", "success", "succeeded"}
COMMAND_FAILURE_STATUSES = {"failed", "error", "rejected", "cancelled", "timeout"}
TERMINAL_TARGET_STATUSES = {"success", "failed", "rolled_back", "cancelled", "skipped"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class RolloutOrchestrator:
    """Poll rollout rows, dispatch waves, and gate promotion on command + heartbeat health."""

    def __init__(self, *, command_client: Any = None) -> None:
        self.command_client = command_client or command_executor
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if not settings.OTA_ROLLOUT_DISPATCH_ENABLED or self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("ota_rollout_orchestrator_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ota_rollout_orchestrator_stopped")

    async def _run(self) -> None:
        while self._running:
            try:
                await self.dispatch_due_rollouts()
            except Exception as exc:  # noqa: BLE001
                logger.error("ota_rollout_dispatch_iteration_failed", error=str(exc))
            await asyncio.sleep(settings.OTA_ROLLOUT_DISPATCH_INTERVAL_SECONDS)

    async def _set_org(self, session, org_id: Any) -> None:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_id)},
        )

    async def dispatch_due_rollouts(self) -> None:
        async with AsyncSessionLocal() as session:
            org_ids = (await session.execute(select(Organization.id))).scalars().all()

        for org_id in org_ids:
            rollout_ids = await self._due_rollout_ids_for_org(org_id)
            for rollout_id in rollout_ids:
                await self.dispatch_rollout(rollout_id, org_id)

    async def _due_rollout_ids_for_org(self, org_id: UUID) -> list[UUID]:
        async with AsyncSessionLocal() as session:
            await self._set_org(session, org_id)
            return list(
                (
                    await session.execute(
                        select(AgentRollout.id)
                        .where(
                            AgentRollout.organization_id == org_id,
                            AgentRollout.status.in_(["pending", "running"]),
                        )
                        .order_by(AgentRollout.created_at)
                    )
                )
                .scalars()
                .all()
            )

    async def dispatch_rollout(self, rollout_id: UUID, org_id: UUID) -> None:
        async with AsyncSessionLocal() as session:
            await self._set_org(session, org_id)
            rollout = (
                await session.execute(
                    select(AgentRollout)
                    .options(
                        selectinload(AgentRollout.release),
                        selectinload(AgentRollout.targets),
                    )
                    .where(
                        AgentRollout.id == rollout_id,
                        AgentRollout.organization_id == org_id,
                        AgentRollout.status.in_(["pending", "running"]),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if rollout is None:
                return

            await self._process_rollout(session, rollout)
            await session.commit()

    async def _process_rollout(self, session, rollout: AgentRollout) -> None:
        if rollout.release is None or rollout.release.status != "published":
            await self._fail_rollout(
                session,
                rollout,
                reason="Rollout release is unavailable or not published",
                event_type="release_unavailable",
            )
            return

        if rollout.status == "pending":
            rollout.status = "running"
            rollout.updated_at = _utcnow()
            self._add_event(
                session,
                rollout,
                "started",
                detail={"release_id": str(rollout.release_id)},
            )

        await self._refresh_updating_targets(session, rollout)

        targets = self._sorted_targets(rollout)
        if all(target.status == "success" for target in targets):
            rollout.status = "completed"
            rollout.updated_at = _utcnow()
            self._add_event(session, rollout, "completed", detail={"target_count": len(targets)})
            return

        failed_wave = self._first_failed_wave_exceeding_threshold(targets, rollout.strategy or {})
        if failed_wave is not None:
            await self._halt_and_rollback_wave(
                session,
                rollout,
                failed_wave,
                reason="Wave failure threshold exceeded",
            )
            return

        if any(target.status == "updating" for target in targets):
            return

        pending_waves = [target.wave_index for target in targets if target.status == "pending"]
        if not pending_waves:
            await self._finalize_incomplete_rollout(session, rollout, targets)
            return

        next_wave = min(pending_waves)
        if not self._previous_waves_passed(targets, next_wave, rollout.strategy or {}):
            await self._halt_and_rollback_wave(
                session,
                rollout,
                max(0, next_wave - 1),
                reason="Previous wave did not meet health gate",
            )
            return

        await self._dispatch_wave(session, rollout, next_wave)

    async def _refresh_updating_targets(self, session, rollout: AgentRollout) -> None:
        for target in self._sorted_targets(rollout):
            if target.status != "updating":
                continue

            command_status = await self._get_command_status(target.command_id)
            status = str(command_status.get("status") or "").lower() if command_status else ""

            if status in COMMAND_FAILURE_STATUSES:
                await self._mark_target_failed(
                    session,
                    rollout,
                    target,
                    f"Command {target.command_id} finished with status {status}",
                )
                continue

            if status in COMMAND_SUCCESS_STATUSES:
                if await self._target_healthy(session, target, rollout.release, rollout.strategy or {}):
                    self._mark_target_success(session, rollout, target, command_status)
                    continue
                if self._target_timed_out(target, rollout.strategy or {}, "health"):
                    await self._mark_target_failed(
                        session,
                        rollout,
                        target,
                        "Health gate timed out after command completion",
                    )
                continue

            if self._target_timed_out(target, rollout.strategy or {}, "command"):
                await self._mark_target_failed(
                    session,
                    rollout,
                    target,
                    f"Command {target.command_id} timed out",
                )

    async def _dispatch_wave(self, session, rollout: AgentRollout, wave_index: int) -> None:
        wave_targets = [
            target
            for target in self._sorted_targets(rollout)
            if target.wave_index == wave_index and target.status == "pending"
        ]
        if not wave_targets:
            return

        self._add_event(
            session,
            rollout,
            "wave_started",
            detail={"wave_index": wave_index, "target_count": len(wave_targets)},
        )

        for target in wave_targets:
            command_id = await self._submit_update_command(
                session,
                rollout,
                target,
                rollout.release,
            )
            now = _utcnow()
            target.status = "updating"
            target.command_id = command_id
            target.attempts = (target.attempts or 0) + 1
            target.dispatched_at = now
            target.last_event_at = now
            target.failure_reason = None
            self._add_event(
                session,
                rollout,
                "device_update_dispatched",
                asset_id=target.asset_id,
                detail={
                    "wave_index": wave_index,
                    "command_id": command_id,
                    "release_id": str(rollout.release_id),
                },
            )

    async def _submit_update_command(
        self,
        session,
        rollout: AgentRollout,
        target: AgentRolloutTarget,
        release: AgentRelease,
        *,
        capture_current_version: bool = True,
    ) -> str:
        bundle_url, _ = issue_release_bundle_url(release.id, rollout.organization_id)
        if capture_current_version:
            target.current_version = await self._current_asset_version(session, target.asset_id)
        return await self.command_client.submit_command(
            asset_id=str(target.asset_id),
            command_type="system",
            action_id="agent_update",
            parameters={
                "release_id": str(release.id),
                "bundle_url": bundle_url,
                "checksum_sha256": release.checksum_sha256,
                "signature_ed25519": release.signature_ed25519,
                "target_version": release.version,
            },
            issued_by=str(rollout.created_by) if rollout.created_by else None,
            organization_id=str(rollout.organization_id),
            timeout_seconds=self._strategy_int(
                rollout.strategy or {},
                "command_timeout_seconds",
                settings.OTA_ROLLOUT_DEFAULT_COMMAND_TIMEOUT_SECONDS,
            ),
        )

    async def _get_command_status(self, command_id: str | None) -> dict[str, Any] | None:
        if not command_id:
            return None
        return await self.command_client.get_command_status(command_id)

    async def _target_healthy(
        self,
        session,
        target: AgentRolloutTarget,
        release: AgentRelease,
        strategy: dict,
    ) -> bool:
        asset = await session.get(Asset, target.asset_id)
        if asset is None:
            return False

        agent_version = getattr(asset, "agent_version", None)
        if agent_version != release.version:
            return False

        last_heartbeat = _aware(getattr(asset, "agent_last_heartbeat", None))
        if last_heartbeat is None:
            last_heartbeat = _aware(getattr(asset, "last_seen", None))
        if last_heartbeat is None:
            return False

        timeout = self._strategy_int(
            strategy,
            "health_timeout_seconds",
            settings.OTA_ROLLOUT_DEFAULT_HEALTH_TIMEOUT_SECONDS,
        )
        return _utcnow() - last_heartbeat <= timedelta(seconds=timeout)

    async def _mark_target_failed(
        self,
        session,
        rollout: AgentRollout,
        target: AgentRolloutTarget,
        reason: str,
    ) -> None:
        now = _utcnow()
        target.status = "failed"
        target.failure_reason = reason
        target.completed_at = now
        target.last_event_at = now
        self._add_event(
            session,
            rollout,
            "device_failed",
            asset_id=target.asset_id,
            detail={
                "command_id": target.command_id,
                "reason": reason,
                "wave_index": target.wave_index,
            },
        )

    def _mark_target_success(
        self,
        session,
        rollout: AgentRollout,
        target: AgentRolloutTarget,
        command_status: dict[str, Any] | None,
    ) -> None:
        now = _utcnow()
        target.status = "success"
        target.completed_at = now
        target.last_event_at = now
        target.failure_reason = None
        self._add_event(
            session,
            rollout,
            "device_updated",
            asset_id=target.asset_id,
            detail={
                "command_id": target.command_id,
                "result": (command_status or {}).get("result") or {},
                "wave_index": target.wave_index,
            },
        )

    async def _halt_and_rollback_wave(
        self,
        session,
        rollout: AgentRollout,
        wave_index: int,
        *,
        reason: str,
    ) -> None:
        rollout.status = "rolled_back"
        rollout.updated_at = _utcnow()
        self._add_event(
            session,
            rollout,
            "rolled_back",
            detail={"wave_index": wave_index, "reason": reason},
        )

        for target in self._sorted_targets(rollout):
            if target.status == "pending":
                target.status = "skipped"
                target.failure_reason = "Rollout halted before this target was updated"
                target.last_event_at = _utcnow()
                self._add_event(
                    session,
                    rollout,
                    "device_skipped",
                    asset_id=target.asset_id,
                    detail={"reason": target.failure_reason},
                )

        affected = [
            target
            for target in self._sorted_targets(rollout)
            if target.wave_index == wave_index and target.status in {"failed", "updating", "success"}
        ]
        await self._dispatch_rollbacks(session, rollout, affected)

    async def _dispatch_rollbacks(
        self,
        session,
        rollout: AgentRollout,
        targets: list[AgentRolloutTarget],
    ) -> None:
        rollback_release = await self._rollback_release(session, rollout)
        for target in targets:
            if target.rollback_command_id:
                continue
            if rollback_release is None:
                self._add_event(
                    session,
                    rollout,
                    "rollback_unavailable",
                    asset_id=target.asset_id,
                    detail={"current_version": target.current_version},
                )
                continue
            command_id = await self._submit_update_command(
                session,
                rollout,
                target,
                rollback_release,
                capture_current_version=False,
            )
            target.rollback_command_id = command_id
            target.status = "rolled_back"
            target.completed_at = _utcnow()
            target.last_event_at = _utcnow()
            self._add_event(
                session,
                rollout,
                "device_rollback_dispatched",
                asset_id=target.asset_id,
                detail={
                    "command_id": command_id,
                    "rollback_release_id": str(rollback_release.id),
                    "rollback_version": rollback_release.version,
                },
            )

    async def _rollback_release(self, session, rollout: AgentRollout) -> AgentRelease | None:
        raw_release_id = (rollout.strategy or {}).get("rollback_release_id")
        if not raw_release_id:
            return None
        try:
            release_id = UUID(str(raw_release_id))
        except ValueError:
            return None
        return (
            await session.execute(
                select(AgentRelease).where(
                    AgentRelease.id == release_id,
                    AgentRelease.organization_id == rollout.organization_id,
                    AgentRelease.status == "published",
                )
            )
        ).scalar_one_or_none()

    async def _fail_rollout(
        self,
        session,
        rollout: AgentRollout,
        *,
        reason: str,
        event_type: str = "failed",
    ) -> None:
        rollout.status = "failed"
        rollout.updated_at = _utcnow()
        self._add_event(session, rollout, event_type, detail={"reason": reason})

    async def _finalize_incomplete_rollout(
        self,
        session,
        rollout: AgentRollout,
        targets: list[AgentRolloutTarget],
    ) -> None:
        if any(target.status == "rolled_back" for target in targets):
            rollout.status = "rolled_back"
        elif any(target.status == "failed" for target in targets):
            rollout.status = "failed"
        else:
            rollout.status = "completed"
        rollout.updated_at = _utcnow()
        self._add_event(session, rollout, rollout.status, detail={"target_count": len(targets)})

    async def _current_asset_version(self, session, asset_id: UUID) -> str | None:
        asset = await session.get(Asset, asset_id)
        if asset is None:
            return None
        return getattr(asset, "agent_version", None)

    def _target_timed_out(self, target: AgentRolloutTarget, strategy: dict, phase: str) -> bool:
        started_at = _aware(target.dispatched_at)
        if started_at is None:
            return False
        key = "health_timeout_seconds" if phase == "health" else "command_timeout_seconds"
        default = (
            settings.OTA_ROLLOUT_DEFAULT_HEALTH_TIMEOUT_SECONDS
            if phase == "health"
            else settings.OTA_ROLLOUT_DEFAULT_COMMAND_TIMEOUT_SECONDS
        )
        timeout = self._strategy_int(strategy, key, default)
        return _utcnow() - started_at > timedelta(seconds=timeout)

    def _first_failed_wave_exceeding_threshold(
        self,
        targets: list[AgentRolloutTarget],
        strategy: dict,
    ) -> int | None:
        for wave_index in sorted({target.wave_index for target in targets}):
            wave = [target for target in targets if target.wave_index == wave_index]
            failed = [
                target
                for target in wave
                if target.status in {"failed", "rolled_back"}
            ]
            if self._failure_threshold_exceeded(len(failed), len(wave), strategy):
                return wave_index
        return None

    def _previous_waves_passed(
        self,
        targets: list[AgentRolloutTarget],
        next_wave: int,
        strategy: dict,
    ) -> bool:
        min_success_ratio = self._strategy_float(
            strategy,
            "min_success_ratio",
            settings.OTA_ROLLOUT_DEFAULT_MIN_SUCCESS_RATIO,
        )
        for wave_index in sorted({target.wave_index for target in targets if target.wave_index < next_wave}):
            wave = [target for target in targets if target.wave_index == wave_index]
            if any(target.status not in TERMINAL_TARGET_STATUSES for target in wave):
                return False
            success_ratio = len([target for target in wave if target.status == "success"]) / len(wave)
            failed_count = len([target for target in wave if target.status in {"failed", "rolled_back"}])
            if success_ratio < min_success_ratio:
                return False
            if self._failure_threshold_exceeded(failed_count, len(wave), strategy):
                return False
        return True

    def _failure_threshold_exceeded(self, failed_count: int, total: int, strategy: dict) -> bool:
        if total == 0 or failed_count == 0:
            return False
        ratio_threshold = strategy.get("max_failure_ratio")
        if isinstance(ratio_threshold, (int, float)):
            return failed_count / total > float(ratio_threshold)
        threshold = self._strategy_int(strategy, "failure_threshold", 1)
        if threshold <= 0:
            return failed_count > 0
        return failed_count >= threshold

    @staticmethod
    def _sorted_targets(rollout: AgentRollout) -> list[AgentRolloutTarget]:
        return sorted(rollout.targets or [], key=lambda item: (item.wave_index, str(item.asset_id)))

    @staticmethod
    def _strategy_int(strategy: dict, key: str, default: int) -> int:
        value = strategy.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _strategy_float(strategy: dict, key: str, default: float) -> float:
        value = strategy.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _add_event(
        self,
        session,
        rollout: AgentRollout,
        event_type: str,
        *,
        asset_id: UUID | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            AgentRolloutEvent(
                rollout_id=rollout.id,
                organization_id=rollout.organization_id,
                event_type=event_type,
                asset_id=asset_id,
                detail=detail or {},
            )
        )


rollout_orchestrator = RolloutOrchestrator()
