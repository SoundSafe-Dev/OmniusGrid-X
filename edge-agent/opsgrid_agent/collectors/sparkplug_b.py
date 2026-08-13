"""MQTT Sparkplug B Collector for Edge Agent.

Subscribes to Sparkplug B (spBv1.0) topics over MQTT and decodes the protobuf
payloads into telemetry. Sparkplug is push/subscribe (not poll): paho delivers
messages on its own network thread, so decoded readings are handed to the
asyncio loop via ``run_coroutine_threadsafe``.

Sparkplug B protocol handling implemented here:
  * Topic parsing ``spBv1.0/{group}/{msg_type}/{node}[/{device}]``.
  * Alias resolution: NBIRTH/DBIRTH carry each metric's full ``name`` *and* its
    numeric ``alias``; to save bandwidth NDATA/DDATA usually carry ONLY the
    alias. We learn the alias->name map from the birth and resolve data metrics
    against it — otherwise every aliased data metric is silently dropped.
  * Sequence tracking: the payload ``seq`` counts 0..255 and wraps. A gap (or
    data before a birth) means we missed a message / the map is stale, so we
    request a rebirth. Data we *can* still resolve is emitted regardless — a
    seq gap must never itself drop readings.
  * Deaths (NDEATH/DDEATH) and host STATE messages carry no live telemetry and
    are not emitted.

Config:
    host (str):        MQTT broker host (required; alias: broker)
    port (int):        MQTT port (default 1883)
    topic (str):       Subscription filter (default "spBv1.0/#")
    username/password: optional broker credentials
    client_id (str):   optional MQTT client id
"""

from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import asyncio
import structlog

from .base import BaseCollector
from opsgrid_agent.tasks import spawn

logger = structlog.get_logger()

try:
    import paho.mqtt.client as mqtt
    _PAHO_AVAILABLE = True
except ImportError:  # pragma: no cover
    mqtt = None  # type: ignore
    _PAHO_AVAILABLE = False

try:
    # Eclipse Tahu-generated Sparkplug B protobuf schema.
    import sparkplug_b_pb2  # type: ignore
    _SPARKPLUG_PB_AVAILABLE = True
except ImportError:  # pragma: no cover
    sparkplug_b_pb2 = None  # type: ignore
    _SPARKPLUG_PB_AVAILABLE = False

# Value oneof fields we surface as telemetry (numeric + scalar text/bool). Ordered
# so the numeric ones are probed first when a stub payload lacks WhichOneof.
_NUMERIC_FIELDS = ("double_value", "float_value", "long_value", "int_value", "boolean_value")
_VALUE_FIELDS = _NUMERIC_FIELDS + ("string_value",)

_BIRTH_TYPES = ("NBIRTH", "DBIRTH")
_DEATH_TYPES = ("NDEATH", "DDEATH")
_DATA_TYPES = ("NDATA", "DDATA")

# Metrics that are Sparkplug bookkeeping, not asset telemetry.
_CONTROL_METRIC_PREFIXES = ("Node Control/", "Device Control/")
_BDSEQ_METRIC = "bdSeq"


