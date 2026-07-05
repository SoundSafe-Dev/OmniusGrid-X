"""MQTT Sparkplug B Collector for Edge Agent.

Subscribes to Sparkplug B (spBv1.0) topics over MQTT and decodes the protobuf
payloads into telemetry. Sparkplug is push/subscribe (not poll): paho delivers
messages on its own network thread, so decoded readings are handed to the
asyncio loop via ``run_coroutine_threadsafe``.

Config:
    host (str):        MQTT broker host (required; alias: broker)
    port (int):        MQTT port (default 1883)
    topic (str):       Subscription filter (default "spBv1.0/#")
    username/password: optional broker credentials
    client_id (str):   optional MQTT client id
"""

from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
import structlog

from .base import BaseCollector

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

_NUMERIC_FIELDS = ("double_value", "float_value", "long_value", "int_value", "boolean_value")


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

    @staticmethod
    def _decode(payload_bytes: bytes) -> Dict[str, Any]:
        """Decode a Sparkplug B protobuf payload into {metric_name: value}."""
        payload = sparkplug_b_pb2.Payload()
        payload.ParseFromString(payload_bytes)
        metrics: Dict[str, Any] = {}
        for metric in payload.metrics:
            name = getattr(metric, "name", None)
            if not name:
                continue
            which = metric.WhichOneof("value") if hasattr(metric, "WhichOneof") else None
            if which and which in _NUMERIC_FIELDS:
                metrics[name] = getattr(metric, which)
            else:
                for field in _NUMERIC_FIELDS:
                    val = getattr(metric, field, None)
                    if val is not None:
                        metrics[name] = val
                        break
        return metrics

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """paho callback (network thread) -> decode -> deliver on the event loop."""
        try:
            values = self._decode(msg.payload)
        except Exception as exc:
            logger.error("sparkplug_decode_error", asset_id=self.asset_id, error=str(exc))
            return
        if not values or self._loop is None:
            return
        envelope = self._normalize_data(values)
        asyncio.run_coroutine_threadsafe(self.emit(envelope), self._loop)

    def _normalize_data(self, values: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "timestamp_edge": datetime.now().isoformat(),
            "asset_id": self.asset_id,
            "topic": "telemetry",
            "collector_type": "sparkplug_b",
            "payload": {str(k).replace("/", "_").lower(): v for k, v in values.items()},
        }
