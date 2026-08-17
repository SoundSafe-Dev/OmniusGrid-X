"""DNP3 Collector for Edge Agent.

Polls a DNP3 outstation (utility / SCADA / substation gear) for analog and
binary points using the ``dnp3_python`` master. Driver calls run in a worker
thread via ``asyncio.to_thread``.

Config:
    host (str):            Outstation IP/hostname (required; alias: ip_address)
    port (int):            DNP3 port (default 20000)
    master_addr (int):     Master link address (default 1)
    outstation_addr (int): Outstation link address (default 1024)
    poll_interval (float): Seconds between integrity polls (default 10)
    points (list):         Points to read. Each: {"name": <key>, "group":
                           "analog"|"binary", "index": <int>}.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import asyncio
import structlog

from .base import BaseCollector
from ..resilience import ReconnectPolicy

logger = structlog.get_logger()

try:
    from dnp3_python.dnp3station.master_new import MyMasterNew  # type: ignore
    _DNP3_AVAILABLE = True
    _DNP3_IMPORT_ERROR: Optional[str] = None
except ImportError as exc:  # pragma: no cover - exercised only without the driver
    MyMasterNew = None  # type: ignore
    _DNP3_AVAILABLE = False
    _DNP3_IMPORT_ERROR = str(exc)


class DNP3Collector(BaseCollector):
    """Collector that polls a DNP3 outstation.

    NOT FIELD-PROVEN, and the reason is packaging rather than protocol (FS-738). The
    collector is written, swept by the agent's hardening guards — backoff and breaker from
    the one `ReconnectPolicy`, aware-UTC timestamps, counted failures — and exercised in
    `tests/test_new_collectors.py` against a fake master. What it has never done is talk to
    a real outstation, because `dnp3_python` publishes **cp38–cp310 linux wheels only**.
    The pin in `edge-agent/requirements.txt` is marked `python_version < "3.11"` and the
    agent image is `python:3.11-slim`, so the driver is absent from every image we build.
    Live DNP3 sites: **zero**, by construction.

    That is a supply gap in somebody else's package and it needs a maintained py3.11 DNP3
    driver (or a vendored libopendnp3 binding) before a site can be commissioned. Until
    then this class refuses to start and says why — see `driver_unavailable_reason`, which
    the coordinator reports so the agent can answer "why is there no DNP3 data" without
    anybody reading a log.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        #: Set when the driver could not be imported, and read by
        #: `CollectorCoordinator.get_collector_status`. `None` means the driver is present
        #: — the attribute always exists so a consumer never has to guess whether the
        #: absence of the field means "fine" or "old collector".
        self.driver_unavailable_reason: Optional[str] = (
            None if _DNP3_AVAILABLE else (
                f"dnp3_python is not installed ({_DNP3_IMPORT_ERROR}). It ships cp38-cp310 "
                f"linux wheels only, so it is excluded from this image by the "
                f'python_version < "3.11" marker in requirements.txt.'
            )
        )
        # Reconnect discipline, from the ONE policy (FS-473). FS-472 gave five collectors
        # a backoff and a breaker by copying the same four constants into each, which made
        # sixteen occurrences across eight files of a number `modbus` documents as a
        # first-pass guess. `ReconnectPolicy` owns them now, and `reconnect:` in this
        # collector's config overrides them per site without editing this file.
        self._backoff, self._breaker = ReconnectPolicy.from_config(config).instruments(
            f"dnp3:{config.get('asset_id')}"
        )
        self.host = config.get("host") or config.get("ip_address")
        self.port = config.get("port", 20000)
        self.master_addr = config.get("master_addr", 1)
        self.outstation_addr = config.get("outstation_addr", 1024)
        self.poll_interval = config.get("poll_interval", 10)
        self.points: List[Dict[str, Any]] = config.get("points", [])
        self._master: Optional[Any] = None
        self._connected = False
        self._poll_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        await super().start()
        if not _DNP3_AVAILABLE:
            self._running = False
            # `error`, not `warning`, and it carries the reason rather than a `pip install`
            # hint that cannot succeed on this interpreter: there is no py3.11 wheel to
            # install. `_run_collector` will treat this return as a restart and retry nine
            # more times, which is wasted on a missing module — but the retry budget is the
            # coordinator's policy and a collector should not reach up and change it, so
            # the honest signal is the status field, not a special case here.
            logger.error("dnp3_driver_missing", asset_id=self.asset_id,
                         error=_DNP3_IMPORT_ERROR,
                         reason=self.driver_unavailable_reason)
            return
        if not self.host:
            self._running = False
            logger.error("dnp3_no_host", asset_id=self.asset_id)
            return
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("dnp3_collector_started", asset_id=self.asset_id,
                    host=self.host, port=self.port, points_count=len(self.points))

    async def stop(self) -> None:
        await super().stop()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        await self._disconnect()
        logger.info("dnp3_collector_stopped", asset_id=self.asset_id)

    def _open_master(self) -> Any:
        master = MyMasterNew(
            masterstation_ip_str="0.0.0.0",
            outstation_ip_str=self.host,
            port=self.port,
            master_id=self.master_addr,
            outstation_id=self.outstation_addr,
        )
        master.start()
        return master

    async def _connect(self) -> None:
        if self._connected and self._master is not None:
            return
        self._master = await asyncio.to_thread(self._open_master)
        self._connected = True
        logger.info("dnp3_connected", asset_id=self.asset_id, host=self.host)

    async def _disconnect(self) -> None:
        if self._master is not None:
            try:
                await asyncio.to_thread(self._master.shutdown)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("dnp3_disconnect_error", asset_id=self.asset_id, error=str(exc))
        self._master = None
        self._connected = False

    def _read_points(self) -> Dict[str, Any]:
        """Read configured points from the outstation DB (runs in a worker thread)."""
        values: Dict[str, Any] = {}
        # Snapshot the master's point databases once.
        soe = getattr(self._master, "soe_handler", None)
        nested = getattr(soe, "gv_index_value_nested_dict", {}) if soe else {}
        analog = nested.get("AnalogInput", {})
        binary = nested.get("BinaryInput", {})
        for point in self.points:
            name = point.get("name")
            group = str(point.get("group", "analog")).lower()
            index = point.get("index")
            if name is None or index is None:
                continue
            source = analog if group.startswith("analog") else binary
            entry = source.get(index)
            if entry is not None:
                # entry is typically {timestamp: value}; take the latest value.
                value = list(entry.values())[-1] if isinstance(entry, dict) else entry
                values[str(name).lower()] = value
        return values

    async def _poll_loop(self) -> None:
        while self._running:
            # Checked BEFORE the attempt (FS-472). This loop calls `_connect()` on every
            # iteration, so without the breaker an unreachable outstation was dialled once
            # per `poll_interval` indefinitely.
            if not self._breaker.allow():
                wait = self._breaker.time_until_retry()
                logger.info(
                    "dnp3_circuit_open", asset_id=self.asset_id, wait_seconds=wait
                )
                await asyncio.sleep(wait)
                continue

            try:
                await self._connect()
                if self.points:
                    values = await asyncio.to_thread(self._read_points)
                    if values:
                        await self.emit(self._normalize_data(values))
                self._backoff.reset()
                self._breaker.record_success()
            except Exception as exc:
                self.record_failure("dnp3_poll_error", error=str(exc))
                await self._disconnect()
                self._breaker.record_failure()
                delay = self._backoff.next_delay()
                logger.info(
                    "dnp3_reconnect_backoff",
                    asset_id=self.asset_id,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
                continue
            await asyncio.sleep(self.poll_interval)

    def _normalize_data(self, values: Dict[str, Any]) -> Dict[str, Any]:
        return {
            # AWARE UTC (FS-461). This was a bare `datetime.now()`, i.e. LOCAL naive.
            # `telemetry.time` is `timestamptz`, and a naive stamp lands there as
            # though it were UTC — so every reading from a device outside UTC was
            # stored wrong by exactly that device's offset.
            "timestamp_edge": datetime.now(timezone.utc).isoformat(),
            "asset_id": self.asset_id,
            "topic": "telemetry",
            "collector_type": "dnp3",
            "payload": dict(values),
        }
