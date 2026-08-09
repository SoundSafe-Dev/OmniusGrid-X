"""Redpanda command consumer, acknowledgement producer, and command DLQ."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Set, Union
from uuid import UUID

import structlog

from opsgrid_agent.remote_ops.contracts import (
    MAX_COMMAND_ACK_BYTES,
    RemoteOperationError,
    error_result,
    is_remote_operation,
    json_size,
    validate_parameters,
    validate_result,
)

logger = structlog.get_logger()


@dataclass
class DeferredCommandAck:
    """A durable handler outcome whose acknowledgement follows a process restart."""

    reason: str
    after_commit: Callable[[], Awaitable[None] | None]

    async def run_after_commit(self) -> None:
        result = self.after_commit()
        if inspect.isawaitable(result):
            await result


CommandResult = Optional[Union[Dict[str, Any], DeferredCommandAck]]
CommandHandler = Callable[[Dict[str, Any]], Awaitable[CommandResult] | CommandResult]


class CommandConsumer:
    """Validate command records, dispatch owned commands, and emit durable outcomes."""

    def __init__(
        self,
        *,
        agent_id: str,
        organization_id: str,
        asset_ids: Iterable[str],
        redpanda_url: str,
        command_topic: str = "opsgrid.commands",
        ack_topic: str = "opsgrid.commands.acks",
        dlq_topic: str = "opsgrid.commands.dlq",
        seen_capacity: int = 1024,
    ):
        self.agent_id = str(agent_id)
        self.organization_id = str(organization_id)
        self.asset_ids: Set[str] = {
            str(asset_id) for asset_id in asset_ids if asset_id
        }
        self.redpanda_url = redpanda_url
        self.command_topic = command_topic
        self.ack_topic = ack_topic
        self.dlq_topic = dlq_topic
        self.seen_capacity = seen_capacity

        self._handlers: Dict[str, CommandHandler] = {}
        self._seen_acks: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._consumer = None
        self._producer = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def register_handler(self, action_id: str, handler: CommandHandler) -> None:
        """Register a handler for an action_id."""
        if not action_id:
            raise ValueError("action_id is required")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._handlers[str(action_id)] = handler

    async def start(self, *, consume: bool = True) -> None:
        """Start raw command consumption with manual offset commits."""
        if self._running:
            if consume:
                self.start_consuming()
            return

        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

        self._consumer = AIOKafkaConsumer(
            self.command_topic,
            bootstrap_servers=self.redpanda_url,
            group_id=f"agent-{self.agent_id}",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.redpanda_url,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            key_serializer=lambda key: key.encode("utf-8") if key else None,
            acks="all",
            enable_idempotence=True,
        )

        try:
            await self._consumer.start()
            await self._producer.start()
            self._running = True
            if consume:
                self.start_consuming()
            logger.info(
                "command_consumer_started",
                agent_id=self.agent_id,
                command_topic=self.command_topic,
                ack_topic=self.ack_topic,
                dlq_topic=self.dlq_topic,
            )
        except Exception:
            await self._stop_clients()
            raise

    def start_consuming(self) -> None:
        """Begin consumption after startup reconciliation has completed."""
        if not self._running:
            raise RuntimeError("Command consumer clients are not started")
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        """Stop command consumption and publication."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._stop_clients()
        logger.info("command_consumer_stopped", agent_id=self.agent_id)

    async def handle_message(
        self,
        payload: Any,
        *,
        source_partition: Optional[int] = None,
        source_offset: Optional[int] = None,
    ) -> CommandResult:
        """Validate and handle one raw command record."""
        command, validation_error = self._decode_and_validate(payload)
        if validation_error:
            await self._publish_dead_letter(
                payload,
                reason=validation_error,
                source_partition=source_partition,
                source_offset=source_offset,
            )
            logger.warning(
                "command_dead_lettered",
                reason=validation_error,
                partition=source_partition,
                offset=source_offset,
            )
            return None

        if not self._should_process(command):
            return None

        command_id = str(command["command_id"])
        cached_ack = self._seen_acks.get(command_id)
        if cached_ack:
            self._seen_acks.move_to_end(command_id)
            await self._emit_ack(cached_ack)
            logger.info("command_duplicate_ack_reemitted", command_id=command_id)
            return cached_ack

        action_id = str(command["action_id"])
        handler = self._handlers.get(action_id)
        if handler is None:
            ack = self._build_ack(
                command,
                status="rejected",
                success=False,
                result={"error": "unknown_action", "action_id": action_id},
                error="unknown_action",
            )
            await self._remember_and_emit(command_id, ack)
            return ack

        remote_operation = is_remote_operation(action_id)
        if remote_operation:
            try:
                command = dict(command)
                command["parameters"] = validate_parameters(
                    action_id,
                    command["parameters"],
                )
            except RemoteOperationError as exc:
                ack = self._build_ack(
                    command,
                    status="rejected",
                    success=False,
                    result=error_result(action_id, exc),
                    error=exc.public_message,
                )
                await self._remember_and_emit(command_id, ack)
                return ack

        try:
            result = handler(command)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, DeferredCommandAck):
                logger.info(
                    "command_ack_deferred",
                    command_id=command_id,
                    action_id=action_id,
                    reason=result.reason,
                )
                return result
            if result is None:
                result = {}
            elif not isinstance(result, dict):
                result = {"value": result}
            if remote_operation:
                result = validate_result(action_id, result)

            ack = self._build_ack(
                command,
                status="completed",
                success=True,
                result=result,
            )
        except RemoteOperationError as exc:
            logger.warning(
                "remote_operation_failed",
                command_id=command_id,
                action_id=action_id,
                error_code=exc.code,
            )
            ack = self._build_ack(
                command,
                status="failed",
                success=False,
                result=error_result(action_id, exc),
                error=exc.public_message,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "command_handler_failed",
                command_id=command_id,
                action_id=action_id,
                error=str(exc),
            )
            if remote_operation:
                remote_error = RemoteOperationError("operation_failed")
                result = error_result(action_id, remote_error)
                public_error = remote_error.public_message
            else:
                result = {
                    "error": str(exc),
                    "action_id": action_id,
                    **({"phase": exc.phase} if hasattr(exc, "phase") else {}),
                }
                public_error = str(exc)
            ack = self._build_ack(
                command,
                status="failed",
                success=False,
                result=result,
                error=public_error,
            )

        await self._remember_and_emit(command_id, ack)
        return ack

    async def emit_command_ack(
        self,
        command: Dict[str, Any],
        *,
        status: str,
        success: bool,
        result: Dict[str, Any],
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Publish an acknowledgement reconstructed after a process restart."""
        ack = self._build_ack(
            command,
            status=status,
            success=success,
            result=result,
            error=error,
        )
        await self._remember_and_emit(str(command["command_id"]), ack)
        return ack

    async def _consume_loop(self) -> None:
        from aiokafka import TopicPartition

        while self._running and self._consumer is not None:
            try:
                async for message in self._consumer:
                    if not self._running:
                        return
                    try:
                        outcome = await self.handle_message(
                            message.value,
                            source_partition=message.partition,
                            source_offset=message.offset,
                        )
                        await self._consumer.commit(
                            {
                                TopicPartition(message.topic, message.partition):
                                    message.offset + 1
                            }
                        )
                        if isinstance(outcome, DeferredCommandAck):
                            await self._run_deferred_after_commit(
                                outcome,
                                command_offset=message.offset,
                            )
                            return
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "command_processing_failed",
                            error=str(exc),
                            partition=message.partition,
                            offset=message.offset,
                        )
                        self._consumer.seek(
                            TopicPartition(message.topic, message.partition),
                            message.offset,
                        )
                        await asyncio.sleep(1)
                        break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("command_consumer_loop_error", error=str(exc))
                await asyncio.sleep(5)

    async def _run_deferred_after_commit(
        self,
        outcome: DeferredCommandAck,
        *,
        command_offset: int,
    ) -> None:
        """Retry the restart handoff without rewinding an already committed offset."""
        while self._running:
            try:
                await outcome.run_after_commit()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "command_post_commit_action_failed",
                    reason=outcome.reason,
                    source_offset=command_offset,
                    error=str(exc),
                )
                await asyncio.sleep(5)

    async def _stop_clients(self) -> None:
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
        if self._producer:
            await self._producer.stop()
            self._producer = None

    async def _remember_and_emit(self, command_id: str, ack: Dict[str, Any]) -> None:
        self._seen_acks[command_id] = ack
        self._seen_acks.move_to_end(command_id)
        while len(self._seen_acks) > self.seen_capacity:
            self._seen_acks.popitem(last=False)
        await self._emit_ack(ack)

    async def _emit_ack(self, ack: Dict[str, Any]) -> None:
        if self._producer is None:
            raise RuntimeError("Command acknowledgement producer unavailable")
        await self._producer.send_and_wait(
            self.ack_topic,
            ack,
            key=str(ack["command_id"]),
        )
        logger.info(
            "command_ack_published",
            command_id=ack["command_id"],
            status=ack["status"],
            success=ack["success"],
        )

    async def _publish_dead_letter(
        self,
        payload: Any,
        *,
        reason: str,
        source_partition: Optional[int],
        source_offset: Optional[int],
    ) -> None:
        if self._producer is None:
            raise RuntimeError("Command DLQ producer unavailable")
        raw = self._payload_bytes(payload)
        summary = self._safe_payload_summary(payload)
        payload_hash = hashlib.sha256(raw).hexdigest()
        envelope = {
            "schema_version": 1,
            "message_type": "dead_letter",
            "reason": reason,
            "source_topic": self.command_topic,
            "source_partition": source_partition,
            "source_offset": source_offset,
            "agent_id": self.agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload_size": len(raw),
            "payload_sha256": payload_hash,
            "payload_summary": summary,
        }
        await self._producer.send_and_wait(
            self.dlq_topic,
            envelope,
            key=str(summary.get("command_id") or payload_hash),
        )

    def _should_process(self, payload: Dict[str, Any]) -> bool:
        if str(payload["organization_id"]) != self.organization_id:
            return False
        target_agent_id = payload.get("agent_id")
        if target_agent_id:
            return str(target_agent_id) == self.agent_id
        return str(payload["asset_id"]) in self.asset_ids

    def _build_ack(
        self,
        payload: Dict[str, Any],
        *,
        status: str,
        success: bool,
        result: Dict[str, Any],
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        ack = {
            "command_id": str(payload["command_id"]),
            "agent_id": self.agent_id,
            "asset_id": str(payload.get("asset_id") or ""),
            "organization_id": self.organization_id,
            "status": status,
            "success": success,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            ack["error"] = str(error)[:512]
        if json_size(ack) > MAX_COMMAND_ACK_BYTES:
            action_id = str(payload.get("action_id") or "")
            if is_remote_operation(action_id):
                overflow = RemoteOperationError("result_too_large")
                ack["result"] = error_result(action_id, overflow)
                ack["error"] = overflow.public_message
            else:
                ack["result"] = {"error": "command_result_too_large"}
                ack["error"] = "Command result exceeded the acknowledgement limit"
            ack["status"] = "failed"
            ack["success"] = False
        return ack

    @staticmethod
    def _decode_and_validate(
        payload: Any,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if isinstance(payload, bytes):
            try:
                payload = json.loads(payload.decode("utf-8"))
            except UnicodeDecodeError:
                return None, "invalid_utf8"
            except json.JSONDecodeError:
                return None, "invalid_json"
        if not isinstance(payload, dict):
            return None, "payload_not_object"
        if payload.get("schema_version") != 1:
            return None, "unsupported_schema_version"
        if payload.get("message_type") != "command":
            return None, "unsupported_message_type"
        for field in ("command_id", "organization_id", "asset_id"):
            value = payload.get(field)
            if not value:
                return None, f"missing_{field}"
            try:
                UUID(str(value))
            except (ValueError, TypeError, AttributeError):
                return None, f"invalid_{field}"
        if not payload.get("action_id"):
            return None, "missing_action_id"
        if not isinstance(payload.get("parameters"), dict):
            return None, "invalid_parameters"
        timeout = payload.get("timeout_seconds")
        if timeout is not None and (
            not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0
        ):
            return None, "invalid_timeout_seconds"
        return payload, None

    @staticmethod
    def _payload_bytes(payload: Any) -> bytes:
        if isinstance(payload, bytes):
            return payload
        try:
            return json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        except Exception:  # noqa: BLE001
            return repr(type(payload)).encode("utf-8")

    @classmethod
    def _safe_payload_summary(cls, payload: Any) -> Dict[str, Any]:
        if isinstance(payload, bytes):
            decoded, error = cls._decode_for_summary(payload)
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
        )
        return {key: payload[key] for key in allowed if key in payload}

    @staticmethod
    def _decode_for_summary(
        payload: bytes,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "invalid_json"
        if not isinstance(decoded, dict):
            return None, "payload_not_object"
        return decoded, None
