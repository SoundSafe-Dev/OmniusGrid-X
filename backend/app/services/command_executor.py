"""Durable command dispatch and acknowledgement processing."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Asset, Command, Organization
from app.services.remote_operations import (
    MAX_COMMAND_ACK_BYTES,
    RemoteOperationAuditContext,
    RemoteOperationContractError,
    add_remote_requested_audit,
    add_remote_terminal_audit,
    invalid_remote_ack,
    is_remote_operation,
    normalize_remote_ack,
)
from app.services.websocket_manager import websocket_manager

logger = structlog.get_logger()


class CommandStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


TERMINAL_STATUSES = {
    CommandStatus.COMPLETED.value,
    CommandStatus.FAILED.value,
    CommandStatus.CANCELLED.value,
    CommandStatus.TIMEOUT.value,
}


@dataclass
class CommandResult:
    """Result of publishing a command to the edge topic."""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value: Any) -> Optional[UUID]:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


class CommandExecutor:
    """Persist commands, publish claimed rows, and reconcile acks via the DB."""

    #: Shared across instances on purpose: the broker is one dependency, so one process
    #: should reach one verdict about it. A per-instance breaker would relearn that
    #: Redpanda is down separately for every executor constructed.
    _breaker = CircuitBreaker("redpanda:commands", failure_threshold=3)

    def __init__(self, *, session_factory=None) -> None:
        self._session_factory = session_factory
        self._running = False
        self._dispatch_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None
        self._ack_consumer_task: Optional[asyncio.Task] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._ack_consumer: Optional[AIOKafkaConsumer] = None
        #: Current reconnect delay, doubling to a cap while the broker is unreachable
        #: (FS-474). Set here rather than lazily so the loop cannot read it before the
        #: first failure has set it.
        self._ack_reconnect_delay: float = self._ACK_RECONNECT_INITIAL_SECONDS
        #: Consecutive failed iterations per background loop (FS-693).
        #:
        #: Each loop catches every exception and continues, which is correct — one bad
        #: command must not kill dispatch for the whole fleet. The consequence is that a
        #: loop failing on EVERY iteration runs forever, so `_dispatch_task.done()` is
        #: False and health reported `ok` while not one command was dispatched. The task
        #: is the mechanism; these counters are the work.
        self._loop_failures: dict[str, int] = {"dispatch": 0, "timeout": 0}
        self._timeout_seconds = 60
        self._max_retries = 3
        self._poll_interval_seconds = 1.0

    @property
    def _sessions(self):
        return self._session_factory or AsyncSessionLocal

    async def start(self) -> None:
        """Start durable dispatch, acknowledgement, and timeout loops."""
        if self._running:
            return

        logger.info("command_executor_starting")
        self._running = True
        await self._ensure_producer()
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        self._timeout_task = asyncio.create_task(self._timeout_loop())
        self._ack_consumer_task = asyncio.create_task(self._ack_consumer_loop())
        logger.info("command_executor_started")

    async def stop(self) -> None:
        """Stop command processing and broker clients."""
        if not self._running and not any(
            (self._dispatch_task, self._timeout_task, self._ack_consumer_task)
        ):
            return

        logger.info("command_executor_stopping")
        self._running = False
        tasks = (
            self._dispatch_task,
            self._timeout_task,
            self._ack_consumer_task,
        )
        for task in tasks:
            if task:
                task.cancel()
        for task in tasks:
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._dispatch_task = None
        self._timeout_task = None
        self._ack_consumer_task = None
        await self._reset_ack_consumer()
        await self._reset_producer()
        logger.info("command_executor_stopped")

    async def submit_command(
        self,
        asset_id: str,
        command_type: str,
        action_id: str,
        parameters: Dict[str, Any],
        issued_by: Optional[str] = None,
        organization_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        remote_audit: Optional[RemoteOperationAuditContext] = None,
        db_session: Optional[AsyncSession] = None,
    ) -> str:
        """Persist a command. A running executor replica will claim it."""
        command_id = uuid4()
        asset_uuid = _uuid(asset_id)
        organization_uuid = _uuid(organization_id)
        issuer_uuid = _uuid(issued_by) if issued_by else None
        timeout = timeout_seconds if timeout_seconds is not None else self._timeout_seconds

        if asset_uuid is None:
            raise ValueError("asset_id must be a UUID")
        if organization_uuid is None:
            raise ValueError("organization_id must be a UUID")
        if issued_by and issuer_uuid is None:
            raise ValueError("issued_by must be a UUID")
        if not command_type:
            raise ValueError("command_type is required")
        if not action_id:
            raise ValueError("action_id is required")
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")

        now = _utcnow()
        async def persist(session: AsyncSession) -> None:
            await self._set_org(session, organization_uuid)
            # THE ASSET AND THE ORG MUST AGREE (FS-736). This method took both as
            # arguments and never compared them, so a caller that had not checked wrote a
            # command naming one tenant's machine and belonging to another. Every route
            # that reaches here checks — `commands.py` looks the asset up and compares,
            # `fleet_agents.py` goes through `_owned_agent_asset` — but a kanban task's
            # `completion_actions.execute_command.asset_id` reached this unexamined, and
            # the caller-by-caller arrangement means the next entrance starts unguarded
            # too. The row was never DELIVERABLE — the edge agent drops a command whose
            # organization_id is not its own — but it was written, counted, and reported
            # to its submitter as executed.
            #
            # Checked here rather than only at the routes so the invariant belongs to the
            # command surface itself. `_set_org` has already bound the GUC, so this read
            # is under the same policy the write will be.
            owner = (
                await session.execute(
                    select(Asset.id).where(
                        Asset.id == asset_uuid,
                        Asset.organization_id == organization_uuid,
                    )
                )
            ).first()
            if owner is None:
                raise ValueError("asset_id does not belong to organization_id")
            command = Command(
                id=command_id,
                asset_id=asset_uuid,
                organization_id=organization_uuid,
                command_type=command_type,
                action_id=action_id,
                parameters=dict(parameters or {}),
                status=CommandStatus.PENDING.value,
                timeout_seconds=int(timeout),
                dispatch_attempts=0,
                next_dispatch_at=now,
                issued_by=issuer_uuid,
                issued_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(command)
            if remote_audit is not None:
                if not is_remote_operation(action_id):
                    raise ValueError(
                        "remote_audit is only valid for remote-operation commands"
                    )
                add_remote_requested_audit(session, command, remote_audit)
            await session.commit()

        if db_session is not None:
            await persist(db_session)
        else:
            async with self._sessions() as session:
                await persist(session)

        await self._broadcast_safely(
            str(organization_uuid),
            str(asset_uuid),
            str(command_id),
            CommandStatus.PENDING,
            action_id,
        )
        logger.info(
            "command_submitted",
            command_id=str(command_id),
            asset_id=str(asset_uuid),
            organization_id=str(organization_uuid),
            action=action_id,
        )
        return str(command_id)

    async def get_command_status(
        self,
        command_id: str,
        organization_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return command state, optionally scoped to a known tenant."""
        command_uuid = _uuid(command_id)
        if command_uuid is None:
            return None

        for org_id in await self._candidate_org_ids(organization_id):
            async with self._sessions() as session:
                await self._set_org(session, org_id)
                command = (
                    await session.execute(
                        select(Command).where(
                            Command.id == command_uuid,
                            Command.organization_id == org_id,
                        )
                    )
                ).scalar_one_or_none()
                if command is not None:
                    return self._command_status_payload(command)
        return None

    async def cancel_command(
        self,
        command_id: str,
        cancelled_by: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Atomically cancel a pending or executing command."""
        command_uuid = _uuid(command_id)
        if command_uuid is None:
            return False

        for org_id in await self._candidate_org_ids(organization_id):
            snapshot = None
            async with self._sessions() as session:
                await self._set_org(session, org_id)
                command = (
                    await session.execute(
                        select(Command)
                        .where(
                            Command.id == command_uuid,
                            Command.organization_id == org_id,
                            Command.status.in_(
                                [
                                    CommandStatus.PENDING.value,
                                    CommandStatus.EXECUTING.value,
                                ]
                            ),
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if command is None:
                    continue

                now = _utcnow()
                command.status = CommandStatus.CANCELLED.value
                command.completed_at = now
                command.updated_at = now
                command.error_message = "Command cancelled"
                command.result = {
                    "cancelled_by": cancelled_by,
                    "cancelled_at": now.isoformat(),
                }
                add_remote_terminal_audit(
                    session,
                    command,
                    status=CommandStatus.CANCELLED.value,
                    occurred_at=now,
                )
                snapshot = self._command_snapshot(command)
                await session.commit()

            await self._broadcast_safely(
                snapshot["organization_id"],
                snapshot["asset_id"],
                snapshot["command_id"],
                CommandStatus.CANCELLED,
                snapshot["action_id"],
                error="Command cancelled",
            )
            logger.info(
                "command_cancelled",
                command_id=str(command_uuid),
                cancelled_by=cancelled_by,
            )
            return True
        return False

    async def dispatch_pending(self, *, limit: int = 100) -> int:
        """Claim and publish ready DB rows across tenants."""
        if limit <= 0 or not await self._ensure_producer():
            return 0

        processed = 0
        for org_id in await self._organization_ids():
            while processed < limit:
                outcome = await self._dispatch_one_for_org(org_id)
                if outcome is None:
                    break
                processed += 1
                if outcome == "retry":
                    return processed
            if processed >= limit:
                break
        return processed

    async def handle_command_ack(self, ack_payload: Dict[str, Any]) -> bool:
        """Reconcile an edge ack against its DB row from any replica."""
        if not isinstance(ack_payload, dict):
            return False
        if len(self._payload_bytes(ack_payload)) > MAX_COMMAND_ACK_BYTES:
            logger.warning("command_ack_too_large")
            return False
        command_uuid = _uuid(ack_payload.get("command_id"))
        if command_uuid is None:
            logger.warning("command_ack_invalid_command_id")
            return False

        outcome = self._ack_outcome(ack_payload)
        if outcome is None:
            logger.warning(
                "command_ack_invalid_status",
                command_id=str(command_uuid),
                status=ack_payload.get("status"),
            )
            return False
        status, error = outcome

        organization_id = ack_payload.get("organization_id")
        for org_id in await self._candidate_org_ids(organization_id):
            snapshot = None
            duplicate = False
            async with self._sessions() as session:
                await self._set_org(session, org_id)
                command = (
                    await session.execute(
                        select(Command)
                        .where(
                            Command.id == command_uuid,
                            Command.organization_id == org_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if command is None:
                    continue

                ack_asset_id = ack_payload.get("asset_id")
                if ack_asset_id and str(command.asset_id) != str(ack_asset_id):
                    logger.warning(
                        "command_ack_asset_mismatch",
                        command_id=str(command_uuid),
                        expected_asset_id=str(command.asset_id),
                        received_asset_id=str(ack_asset_id),
                    )
                    return False

                corrective_rollback = self._is_corrective_self_rollback(
                    command,
                    status,
                    ack_payload,
                )
                if command.status in TERMINAL_STATUSES and not corrective_rollback:
                    duplicate = True
                elif (
                    not corrective_rollback
                    and command.status
                    not in {
                        CommandStatus.PENDING.value,
                        CommandStatus.EXECUTING.value,
                    }
                ):
                    return False
                else:
                    now = _utcnow()
                    stored_ack = ack_payload
                    if is_remote_operation(command.action_id):
                        try:
                            stored_ack, safe_error = normalize_remote_ack(
                                command.action_id,
                                ack_payload,
                                successful=status is CommandStatus.COMPLETED,
                            )
                            error = safe_error
                        except RemoteOperationContractError:
                            status = CommandStatus.FAILED
                            stored_ack, error = invalid_remote_ack(
                                command.action_id,
                                ack_payload,
                            )
                    command.status = status.value
                    command.completed_at = now
                    command.updated_at = now
                    command.error_message = error
                    command.result = {
                        "ack_received_at": now.isoformat(),
                        "edge_ack": stored_ack,
                        **({"error": error} if error else {}),
                    }
                    add_remote_terminal_audit(
                        session,
                        command,
                        status=status.value,
                        occurred_at=now,
                    )
                    snapshot = self._command_snapshot(command)
                    await session.commit()

            if duplicate:
                logger.info(
                    "command_ack_duplicate_terminal",
                    command_id=str(command_uuid),
                )
                return True

            await self._broadcast_safely(
                snapshot["organization_id"],
                snapshot["asset_id"],
                snapshot["command_id"],
                status,
                snapshot["action_id"],
                result=stored_ack if status is CommandStatus.COMPLETED else None,
                error=error,
            )
            logger.info(
                "command_ack_handled",
                command_id=str(command_uuid),
                status=status.value,
            )
            return True

        logger.warning("command_ack_for_unknown_command", command_id=str(command_uuid))
        return False

    async def expire_timed_out(self, *, limit: int = 100) -> int:
        """Mark commands whose durable acknowledgement deadline has passed."""
        if limit <= 0:
            return 0

        expired = 0
        now = _utcnow()
        for org_id in await self._organization_ids():
            if expired >= limit:
                break
            snapshots = []
            async with self._sessions() as session:
                await self._set_org(session, org_id)
                commands = (
                    await session.execute(
                        select(Command)
                        .where(
                            Command.organization_id == org_id,
                            Command.status == CommandStatus.EXECUTING.value,
                            Command.deadline_at.is_not(None),
                            Command.deadline_at <= now,
                        )
                        .order_by(Command.deadline_at)
                        .limit(limit - expired)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars().all()
                for command in commands:
                    command.status = CommandStatus.TIMEOUT.value
                    command.completed_at = now
                    command.updated_at = now
                    command.error_message = "Command acknowledgement timed out"
                    command.result = {"timeout_at": now.isoformat()}
                    add_remote_terminal_audit(
                        session,
                        command,
                        status=CommandStatus.TIMEOUT.value,
                        occurred_at=now,
                    )
                    snapshots.append(self._command_snapshot(command))
                if commands:
                    await session.commit()

            for snapshot in snapshots:
                await self._broadcast_safely(
                    snapshot["organization_id"],
                    snapshot["asset_id"],
                    snapshot["command_id"],
                    CommandStatus.TIMEOUT,
                    snapshot["action_id"],
                    error="Command acknowledgement timed out",
                )
                logger.warning("command_timeout", command_id=snapshot["command_id"])
            expired += len(snapshots)
        return expired

    async def get_pending_count(self, organization_id: Optional[str] = None) -> int:
        """Count non-terminal commands from the database."""
        total = 0
        for org_id in await self._candidate_org_ids(organization_id):
            async with self._sessions() as session:
                await self._set_org(session, org_id)
                total += int(
                    (
                        await session.execute(
                            select(func.count(Command.id)).where(
                                Command.organization_id == org_id,
                                Command.status.in_(
                                    [
                                        CommandStatus.PENDING.value,
                                        CommandStatus.EXECUTING.value,
                                    ]
                                ),
                            )
                        )
                    ).scalar_one()
                )
        return total

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                await self.dispatch_pending()
                self._loop_failures["dispatch"] = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._loop_failures["dispatch"] += 1
                logger.exception("command_dispatch_iteration_failed", error=str(exc))
            await asyncio.sleep(self._poll_interval_seconds)

    async def _timeout_loop(self) -> None:
        while self._running:
            try:
                await self.expire_timed_out()
                self._loop_failures["timeout"] = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._loop_failures["timeout"] += 1
                logger.exception("command_timeout_iteration_failed", error=str(exc))
            await asyncio.sleep(10)

    async def _dispatch_one_for_org(self, org_id: UUID) -> Optional[str]:
        now = _utcnow()
        snapshot = None
        failure = None
        terminal_failure = False

        async with self._sessions() as session:
            await self._set_org(session, org_id)
            command = (
                await session.execute(
                    select(Command)
                    .where(
                        Command.organization_id == org_id,
                        Command.status == CommandStatus.PENDING.value,
                        Command.next_dispatch_at <= now,
                    )
                    .order_by(Command.next_dispatch_at, Command.issued_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if command is None:
                return None

            command.dispatch_attempts = int(command.dispatch_attempts or 0) + 1
            command.updated_at = now
            publish_result = await self._send_to_edge_agent(
                command_id=str(command.id),
                asset_id=str(command.asset_id),
                organization_id=str(command.organization_id),
                action_id=command.action_id,
                parameters=dict(command.parameters or {}),
                timeout_seconds=command.timeout_seconds,
            )

            if publish_result.success:
                dispatched_at = _utcnow()
                command.status = CommandStatus.EXECUTING.value
                command.executed_at = dispatched_at
                command.dispatched_at = dispatched_at
                command.deadline_at = dispatched_at + timedelta(
                    seconds=command.timeout_seconds
                )
                command.last_dispatch_error = None
                command.error_message = None
                command.result = {
                    "dispatched_at": dispatched_at.isoformat(),
                    **(publish_result.data or {}),
                }
                snapshot = self._command_snapshot(command)
                await session.commit()
            else:
                failure = publish_result.message[:2000]
                command.last_dispatch_error = failure
                command.error_message = failure
                if command.dispatch_attempts >= self._max_retries:
                    terminal_failure = True
                    command.status = CommandStatus.FAILED.value
                    command.completed_at = now
                    command.result = {
                        "error": failure,
                        "failed_at": now.isoformat(),
                        "dispatch_attempts": command.dispatch_attempts,
                    }
                    add_remote_terminal_audit(
                        session,
                        command,
                        status=CommandStatus.FAILED.value,
                        occurred_at=now,
                    )
                    snapshot = self._command_snapshot(command)
                else:
                    command.status = CommandStatus.PENDING.value
                    command.next_dispatch_at = now + timedelta(
                        seconds=min(2 ** command.dispatch_attempts, 60)
                    )
                    command.result = {
                        "dispatch_error": failure,
                        "retry_at": command.next_dispatch_at.isoformat(),
                        "dispatch_attempts": command.dispatch_attempts,
                    }
                await session.commit()

        if publish_result.success:
            await self._broadcast_safely(
                snapshot["organization_id"],
                snapshot["asset_id"],
                snapshot["command_id"],
                CommandStatus.EXECUTING,
                snapshot["action_id"],
            )
            logger.info(
                "command_dispatched",
                command_id=snapshot["command_id"],
                asset_id=snapshot["asset_id"],
            )
            return "dispatched"

        await self._reset_producer()
        if terminal_failure:
            await self._broadcast_safely(
                snapshot["organization_id"],
                snapshot["asset_id"],
                snapshot["command_id"],
                CommandStatus.FAILED,
                snapshot["action_id"],
                error=failure,
            )
            logger.error(
                "command_dispatch_failed",
                command_id=snapshot["command_id"],
                error=failure,
            )
            return "failed"
        return "retry"

    async def _send_to_edge_agent(
        self,
        command_id: str,
        asset_id: str,
        organization_id: Optional[str],
        action_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: int,
    ) -> CommandResult:
        if self._producer is None:
            return CommandResult(
                success=False,
                message="Redpanda producer not available",
                error_code="PRODUCER_UNAVAILABLE",
            )

        command_message = {
            "schema_version": 1,
            "message_type": "command",
            "command_id": command_id,
            "asset_id": asset_id,
            "organization_id": organization_id,
            "action_id": action_id,
            "parameters": parameters,
            "timeout_seconds": timeout_seconds,
            "timestamp": _utcnow().isoformat(),
        }
        try:
            # FS-848. Every dispatch paid the broker's full `send_and_wait` timeout while
            # Redpanda was down, and command dispatch is called in a loop over targeted
            # assets — so one broker outage turned a fleet-wide command into N timeouts
            # back to back, each holding its worker. The breaker makes the second and
            # subsequent ones immediate; the OUTCOME is unchanged (`SEND_FAILED`), which
            # is what makes it safe to short-circuit.
            #
            # `edge_ingest` already had a hand-rolled equivalent (`_unavailable_until`);
            # this path had nothing, which is the asymmetry FS-846..848 was about.
            await self._breaker.call(
                lambda: self._producer.send_and_wait(
                    settings.REDPANDA_COMMAND_TOPIC,
                    command_message,
                    key=command_id.encode("utf-8"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "redpanda_send_failed",
                command_id=command_id,
                asset_id=asset_id,
                action=action_id,
                error=str(exc),
            )
            return CommandResult(
                success=False,
                message=f"Failed to send command: {exc}",
                error_code="SEND_FAILED",
            )

        return CommandResult(
            success=True,
            message="Command sent to edge agent via Redpanda",
            data={
                "sent_at": _utcnow().isoformat(),
                "topic": settings.REDPANDA_COMMAND_TOPIC,
                "ack_topic": settings.REDPANDA_COMMAND_ACK_TOPIC,
            },
        )

    #: Reconnect delays for the command-ack consumer (FS-474).
    #:
    #: Both exits from `_ack_consumer_loop` used to sleep a flat 5 seconds — the one where
    #: the consumer will not start, and the one where it errors mid-stream. A broker down
    #: for a day therefore drew ~17,000 connection attempts and the same number of error
    #: lines, at a rate that did not depend on anything.
    #:
    #: This is the edge agent's FS-472 in the cloud. The agent has a `ReconnectPolicy` for
    #: it; the backend has exactly one loop with this shape, so the values live here rather
    #: than in a framework built for a single caller. **If a second loop needs them, that
    #: is the moment to factor — not before.**
    _ACK_RECONNECT_INITIAL_SECONDS = 1.0
    _ACK_RECONNECT_CAP_SECONDS = 60.0

    def _next_ack_reconnect_delay(self) -> float:
        """Current delay, then double it for next time (capped)."""
        delay = self._ack_reconnect_delay
        self._ack_reconnect_delay = min(
            delay * 2, self._ACK_RECONNECT_CAP_SECONDS
        )
        return delay

    def _reset_ack_reconnect_delay(self) -> None:
        """Called when the broker accepts a connection: the next outage starts low."""
        self._ack_reconnect_delay = self._ACK_RECONNECT_INITIAL_SECONDS

    async def _ack_consumer_loop(self) -> None:
        while self._running:
            if not await self._ensure_ack_consumer():
                await asyncio.sleep(self._next_ack_reconnect_delay())
                continue
            # The broker accepted a connection, so an outage after this point starts its
            # own curve rather than inheriting the last one's.
            self._reset_ack_reconnect_delay()

            try:
                async for message in self._ack_consumer:
                    if not self._running:
                        return
                    try:
                        payload, error = self._decode_json_object(message.value)
                        if error:
                            await self._publish_dead_letter(
                                message.value,
                                reason=error,
                                source_topic=message.topic,
                                partition=message.partition,
                                offset=message.offset,
                                consumer="backend-command-ack",
                            )
                        elif not await self.handle_command_ack(payload):
                            await self._publish_dead_letter(
                                payload,
                                reason="unmatched_or_invalid_ack",
                                source_topic=message.topic,
                                partition=message.partition,
                                offset=message.offset,
                                consumer="backend-command-ack",
                            )
                        await self._ack_consumer.commit(
                            {
                                TopicPartition(message.topic, message.partition):
                                    message.offset + 1
                            }
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "command_ack_processing_failed",
                            error=str(exc),
                            topic=message.topic,
                            partition=message.partition,
                            offset=message.offset,
                        )
                        self._ack_consumer.seek(
                            TopicPartition(message.topic, message.partition),
                            message.offset,
                        )
                        await asyncio.sleep(1)
                        break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("command_ack_consumer_error", error=str(exc))
                await self._reset_ack_consumer()
                await asyncio.sleep(self._next_ack_reconnect_delay())

    async def _ensure_producer(self) -> bool:
        if self._producer is not None:
            return True
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.REDPANDA_URL,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            acks="all",
            enable_idempotence=True,
            compression_type="gzip",
        )
        try:
            await producer.start()
        except Exception as exc:  # noqa: BLE001
            logger.error("redpanda_producer_start_failed", error=str(exc))
            try:
                await producer.stop()
            except Exception:  # noqa: BLE001
                pass
            return False
        self._producer = producer
        logger.info("redpanda_producer_started", url=settings.REDPANDA_URL)
        return True

    async def _ensure_ack_consumer(self) -> bool:
        if self._ack_consumer is not None:
            return True
        consumer = AIOKafkaConsumer(
            settings.REDPANDA_COMMAND_ACK_TOPIC,
            bootstrap_servers=settings.REDPANDA_URL,
            group_id="opsgrid-command-executor",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        try:
            await consumer.start()
        except Exception as exc:  # noqa: BLE001
            logger.error("redpanda_command_ack_consumer_start_failed", error=str(exc))
            try:
                await consumer.stop()
            except Exception:  # noqa: BLE001
                pass
            return False
        self._ack_consumer = consumer
        logger.info(
            "redpanda_command_ack_consumer_started",
            topic=settings.REDPANDA_COMMAND_ACK_TOPIC,
        )
        return True

    async def _reset_producer(self) -> None:
        producer, self._producer = self._producer, None
        if producer is not None:
            try:
                await producer.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("redpanda_producer_stop_failed", error=str(exc))

    async def _reset_ack_consumer(self) -> None:
        consumer, self._ack_consumer = self._ack_consumer, None
        if consumer is not None:
            try:
                await consumer.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("redpanda_ack_consumer_stop_failed", error=str(exc))

    async def _publish_dead_letter(
        self,
        payload: Any,
        *,
        reason: str,
        source_topic: str,
        partition: Optional[int] = None,
        offset: Optional[int] = None,
        consumer: str,
    ) -> None:
        if not await self._ensure_producer():
            raise RuntimeError("DLQ producer unavailable")
        raw = self._payload_bytes(payload)
        summary = self._safe_payload_summary(payload)
        envelope = {
            "schema_version": 1,
            "message_type": "dead_letter",
            "reason": reason,
            "source_topic": source_topic,
            "source_partition": partition,
            "source_offset": offset,
            "consumer": consumer,
            "timestamp": _utcnow().isoformat(),
            "payload_size": len(raw),
            "payload_sha256": hashlib.sha256(raw).hexdigest(),
            "payload_summary": summary,
        }
        key = str(summary.get("command_id") or envelope["payload_sha256"])
        await self._producer.send_and_wait(
            settings.REDPANDA_COMMAND_DLQ_TOPIC,
            envelope,
            key=key.encode("utf-8"),
        )

    async def _organization_ids(self) -> list[UUID]:
        async with self._sessions() as session:
            return list(
                (await session.execute(select(Organization.id))).scalars().all()
            )

    async def _candidate_org_ids(self, organization_id: Optional[str]) -> list[UUID]:
        if organization_id is not None:
            parsed = _uuid(organization_id)
            return [parsed] if parsed is not None else []
        return await self._organization_ids()

    @staticmethod
    async def _set_org(session: AsyncSession, organization_id: UUID) -> None:
        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(organization_id)},
            )

    @staticmethod
    def _ack_outcome(
        ack_payload: Dict[str, Any],
    ) -> Optional[tuple[CommandStatus, Optional[str]]]:
        raw_status = str(ack_payload.get("status") or "").lower()
        success = ack_payload.get("success")
        if isinstance(success, bool):
            if raw_status in {"completed", "success", "succeeded"} and not success:
                return None
            if raw_status in {
                "failed",
                "error",
                "rejected",
                "cancelled",
                "timeout",
            } and success:
                return None
        if raw_status in {"completed", "success", "succeeded"}:
            return CommandStatus.COMPLETED, None
        if raw_status == "cancelled":
            error = str(
                ack_payload.get("error")
                or ack_payload.get("message")
                or "Edge agent cancelled command"
            )
            return CommandStatus.CANCELLED, error
        if raw_status == "timeout":
            error = str(
                ack_payload.get("error")
                or ack_payload.get("message")
                or "Edge agent timed out command"
            )
            return CommandStatus.TIMEOUT, error
        if raw_status in {"failed", "error", "rejected"}:
            error = str(
                ack_payload.get("error")
                or ack_payload.get("message")
                or "Edge agent reported command failure"
            )
            return CommandStatus.FAILED, error
        if isinstance(success, bool):
            if success:
                return CommandStatus.COMPLETED, None
            error = str(
                ack_payload.get("error")
                or ack_payload.get("message")
                or "Edge agent reported command failure"
            )
            return CommandStatus.FAILED, error
        return None

    @staticmethod
    def _is_corrective_self_rollback(
        command: Command,
        incoming_status: CommandStatus,
        ack_payload: Dict[str, Any],
    ) -> bool:
        """Allow a post-success boot rollback to correct the durable outcome."""
        result = ack_payload.get("result")
        return (
            command.action_id == "agent_self_update"
            and command.status
            in {
                CommandStatus.COMPLETED.value,
                CommandStatus.TIMEOUT.value,
            }
            and incoming_status is CommandStatus.FAILED
            and isinstance(result, dict)
            and result.get("rolled_back") is True
        )

    @staticmethod
    def _command_snapshot(command: Command) -> Dict[str, str]:
        return {
            "command_id": str(command.id),
            "organization_id": str(command.organization_id),
            "asset_id": str(command.asset_id),
            "action_id": command.action_id,
        }

    @staticmethod
    def _command_status_payload(command: Command) -> Dict[str, Any]:
        return {
            "command_id": str(command.id),
            "status": command.status,
            "asset_id": str(command.asset_id),
            "action": command.action_id,
            "issued_at": command.issued_at.isoformat() if command.issued_at else None,
            "executed_at": (
                command.executed_at.isoformat() if command.executed_at else None
            ),
            "completed_at": (
                command.completed_at.isoformat() if command.completed_at else None
            ),
            "result": command.result,
            "error": command.error_message,
        }

    @staticmethod
    def _decode_json_object(value: Any) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if isinstance(value, bytes):
            try:
                value = json.loads(value.decode("utf-8"))
            except UnicodeDecodeError:
                return None, "invalid_utf8"
            except json.JSONDecodeError:
                return None, "invalid_json"
        if not isinstance(value, dict):
            return None, "payload_not_object"
        return value, None

    @staticmethod
    def _payload_bytes(payload: Any) -> bytes:
        if isinstance(payload, bytes):
            return payload
        try:
            return json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            # NARROWED to what json.dumps can actually raise here (FS-693's ratchet
            # payment). `default=str` already absorbs unserialisable values, so the
            # remaining cases are a circular reference (ValueError) and a structure deep
            # enough to exhaust the stack (RecursionError); TypeError is kept because a
            # `default` that itself fails raises it.
            #
            # The old `except Exception` also swallowed MemoryError and anything else
            # raised while measuring a payload, and returned a 20-byte type name in its
            # place — so `payload_size` in the dead-letter envelope would record the length
            # of "<class 'dict'>" as if it were the message. Better that an unmeasurable
            # payload propagates than that a wrong number is written down as a measurement.
            return repr(type(payload)).encode("utf-8")

    @staticmethod
    def _safe_payload_summary(payload: Any) -> Dict[str, Any]:
        if isinstance(payload, bytes):
            decoded, error = CommandExecutor._decode_json_object(payload)
            if error:
                return {"payload_type": "bytes"}
            payload = decoded
        if not isinstance(payload, dict):
            return {"payload_type": type(payload).__name__}
        allowed = (
            "schema_version",
            "message_type",
            "command_id",
            "organization_id",
            "asset_id",
            "agent_id",
            "action_id",
            "status",
            "success",
        )
        return {key: payload[key] for key in allowed if key in payload}

    async def _broadcast_safely(
        self,
        organization_id: str,
        asset_id: str,
        command_id: str,
        status: CommandStatus,
        action: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        try:
            await self._broadcast_command_status(
                organization_id,
                asset_id,
                command_id,
                status,
                action,
                result=result,
                error=error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "command_status_broadcast_failed",
                command_id=command_id,
                status=status.value,
                error=str(exc),
            )

    async def _broadcast_command_status(
        self,
        organization_id: str,
        asset_id: str,
        command_id: str,
        status: CommandStatus,
        action: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        await websocket_manager.publish_alarm(
            organization_id=organization_id,
            asset_id=asset_id,
            alarm_data={
                "type": "command_status",
                "severity": "info",
                "message": f"Command {action} {status.value}",
                "command_id": command_id,
                "status": status.value,
                "result": result,
                "error": error,
            },
        )


command_executor = CommandExecutor()
