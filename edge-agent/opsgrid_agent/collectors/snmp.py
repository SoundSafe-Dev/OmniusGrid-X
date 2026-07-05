"""SNMP Collector for Edge Agent.

Polls SNMP OIDs from network devices / gateways / UPSes using ``pysnmp``. The
high-level SNMP calls are synchronous, so they run in a worker thread via
``asyncio.to_thread`` to keep the event loop responsive.

Config:
    host (str):            Target IP/hostname (required; alias: ip_address)
    port (int):            SNMP port (default 161)
    community (str):       SNMPv2c community string (default "public")
    version (str):         "2c" (default) or "1"
    poll_interval (float): Seconds between polls (default 60)
    oids (list):           OIDs to read. Each entry is an OID string, or a dict
                           {"name": <payload key>, "oid": <numeric OID>}.
"""

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import asyncio
import structlog

from .base import BaseCollector

logger = structlog.get_logger()

try:
    from pysnmp import hlapi
    _PYSNMP_AVAILABLE = True
    _PYSNMP_IMPORT_ERROR: Optional[str] = None
except ImportError as exc:  # pragma: no cover - exercised only without the driver
    hlapi = None  # type: ignore
    _PYSNMP_AVAILABLE = False
    _PYSNMP_IMPORT_ERROR = str(exc)


class SNMPCollector(BaseCollector):
    """Collector that polls SNMP OIDs."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.host = config.get("host") or config.get("ip_address")
        self.port = config.get("port", 161)
        self.community = config.get("community", "public")
        self.version = str(config.get("version", "2c"))
        self.poll_interval = config.get("poll_interval", 60)
        self.oids: List[Any] = config.get("oids", [])
        self._poll_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        await super().start()
        if not _PYSNMP_AVAILABLE:
            self._running = False
            logger.error("snmp_driver_missing", asset_id=self.asset_id,
                         error=_PYSNMP_IMPORT_ERROR, hint="pip install pysnmp")
            return
        if not self.host:
            self._running = False
            logger.error("snmp_no_host", asset_id=self.asset_id)
            return
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("snmp_collector_started", asset_id=self.asset_id,
                    host=self.host, port=self.port, oids_count=len(self.oids))

    async def stop(self) -> None:
        await super().stop()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("snmp_collector_stopped", asset_id=self.asset_id)

    def _resolve_oids(self) -> List[Tuple[str, str]]:
        """Normalize configured OIDs to (payload_key, oid) pairs."""
        resolved: List[Tuple[str, str]] = []
        for entry in self.oids:
            if isinstance(entry, dict):
                oid = entry.get("oid")
                if not oid:
                    continue
                name = entry.get("name", oid)
            else:
                oid = str(entry)
                name = oid
            resolved.append((str(name).replace(".", "_").replace(":", "_").lower(), str(oid)))
        return resolved

    @staticmethod
    def _coerce(value: Any) -> Any:
        """Best-effort numeric coercion of an SNMP varBind value."""
        try:
            f = float(value)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            return str(value)

    def _read_oids(self, resolved: List[Tuple[str, str]]) -> Dict[str, Any]:
        """Read OIDs synchronously (runs in a worker thread)."""
        mp_model = 0 if self.version == "1" else 1
        values: Dict[str, Any] = {}
        for name, oid in resolved:
            error_indication, error_status, _idx, var_binds = next(hlapi.getCmd(
                hlapi.SnmpEngine(),
                hlapi.CommunityData(self.community, mpModel=mp_model),
                hlapi.UdpTransportTarget((self.host, self.port)),
                hlapi.ContextData(),
                hlapi.ObjectType(hlapi.ObjectIdentity(oid)),
            ))
            if error_indication or error_status:
                logger.warning("snmp_oid_read_failed", asset_id=self.asset_id,
                               oid=oid, error=str(error_indication or error_status))
                continue
            for var_bind in var_binds:
                values[name] = self._coerce(var_bind[1])
        return values

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                resolved = self._resolve_oids()
                if resolved:
                    values = await asyncio.to_thread(self._read_oids, resolved)
                    if values:
                        await self.emit(self._normalize_data(values))
            except Exception as exc:
                logger.error("snmp_poll_error", asset_id=self.asset_id, error=str(exc))
            await asyncio.sleep(self.poll_interval)

    def _normalize_data(self, values: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "timestamp_edge": datetime.now().isoformat(),
            "asset_id": self.asset_id,
            "topic": "telemetry",
            "collector_type": "snmp",
            "payload": dict(values),
        }
