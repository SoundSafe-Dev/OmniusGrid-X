"""Redpanda command consumer and acknowledgement producer."""

import asyncio
import inspect
import json
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Set

import structlog

logger = structlog.get_logger()

CommandHandler = Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]


class CommandConsumer:
    """Consume backend command envelopes, dispatch handlers, and emit acks."""

    def __init__(
        self,
        *,
        agent_id: str,
        organization_id: str,
        asset_ids: Iterable[str],
        redpanda_url: str,
        command_topic: str = "opsgrid.commands",
        ack_topic: str = "opsgrid.commands.acks",
        seen_capacity: int = 1024,
    ):
        self.agent_id = str(agent_id)
        self.organization_id = str(organization_id)
        self.asset_ids: Set[str] = {str(asset_id) for asset_id in asset_ids if asset_id}
        self.redpanda_url = redpanda_url
        self.command_topic = command_topic
        self.ack_topic = ack_topic
        self.seen_capacity = seen_capacity

        self._handlers: Dict[str, CommandHandler] = {}
        self._seen_acks: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._consumer = None
        self._producer = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def register_handler(self, action_id: str, handler: CommandHandler) -> None:
        """Register a handler for an action_id."""
        if not action_id:
            raise ValueError("action_id is required")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._handlers[str(action_id)] = handler

    async def start(self) -> None:
        """Start command consumption."""
        if self._running:
            return

        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

        self._consumer = AIOKafkaConsumer(
            self.command_topic,
            bootstrap_servers=self.redpanda_url,
            group_id=f"agent-{self.agent_id}",
            value_deserializer=self._deserialize_value,
            enable_auto_commit=True,
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.redpanda_url,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            key_serializer=lambda key: key.encode("utf-8") if key else None,
            acks="all",
        )

        try:
            await self._consumer.start()
            await self._producer.start()
            self._running = True
            self._task = asyncio.create_task(self._consume_loop())
            logger.info(
                "command_consumer_started",
                agent_id=self.agent_id,
                command_topic=self.command_topic,
                ack_topic=self.ack_topic,
            )
        except Exception:
            await self._stop_clients()
            raise

    async def stop(self) -> None:
        """Stop command consumption and ack production."""
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

    async def handle_message(self, payload: Any) -> Optional[Dict[str, Any]]:
        """Handle one decoded command payload. Returns the ack if one was emitted."""
        payload = self._normalize_payload(payload)
        if not payload:
            logger.warning("command_payload_malformed")
            return None

        if not self._should_process(payload):
            return None

        command_id = str(payload.get("command_id") or "")
        if not command_id:
            logger.warning("command_missing_command_id", payload=payload)
            return None

        cached_ack = self._seen_acks.get(command_id)
        if cached_ack:
            self._seen_acks.move_to_end(command_id)
            await self._emit_ack(cached_ack)
            logger.info("command_duplicate_ack_reemitted", command_id=command_id)
            return cached_ack

        action_id = str(payload.get("action_id") or "")
        handler = self._handlers.get(action_id)
        if handler is None:
            ack = self._build_ack(
                payload,
                status="rejected",
                success=False,
                result={"error": "unknown_action", "action_id": action_id},
                error="unknown_action",
            )
            await self._remember_and_emit(command_id, ack)
            return ack

        try:
            result = handler(payload)
            if inspect.isawaitable(result):
                result = await result
            if result is None:
                result = {}
            elif not isinstance(result, dict):
                result = {"value": result}

            ack = self._build_ack(
                payload,
                status="completed",
                success=True,
                result=result,
            )
        except Exception as exc:
            logger.exception(
                "command_handler_failed",
                command_id=command_id,
                action_id=action_id,
                error=str(exc),
            )
            ack = self._build_ack(
                payload,
                status="failed",
                success=False,
                result={
                    "error": str(exc),
                    "action_id": action_id,
                    **({"phase": exc.phase} if hasattr(exc, "phase") else {}),
                },
                error=str(exc),
            )

        await self._remember_and_emit(command_id, ack)
        return ack

    async def _consume_loop(self) -> None:
        while self._running and self._consumer is not None:
            try:
                async for message in self._consumer:
                    await self.handle_message(message.value)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("command_consumer_loop_error", error=str(exc))
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
            logger.warning(
                "command_ack_producer_unavailable",
                command_id=ack.get("command_id"),
            )
            return

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

    def _should_process(self, payload: Dict[str, Any]) -> bool:
        if payload.get("message_type") != "command":
            return False

        organization_id = payload.get("organization_id")
        if organization_id and str(organization_id) != self.organization_id:
            return False

        target_agent_id = payload.get("agent_id")
        if target_agent_id:
            return str(target_agent_id) == self.agent_id

        asset_id = payload.get("asset_id")
        return bool(asset_id and str(asset_id) in self.asset_ids)

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
            "status": status,
            "success": success,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            ack["error"] = error
        return ack

    @staticmethod
    def _deserialize_value(value: bytes) -> Any:
        return json.loads(value.decode("utf-8"))

    @staticmethod
    def _normalize_payload(payload: Any) -> Optional[Dict[str, Any]]:
        if isinstance(payload, bytes):
            try:
                payload = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
        return payload if isinstance(payload, dict) else None
