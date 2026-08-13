"""BACnet Collector for Edge Agent.

Reads objects from BACnet/IP building-automation devices using ``BAC0`` (which
wraps ``bacpypes``). BAC0's read calls are blocking, so they are offloaded to a
worker thread via ``asyncio.to_thread`` to keep the event loop responsive.

Config:
    device_id (int):       BACnet device instance (informational / logging)
    ip_address (str):      Target device IP address (required)
    port (int):            BACnet/IP port (default 47808)
    bind_ip (str):         Local interface for BAC0 to bind, e.g. "10.0.0.5/24"
                           (optional; BAC0 auto-detects if omitted)
    poll_interval (float): Seconds between reads (default 60)
    objects (list):        Objects to read. Each entry:
        {
          "name": "zone_temp",
          "object_type": "analogInput",
          "object_instance": 1,
          "property_id": "presentValue"   # optional, defaults to presentValue
        }
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import asyncio
import structlog

from .base import BaseCollector
from ..resilience import ReconnectPolicy

logger = structlog.get_logger()

try:
    import BAC0
    _BAC0_AVAILABLE = True
    _BAC0_IMPORT_ERROR: Optional[str] = None
except ImportError as exc:  # pragma: no cover - exercised only without the driver
    BAC0 = None  # type: ignore
    _BAC0_AVAILABLE = False
    _BAC0_IMPORT_ERROR = str(exc)


class BACnetCollector(BaseCollector):
    """Collector for BACnet/IP (building automation) devices."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Reconnect discipline, from the ONE policy (FS-473). FS-472 gave five collectors
        # a backoff and a breaker by copying the same four constants into each, which made
        # sixteen occurrences across eight files of a number `modbus` documents as a
        # first-pass guess. `ReconnectPolicy` owns them now, and `reconnect:` in this
        # collector's config overrides them per site without editing this file.
        self._backoff, self._breaker = ReconnectPolicy.from_config(config).instruments(
            f"bacnet:{config.get('asset_id')}"
        )
        self.device_id = config.get("device_id")
        self.ip_address = config.get("ip_address")
        self.port = config.get("port", 47808)
        self.bind_ip = config.get("bind_ip")
        self.poll_interval = config.get("poll_interval", 60)  # seconds
        self.objects: List[Dict[str, Any]] = config.get("objects", [])
        self._poll_task: Optional[asyncio.Task] = None
        self._client: Optional[Any] = None
        self._connected = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        """Start the BACnet collector."""
        await super().start()

        if not _BAC0_AVAILABLE:
            self._running = False
            logger.error(
                "bacnet_driver_missing",
                asset_id=self.asset_id,
                error=_BAC0_IMPORT_ERROR,
                hint="pip install BAC0",
            )
            return

        if not self.ip_address:
            self._running = False
            logger.error("bacnet_no_ip_address", asset_id=self.asset_id)
            return

        self._poll_task = asyncio.create_task(self._poll_loop())

        logger.info(
            "bacnet_collector_started",
            asset_id=self.asset_id,
            device_id=self.device_id,
            ip_address=self.ip_address,
            port=self.port,
            objects_count=len(self.objects),
        )

    async def stop(self) -> None:
        """Stop the BACnet collector."""
        await super().stop()

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        await self._disconnect()
        logger.info("bacnet_collector_stopped", asset_id=self.asset_id)

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #
    def _open_client(self) -> Any:
        """Create a BAC0 network application (runs in a worker thread)."""
        if self.bind_ip:
            return BAC0.lite(ip=self.bind_ip)
        return BAC0.lite()

    async def _connect(self) -> None:
        if self._connected and self._client is not None:
            return
        self._client = await asyncio.to_thread(self._open_client)
        self._connected = True
        logger.info("bacnet_connected", asset_id=self.asset_id)

    async def _disconnect(self) -> None:
        if self._client is not None:
            try:
                await asyncio.to_thread(self._client.disconnect)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "bacnet_disconnect_error",
                    asset_id=self.asset_id,
                    error=str(exc),
                )
        self._client = None
        self._connected = False

    # ------------------------------------------------------------------ #
    # Polling
    # ------------------------------------------------------------------ #
    async def _poll_loop(self) -> None:
        """Poll BACnet objects at configured intervals."""
        while self._running:
            # The breaker is checked BEFORE the attempt (FS-472): once it opens, the
            # loop waits out the cooldown instead of hammering a device that has
            # already refused five times.
            if not self._breaker.allow():
                wait = self._breaker.time_until_retry()
                logger.info(
                    "bacnet_circuit_open", asset_id=self.asset_id, wait_seconds=wait
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
                    "bacnet_poll_error",
                    device_id=self.device_id,
                    error=str(exc),
                )
                await self._disconnect()
                self._breaker.record_failure()
                delay = self._backoff.next_delay()
                logger.info(
                    "bacnet_reconnect_backoff",
                    asset_id=self.asset_id,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
                continue

            await asyncio.sleep(self.poll_interval)

    def _read_object(self, request: str) -> Any:
        """Read a single BACnet property (runs in a worker thread)."""
        return self._client.read(request)

    async def _collect(self) -> None:
        """Collect data from BACnet objects."""
        if not self.objects:
            return

        await self._connect()

        payload: Dict[str, Any] = {}
        for obj in self.objects:
            name = obj.get("name")
            object_type = obj.get("object_type")
            instance = obj.get("object_instance")
            prop = obj.get("property_id", "presentValue")
            if not name or object_type is None or instance is None:
                continue

            request = f"{self.ip_address} {object_type} {instance} {prop}"
            try:
                value = await asyncio.to_thread(self._read_object, request)
            except Exception as exc:
                logger.warning(
                    "bacnet_object_read_failed",
                    asset_id=self.asset_id,
                    object=request,
                    error=str(exc),
                )
                continue

            if value is not None:
                payload[self._payload_key(name)] = value

        if not payload:
            return

        await self.emit(self._normalize_data(payload))
        logger.debug(
            "bacnet_data_collected",
            asset_id=self.asset_id,
            objects_count=len(payload),
        )

    @staticmethod
    def _payload_key(name: str) -> str:
        return name.replace("-", "_").replace(" ", "_").lower()

    def _normalize_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize BACnet object data to the standard telemetry envelope."""
        return {
            # AWARE UTC (FS-461). This was a bare `datetime.now()`, i.e. LOCAL naive.
            # `telemetry.time` is `timestamptz`, and a naive stamp lands there as
            # though it were UTC — so every reading from a device outside UTC was
            # stored wrong by exactly that device's offset.
            "timestamp_edge": datetime.now(timezone.utc).isoformat(),
            "asset_id": self.asset_id,
            "topic": "telemetry",
            "collector_type": "bacnet",
            "payload": dict(payload),
        }