class SparkplugBCollector(BaseCollector):
    """Collector for MQTT Sparkplug B."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.host = config.get("host") or config.get("broker")
        self.port = config.get("port", 1883)
        self.topic = config.get("topic", "spBv1.0/#")
        self.username = config.get("username")
        self.password = config.get("password")
        self.client_id = config.get("client_id", f"opsgrid-spb-{self.asset_id}")
        self._client: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Per edge-node state (keyed by "group/node"): alias->name maps and the
        # next expected sequence number. Aliases in Sparkplug are unique across
        # an edge node and all its devices, so one map per node covers devices.
        self._alias_maps: Dict[str, Dict[int, str]] = {}
        self._expected_seq: Dict[str, int] = {}

    async def start(self) -> None:
        await super().start()
        if not (_PAHO_AVAILABLE and _SPARKPLUG_PB_AVAILABLE):
            self._running = False
            logger.error("sparkplug_driver_missing", asset_id=self.asset_id,
                         paho=_PAHO_AVAILABLE, protobuf=_SPARKPLUG_PB_AVAILABLE,
                         hint="pip install paho-mqtt tahu")
            return
        if not self.host:
            self._running = False
            logger.error("sparkplug_no_host", asset_id=self.asset_id)
            return

        self._loop = asyncio.get_running_loop()
        self._client = mqtt.Client(client_id=self.client_id)
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.on_message = self._on_message
        await asyncio.to_thread(self._client.connect, self.host, self.port)
        self._client.subscribe(self.topic)
        self._client.loop_start()
        logger.info("sparkplug_collector_started", asset_id=self.asset_id,
                    host=self.host, topic=self.topic)

    async def stop(self) -> None:
        await super().stop()
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("sparkplug_stop_error", asset_id=self.asset_id, error=str(exc))
        self._client = None
        logger.info("sparkplug_collector_stopped", asset_id=self.asset_id)

    # ------------------------------------------------------------------ #
    # Decoding helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_topic(topic: str) -> Optional[Tuple[str, str, str, Optional[str]]]:
        """Parse ``spBv1.0/{group}/{msg_type}/{node}[/{device}]``.

        Returns (group, msg_type, node, device|None) or None if not spBv1.0.
        """
        if not topic:
            return None
        parts = topic.split("/")
        if len(parts) < 4 or parts[0] != "spBv1.0":
            return None
        group, msg_type, node = parts[1], parts[2], parts[3]
        device = parts[4] if len(parts) > 4 else None
        return group, msg_type, node, device

    @staticmethod
    def _metric_value(metric: Any) -> Any:
        """Return a metric's set scalar value, or None if it carries no scalar.

        Uses the protobuf ``value`` oneof so an *unset* numeric field (which
        reads back as 0/0.0 on protobuf) is never mistaken for a real reading —
        the old fallback fabricated 0.0 for string/complex metrics.
        """
        which = metric.WhichOneof("value") if hasattr(metric, "WhichOneof") else None
        if which is not None:
            return getattr(metric, which) if which in _VALUE_FIELDS else None
        # Stub/legacy payloads without WhichOneof: probe declared fields, using
        # HasField where available so unset scalars are skipped rather than
        # read back as their zero default.
        for field in _NUMERIC_FIELDS:
            try:
                if metric.HasField(field):
                    return getattr(metric, field)
            except (ValueError, AttributeError):
                val = getattr(metric, field, None)
                if val is not None:
                    return val
        return None

    @classmethod
    def _decode(cls, payload_bytes: bytes) -> Dict[str, Any]:
        """Decode a payload into {metric_name: value} for *named* metrics.

        Alias-only metrics are not resolvable without the birth context, so this
        low-level helper only surfaces named metrics; alias resolution lives in
        the topic-aware :meth:`_extract_metrics` path used by ``_on_message``.
        """
        payload = cls._decode_payload(payload_bytes)
        metrics: Dict[str, Any] = {}
        for metric in payload.metrics:
            name = getattr(metric, "name", None)
            if not name:
                continue
            val = cls._metric_value(metric)
            if val is not None:
                metrics[name] = val
        return metrics

    @staticmethod
    def _decode_payload(payload_bytes: bytes) -> Any:
        payload = sparkplug_b_pb2.Payload()
        payload.ParseFromString(payload_bytes)
        return payload

    def _extract_metrics(
        self, payload: Any, node_key: str, is_birth: bool
    ) -> Tuple[Dict[str, Any], bool]:
        """Resolve a payload's metrics to {name: value}, learning/using aliases.

        Returns (values, had_unresolved_alias). On a birth we (re)learn the
        alias->name map; on data we resolve alias-only metrics against it. An
        alias we have never seen (missed/old birth) is reported via the second
        return value so the caller can request a rebirth — but every metric we
        *can* name is still emitted.
        """
        amap = self._alias_maps.setdefault(node_key, {})
        values: Dict[str, Any] = {}
        had_unresolved = False
        for metric in payload.metrics:
            name = getattr(metric, "name", "") or ""
            alias = getattr(metric, "alias", 0) or 0
            if is_birth and name and alias:
                amap[alias] = name
            if not name and alias:
                name = amap.get(alias, "")
                if not name:
                    had_unresolved = True
                    logger.warning("sparkplug_unresolved_alias",
                                   asset_id=self.asset_id, node=node_key, alias=alias)
                    continue
            if not name:
                continue
            # Skip Sparkplug bookkeeping metrics — not asset telemetry.
            if name == _BDSEQ_METRIC or name.startswith(_CONTROL_METRIC_PREFIXES):
                continue
            val = self._metric_value(metric)
            if val is not None:
                values[name] = val
        return values, had_unresolved

    def _check_sequence(self, node_key: str, seq: Optional[int], is_birth: bool) -> bool:
        """Track the 0..255 sequence counter; return True if in sync.

        A birth resets the expected sequence. For data, a missing prior birth or
        a gap returns False (caller requests a rebirth). ``seq is None`` (a stub
        payload without the field) is treated as in-sync so tests / non-Sparkplug
        stubs are not penalised.
        """
        if seq is None:
            return True
        if is_birth:
            self._expected_seq[node_key] = (seq + 1) % 256
            return True
        expected = self._expected_seq.get(node_key)
        if expected is None:
            return False  # data before we ever saw a birth
        if seq != expected:
            # Resync to whatever we just got so we don't fire a rebirth on every
            # subsequent message, but signal the gap for this one.
            self._expected_seq[node_key] = (seq + 1) % 256
            return False
        self._expected_seq[node_key] = (seq + 1) % 256
        return True

    def _request_rebirth(self, group: str, node: str) -> None:
        """Publish an NCMD Node Control/Rebirth so the node re-sends its births."""
        if self._client is None or not _SPARKPLUG_PB_AVAILABLE:
            return
        try:
            payload = sparkplug_b_pb2.Payload()
            metric = payload.metrics.add()
            metric.name = "Node Control/Rebirth"
            metric.boolean_value = True
            self._client.publish(f"spBv1.0/{group}/NCMD/{node}",
                                 payload.SerializeToString())
            logger.info("sparkplug_rebirth_requested",
                        asset_id=self.asset_id, group=group, node=node)
        except Exception as exc:  # pragma: no cover - defensive
            self.record_failure("sparkplug_rebirth_failed",
                                group=group, node=node, error=str(exc))

    @staticmethod
    def _payload_timestamp(payload: Any) -> datetime:
        """Prefer the payload's own epoch-millis timestamp; else now (aware UTC)."""
        ts = getattr(payload, "timestamp", 0) or 0
        if ts:
            try:
                return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
            except (ValueError, OverflowError, OSError, TypeError):
                pass
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------------ #
    # Message handling
    # ------------------------------------------------------------------ #
    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """paho callback (network thread) -> decode -> deliver on the event loop."""
        try:
            envelope = self._process(getattr(msg, "topic", ""), msg.payload)
        except Exception as exc:
            self.record_failure("sparkplug_decode_error", error=str(exc))
            return
        if envelope is None:
            return
        # `spawn`, WHICH THIS FILE ALREADY HAD THE RIGHT IDEA ABOUT (FS-681). The hand-rolled
        # `run_coroutine_threadsafe` here was correct — and was the pattern MQTT and the file
        # watcher needed and did not have (FS-675). Two things it did not do: retain the
        # returned future, so the loop held only a weak reference to the work, and say
        # anything when `self._loop` was None. That second case returned silently, so a
        # reading decoded on paho's thread before `start()` had run vanished without trace;
        # `spawn` logs `background_task_unscheduled` and closes the coroutine instead.
        spawn(self.emit(envelope), name="sparkplug.emit", loop=self._loop)

    def _process(self, topic: str, payload_bytes: bytes) -> Optional[Dict[str, Any]]:
        """Decode a message, applying alias/sequence/message-type semantics.

        Returns a telemetry envelope, or None when there is nothing to emit
        (deaths, host STATE, or a payload with no resolvable metric values).
        """
        parsed = self._parse_topic(topic)
        payload = self._decode_payload(payload_bytes)

        if parsed is None:
            # Non-Sparkplug topic (or bare test payload): decode named metrics
            # only, no alias/sequence context available.
            values = self._decode(payload_bytes)
            if not values:
                return None
            return self._normalize_data(values, self._payload_timestamp(payload))

        group, msg_type, node, _device = parsed
        node_key = f"{group}/{node}"

        if msg_type == "STATE" or msg_type in _DEATH_TYPES:
            # Host application state and death certificates carry no live
            # telemetry; deaths simply mark the node/device offline.
            return None

        seq = getattr(payload, "seq", None)
        is_birth = msg_type in _BIRTH_TYPES
        in_sync = self._check_sequence(node_key, seq, is_birth)
        if not in_sync and msg_type in _DATA_TYPES:
            # Missed a message or never saw the birth: ask for a rebirth so the
            # alias map is rebuilt. Still emit anything we could resolve below.
            self._request_rebirth(group, node)

        if is_birth or msg_type in _DATA_TYPES:
            values, had_unresolved = self._extract_metrics(payload, node_key, is_birth)
            if had_unresolved and msg_type in _DATA_TYPES:
                self._request_rebirth(group, node)
            if not values:
                return None
            return self._normalize_data(values, self._payload_timestamp(payload))

        # NCMD/DCMD and anything else: not telemetry.
        return None

    def _normalize_data(
        self, values: Dict[str, Any], timestamp_edge: Optional[datetime] = None
    ) -> Dict[str, Any]:
        ts = timestamp_edge or datetime.now(timezone.utc)
        return {
            # Aware UTC (was naive local time): the store-and-forward buffer and
            # coordinator subtract an aware now() for backfill-lag/age, where a
            # naive local stamp is either a swallowed TypeError (dropped reading)
            # or an age wrong by the host's UTC offset.
            "timestamp_edge": ts.isoformat(),
            "asset_id": self.asset_id,
            "topic": "telemetry",
            "collector_type": "sparkplug_b",
            "payload": {str(k).replace("/", "_").lower(): v for k, v in values.items()},
        }
