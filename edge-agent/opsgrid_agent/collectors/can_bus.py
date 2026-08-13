"""CAN Bus Collector for Edge Agent.

Receives frames from a CAN bus (vehicle / machine controllers) using the
``python-can`` driver. ``python-can``'s ``recv`` is blocking, so it is offloaded
to a worker thread via ``asyncio.to_thread`` to keep the event loop responsive.

Config:
    interface (str):   python-can interface / bustype, e.g. "socketcan",
                       "pcan", "vector" (default "socketcan")
    channel (str):     Bus channel, e.g. "can0" (default "can0")
    bitrate (int):     Bus bitrate in bits/sec (default 500000)
    can_ids (list):    Arbitration IDs to accept (ints). Empty = accept all.
    poll_interval (float): Seconds to sleep between receive batches (default 0.1)
    batch_size (int):  Max frames drained per batch (default 10)
    recv_timeout (float): Per-frame blocking receive timeout in seconds (default 0.5)
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import asyncio
import structlog

from .base import BaseCollector
from ..resilience import ReconnectPolicy

logger = structlog.get_logger()

try:
    import can
    _CAN_AVAILABLE = True
    _CAN_IMPORT_ERROR: Optional[str] = None
except ImportError as exc:  # pragma: no cover - exercised only without the driver
    can = None  # type: ignore
    _CAN_AVAILABLE = False
    _CAN_IMPORT_ERROR = str(exc)


class CANBusCollector(BaseCollector):
    """Collector for CAN Bus (vehicle / machine controllers)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Reconnect discipline, from the ONE policy (FS-473). FS-472 gave five collectors
        # a backoff and a breaker by copying the same four constants into each, which made
        # sixteen occurrences across eight files of a number `modbus` documents as a
        # first-pass guess. `ReconnectPolicy` owns them now, and `reconnect:` in this
        # collector's config overrides them per site without editing this file.
        self._backoff, self._breaker = ReconnectPolicy.from_config(config).instruments(
            f"can_bus:{config.get('asset_id')}"
        )
        # "bustype" is accepted as an alias for backwards compatibility.
        self.interface = config.get("interface") or config.get("bustype", "socketcan")
        self.channel = config.get("channel", "can0")
        self.bitrate = config.get("bitrate", 500000)
        self.can_ids: List[int] = config.get("can_ids", [])
        self.poll_interval = config.get("poll_interval", 0.1)  # seconds
        self.batch_size = config.get("batch_size", 10)
        self.recv_timeout = config.get("recv_timeout", 0.5)
        self._poll_task: Optional[asyncio.Task] = None
        self._bus: Optional[Any] = None
        self._connected = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        """Start the CAN Bus collector."""
        await super().start()

        if not _CAN_AVAILABLE:
            self._running = False
            logger.error(
                "can_bus_driver_missing",
                asset_id=self.asset_id,
                error=_CAN_IMPORT_ERROR,
                hint="pip install python-can",
            )
            return

        self._poll_task = asyncio.create_task(self._poll_loop())

        logger.info(
            "can_bus_collector_started",
            asset_id=self.asset_id,
            interface=self.interface,
            channel=self.channel,
            bitrate=self.bitrate,
            can_ids_count=len(self.can_ids),
        )

    async def stop(self) -> None:
        """Stop the CAN Bus collector."""
        await super().stop()

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        await self._disconnect()
        logger.info("can_bus_collector_stopped", asset_id=self.asset_id)

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #
    def _open_bus(self) -> Any:
        """Create the CAN bus interface (runs in a worker thread)."""
        kwargs: Dict[str, Any] = {
            "interface": self.interface,
            "channel": self.channel,
        }
        if self.bitrate:
            kwargs["bitrate"] = self.bitrate
        if self.can_ids:
            kwargs["can_filters"] = [
                {"can_id": can_id, "can_mask": 0x7FF, "extended": False}
                for can_id in self.can_ids
            ]
        return can.Bus(**kwargs)

    async def _connect(self) -> None:
        if self._connected and self._bus is not None:
            return
        self._bus = await asyncio.to_thread(self._open_bus)
        self._connected = True
        logger.info(
            "can_bus_connected",
            asset_id=self.asset_id,
            channel=self.channel,
        )

    async def _disconnect(self) -> None:
        if self._bus is not None:
            try:
                await asyncio.to_thread(self._bus.shutdown)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "can_bus_disconnect_error",
                    asset_id=self.asset_id,
                    error=str(exc),
                )
        self._bus = None
        self._connected = False

    # ------------------------------------------------------------------ #
    # Polling
    # ------------------------------------------------------------------ #
    async def _poll_loop(self) -> None:
        """Receive CAN frames in batches."""
        while self._running:
            # The breaker is checked BEFORE the attempt (FS-472): once it opens, the
            # loop waits out the cooldown instead of hammering a device that has
            # already refused five times.
            if not self._breaker.allow():
                wait = self._breaker.time_until_retry()
                logger.info(
                    "can_bus_circuit_open", asset_id=self.asset_id, wait_seconds=wait
                )
                await asyncio.sleep(wait)
                continue

            try:
                await self._collect()
                # A clean poll resets the curve, so a brief blip does not leave the
                # next outage starting from a 60-second delay.
                self._backoff.reset()
                self._breaker.record_success()
            except Exception as exc:
                self.record_failure(
                    "can_bus_poll_error",
                    channel=self.channel,
                    error=str(exc),
                )
                await self._disconnect()
                self._breaker.record_failure()
                delay = self._backoff.next_delay()
                logger.info(
                    "can_bus_reconnect_backoff",
                    asset_id=self.asset_id,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
                continue

            await asyncio.sleep(self.poll_interval)

    def _drain(self) -> List[Any]:
        """Drain up to batch_size frames from the bus (runs in a worker thread)."""
        messages: List[Any] = []
        for _ in range(self.batch_size):
            msg = self._bus.recv(timeout=self.recv_timeout)
            if msg is None:
                break
            messages.append(msg)
        return messages

    async def _collect(self) -> None:
        """Collect frames from the CAN bus and emit each."""
        await self._connect()

        messages = await asyncio.to_thread(self._drain)
        for msg in messages:
            await self.emit(self._normalize_data(msg))

        if messages:
            logger.debug(
                "can_bus_data_collected",
                asset_id=self.asset_id,
                messages_count=len(messages),
            )

    def _normalize_data(self, message: Any) -> Dict[str, Any]:
        """Normalize a python-can Message to the standard telemetry envelope."""
        arbitration_id = getattr(message, "arbitration_id", 0)
        data = bytes(getattr(message, "data", b"") or b"")
        # python-can timestamps are epoch seconds (float); fall back to now.
        ts = getattr(message, "timestamp", None)
        if ts:
            timestamp = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        else:
            timestamp = datetime.now(tz=timezone.utc).isoformat()

        payload: Dict[str, Any] = {
            "can_id": f"0x{arbitration_id:03X}",
            "dlc": len(data),
            "is_extended_id": bool(getattr(message, "is_extended_id", False)),
        }
        for i, byte in enumerate(data[:8]):
            payload[f"byte_{i}"] = byte
        if len(data) >= 4:
            payload["value"] = int.from_bytes(data[:4], byteorder="little")

        return {
            "timestamp_edge": timestamp,
            "asset_id": self.asset_id,
            "topic": "telemetry",
            "collector_type": "can_bus",
            "payload": payload,
        }
