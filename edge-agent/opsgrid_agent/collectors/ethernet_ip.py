"""EtherNet/IP Collector for Edge Agent.

Reads tags from Rockwell / Allen-Bradley PLCs over EtherNet/IP using the
``pylogix`` driver. ``pylogix`` is synchronous, so all network I/O is offloaded
to a worker thread via ``asyncio.to_thread`` to keep the event loop responsive.

Config:
    ip_address (str):    PLC IP address (required)
    port (int):          EtherNet/IP port (default 44818)
    slot (int):          Processor slot in the chassis (default 0)
    poll_interval (float): Seconds between reads (default 5)
    tags (list):         Tags to read. Each entry is either a tag-name string,
                         or a dict {"name": <payload key>, "tag": <PLC tag>}.
"""

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
import asyncio
import structlog

from .base import BaseCollector

logger = structlog.get_logger()

try:
    from pylogix import PLC
    _PYLOGIX_AVAILABLE = True
    _PYLOGIX_IMPORT_ERROR: Optional[str] = None
except ImportError as exc:  # pragma: no cover - exercised only without the driver
    PLC = None  # type: ignore
    _PYLOGIX_AVAILABLE = False
    _PYLOGIX_IMPORT_ERROR = str(exc)


class EthernetIPCollector(BaseCollector):
    """Collector for EtherNet/IP (Rockwell Automation) PLCs."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.ip_address = config.get("ip_address")
        self.port = config.get("port", 44818)
        self.slot = config.get("slot", 0)
        self.poll_interval = config.get("poll_interval", 5)  # seconds
        self.tags: List[Any] = config.get("tags", [])
        self._poll_task: Optional[asyncio.Task] = None
        self._client: Optional[Any] = None
        self._connected = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        """Start the EtherNet/IP collector."""
        await super().start()

        if not _PYLOGIX_AVAILABLE:
            self._running = False
            logger.error(
                "ethernet_ip_driver_missing",
                asset_id=self.asset_id,
                error=_PYLOGIX_IMPORT_ERROR,
                hint="pip install pylogix",
            )
            return

        if not self.ip_address:
            self._running = False
            logger.error("ethernet_ip_no_ip_address", asset_id=self.asset_id)
            return

        self._poll_task = asyncio.create_task(self._poll_loop())

        logger.info(
            "ethernet_ip_collector_started",
            asset_id=self.asset_id,
            ip_address=self.ip_address,
            port=self.port,
            slot=self.slot,
            tags_count=len(self.tags),
        )

    async def stop(self) -> None:
        """Stop the EtherNet/IP collector."""
        await super().stop()

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        await self._disconnect()
        logger.info("ethernet_ip_collector_stopped", asset_id=self.asset_id)

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #
    def _open_client(self) -> Any:
        """Create and configure a pylogix PLC client (runs in a worker thread)."""
        client = PLC()
        client.IPAddress = self.ip_address
        client.ProcessorSlot = self.slot
        client.Port = self.port
        return client

    async def _connect(self) -> None:
        if self._connected and self._client is not None:
            return
        self._client = await asyncio.to_thread(self._open_client)
        self._connected = True
        logger.info(
            "ethernet_ip_connected",
            asset_id=self.asset_id,
            ip_address=self.ip_address,
        )

    async def _disconnect(self) -> None:
        if self._client is not None:
            try:
                await asyncio.to_thread(self._client.Close)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "ethernet_ip_disconnect_error",
                    asset_id=self.asset_id,
                    error=str(exc),
                )
        self._client = None
        self._connected = False

    # ------------------------------------------------------------------ #
    # Polling
    # ------------------------------------------------------------------ #
    async def _poll_loop(self) -> None:
        """Poll PLC tags at configured intervals."""
        while self._running:
            try:
                await self._collect()
            except Exception as exc:
                logger.error(
                    "ethernet_ip_poll_error",
                    asset_id=self.asset_id,
                    ip_address=self.ip_address,
                    error=str(exc),
                )
                # Drop the connection so the next iteration reconnects.
                await self._disconnect()

            await asyncio.sleep(self.poll_interval)

    def _resolve_tags(self) -> List[Tuple[str, str]]:
        """Normalize the configured tags to (payload_key, plc_tag) pairs."""
        resolved: List[Tuple[str, str]] = []
        for entry in self.tags:
            if isinstance(entry, dict):
                plc_tag = entry.get("tag") or entry.get("name")
                if not plc_tag:
                    continue
                payload_key = entry.get("name", plc_tag)
            else:
                plc_tag = str(entry)
                payload_key = plc_tag
            resolved.append((self._payload_key(payload_key), plc_tag))
        return resolved

    @staticmethod
    def _payload_key(name: str) -> str:
        return name.replace(".", "_").replace(":", "_").lower()

    def _read_tags(self, plc_tags: List[str]) -> List[Any]:
        """Read a batch of tags (runs in a worker thread). Returns pylogix Responses."""
        result = self._client.Read(plc_tags)
        # pylogix returns a single Response for one tag, a list for many.
        if not isinstance(result, list):
            return [result]
        return result

    async def _collect(self) -> None:
        """Collect data from PLC tags."""
        resolved = self._resolve_tags()
        if not resolved:
            return

        await self._connect()

        plc_tags = [plc_tag for _, plc_tag in resolved]
        responses = await asyncio.to_thread(self._read_tags, plc_tags)

        tag_values: Dict[str, Any] = {}
        for (payload_key, plc_tag), response in zip(resolved, responses):
            status = getattr(response, "Status", None)
            value = getattr(response, "Value", None)
            if status == "Success" and value is not None:
                tag_values[payload_key] = value
            else:
                logger.warning(
                    "ethernet_ip_tag_read_failed",
                    asset_id=self.asset_id,
                    tag=plc_tag,
                    status=status,
                )

        if not tag_values:
            return

        await self.emit(self._normalize_data(tag_values))
        logger.debug(
            "ethernet_ip_data_collected",
            asset_id=self.asset_id,
            tags_count=len(tag_values),
        )

    def _normalize_data(self, tag_values: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize PLC tag data to the standard telemetry envelope."""
        return {
            # AWARE UTC (FS-461). This was a bare `datetime.now()`, i.e. LOCAL naive.
            # `telemetry.time` is `timestamptz`, and a naive stamp lands there as
            # though it were UTC — so every reading from a device outside UTC was
            # stored wrong by exactly that device's offset.
            "timestamp_edge": datetime.now(timezone.utc).isoformat(),
            "asset_id": self.asset_id,
            "topic": "telemetry",
            "collector_type": "ethernet_ip",
            "payload": dict(tag_values),
        }
