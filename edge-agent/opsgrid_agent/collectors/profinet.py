"""PROFINET / S7 Collector for Edge Agent.

Reads data blocks from Siemens S7 PLCs using the ``python-snap7`` driver.
``python-snap7`` is synchronous, so all network I/O is offloaded to a worker
thread via ``asyncio.to_thread`` to keep the event loop responsive.

Config:
    ip_address (str):      PLC IP address (required)
    rack (int):            CPU rack number (default 0)
    slot (int):            CPU slot number (default 1)
    poll_interval (float): Seconds between reads (default 5)
    db_blocks (list):      Data blocks to read. Each entry:
        {
          "number": <db number>,
          "start": <byte offset to start reading>,
          "size": <bytes to read>,
          "fields": [                 # optional; typed extraction
            {"name": "temp", "offset": 0, "type": "real"},
            {"name": "count", "offset": 4, "type": "dint"},
            {"name": "running", "offset": 8, "type": "bool", "bit": 0}
          ]
        }
      If "fields" is omitted, the first 4 bytes are emitted as a big-endian int.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import asyncio
import structlog

from .base import BaseCollector
from ..resilience import CircuitBreaker, ExponentialBackoff

logger = structlog.get_logger()

try:
    import snap7
    from snap7 import util as snap7_util
    _SNAP7_AVAILABLE = True
    _SNAP7_IMPORT_ERROR: Optional[str] = None
except ImportError as exc:  # pragma: no cover - exercised only without the driver
    snap7 = None  # type: ignore
    snap7_util = None  # type: ignore
    _SNAP7_AVAILABLE = False
    _SNAP7_IMPORT_ERROR = str(exc)


class ProfinetCollector(BaseCollector):
    """Collector for PROFINET / S7 (Siemens) PLCs."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Reconnect discipline, matching modbus/opcua/mqtt (FS-472). Without this the
        # loop retried every `poll_interval` for as long as the device stayed down —
        # a PLC out for a day drew ~17,000 identical connection attempts, and each one
        # costs the device a socket it has to refuse.
        self._backoff = ExponentialBackoff(initial=1.0, cap=60.0, multiplier=2.0)
        self._breaker = CircuitBreaker(
            failure_threshold=5,
            initial_cooldown=30.0,
            cooldown_cap=300.0,
            cooldown_multiplier=2.0,
            name=f"profinet:{config.get('asset_id')}",
        )
        self.ip_address = config.get("ip_address")
        self.rack = config.get("rack", 0)
        self.slot = config.get("slot", 1)
        self.poll_interval = config.get("poll_interval", 5)  # seconds
        self.db_blocks: List[Dict[str, Any]] = config.get("db_blocks", [])
        self._poll_task: Optional[asyncio.Task] = None
        self._client: Optional[Any] = None
        self._connected = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        """Start the PROFINET collector."""
        await super().start()

        if not _SNAP7_AVAILABLE:
            self._running = False
            logger.error(
                "profinet_driver_missing",
                asset_id=self.asset_id,
                error=_SNAP7_IMPORT_ERROR,
                hint="pip install python-snap7",
            )
            return

        if not self.ip_address:
            self._running = False
            logger.error("profinet_no_ip_address", asset_id=self.asset_id)
            return

        self._poll_task = asyncio.create_task(self._poll_loop())

        logger.info(
            "profinet_collector_started",
            asset_id=self.asset_id,
            ip_address=self.ip_address,
            rack=self.rack,
            slot=self.slot,
            db_blocks_count=len(self.db_blocks),
        )

    async def stop(self) -> None:
        """Stop the PROFINET collector."""
        await super().stop()

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        await self._disconnect()
        logger.info("profinet_collector_stopped", asset_id=self.asset_id)

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #
    def _open_client(self) -> Any:
        """Create and connect an snap7 client (runs in a worker thread)."""
        client = snap7.client.Client()
        client.connect(self.ip_address, self.rack, self.slot)
        return client

    async def _connect(self) -> None:
        if self._connected and self._client is not None:
            return
        self._client = await asyncio.to_thread(self._open_client)
        self._connected = True
        logger.info(
            "profinet_connected",
            asset_id=self.asset_id,
            ip_address=self.ip_address,
        )

    async def _disconnect(self) -> None:
        if self._client is not None:
            try:
                await asyncio.to_thread(self._client.disconnect)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "profinet_disconnect_error",
                    asset_id=self.asset_id,
                    error=str(exc),
                )
        self._client = None
        self._connected = False

    # ------------------------------------------------------------------ #
    # Polling
    # ------------------------------------------------------------------ #
    async def _poll_loop(self) -> None:
        """Poll DB blocks at configured intervals."""
        while self._running:
            # The breaker is checked BEFORE the attempt (FS-472): once it opens, the
            # loop waits out the cooldown instead of hammering a device that has
            # already refused five times.
            if not self._breaker.allow():
                wait = self._breaker.time_until_retry()
                logger.info(
                    "profinet_circuit_open", asset_id=self.asset_id, wait_seconds=wait
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
                logger.error(
                    "profinet_poll_error",
                    asset_id=self.asset_id,
                    ip_address=self.ip_address,
                    error=str(exc),
                )
                await self._disconnect()
                self._breaker.record_failure()
                delay = self._backoff.next_delay()
                logger.info(
                    "profinet_reconnect_backoff",
                    asset_id=self.asset_id,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
                continue

            await asyncio.sleep(self.poll_interval)

    def _read_db(self, number: int, start: int, size: int) -> bytearray:
        """Read a DB block (runs in a worker thread)."""
        return self._client.db_read(number, start, size)

    async def _collect(self) -> None:
        """Collect data from DB blocks."""
        if not self.db_blocks:
            return

        await self._connect()

        payload: Dict[str, Any] = {}
        for block in self.db_blocks:
            number = block.get("number")
            start = block.get("start", 0)
            size = block.get("size", 4)
            if number is None:
                continue

            data = await asyncio.to_thread(self._read_db, number, start, size)
            payload.update(self._extract_block(number, block, data))

        if not payload:
            return

        await self.emit(self._normalize_data(payload))
        logger.debug(
            "profinet_data_collected",
            asset_id=self.asset_id,
            db_blocks_count=len(self.db_blocks),
            fields=len(payload),
        )

    def _extract_block(
        self, number: int, block: Dict[str, Any], data: bytearray
    ) -> Dict[str, Any]:
        """Extract typed fields from a DB block payload."""
        fields = block.get("fields")
        if not fields:
            # Backwards-compatible default: first 4 bytes as a big-endian int.
            value = int.from_bytes(data[:4], byteorder="big") if len(data) >= 4 else 0
            return {f"db{number}_value": value}

        extracted: Dict[str, Any] = {}
        for field in fields:
            name = field.get("name")
            offset = field.get("offset", 0)
            ftype = str(field.get("type", "int")).lower()
            if not name:
                continue
            try:
                extracted[f"db{number}_{name}"] = self._decode_field(
                    data, offset, ftype, field.get("bit", 0)
                )
            except Exception as exc:
                logger.warning(
                    "profinet_field_decode_error",
                    asset_id=self.asset_id,
                    db=number,
                    field=name,
                    type=ftype,
                    error=str(exc),
                )
        return extracted

    @staticmethod
    def _decode_field(data: bytearray, offset: int, ftype: str, bit: int) -> Any:
        """Decode a single S7 value using snap7 utilities."""
        if ftype == "real":
            return snap7_util.get_real(data, offset)
        if ftype == "int":
            return snap7_util.get_int(data, offset)
        if ftype == "dint":
            return snap7_util.get_dint(data, offset)
        if ftype == "word":
            return snap7_util.get_word(data, offset)
        if ftype == "dword":
            return snap7_util.get_dword(data, offset)
        if ftype == "bool":
            return snap7_util.get_bool(data, offset, bit)
        if ftype == "byte":
            return data[offset]
        raise ValueError(f"unsupported S7 field type: {ftype}")

    def _normalize_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize DB block data to the standard telemetry envelope."""
        return {
            # AWARE UTC (FS-461). This was a bare `datetime.now()`, i.e. LOCAL naive.
            # `telemetry.time` is `timestamptz`, and a naive stamp lands there as
            # though it were UTC — so every reading from a device outside UTC was
            # stored wrong by exactly that device's offset.
            "timestamp_edge": datetime.now(timezone.utc).isoformat(),
            "asset_id": self.asset_id,
            "topic": "telemetry",
            "collector_type": "profinet",
            "payload": dict(payload),
        }
