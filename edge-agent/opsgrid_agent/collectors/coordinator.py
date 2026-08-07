"""
Unified Collector Coordinator
Manages all data source collectors in a single coordinated system
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
import structlog

from opsgrid_agent.collectors.mqtt import BambuCollector, MQTTCollector
from opsgrid_agent.collectors.screen_scraper import QidiCollector, SovolCollector
from opsgrid_agent.collectors.file_watcher import OrcaSlicerCollector
from opsgrid_agent.collectors.opcua_collector import OPCUACollector
from opsgrid_agent.collectors.modbus_collector import ModbusCollector
from opsgrid_agent.buffer.store_forward import StoreForwardBuffer

# BaseCollector-style collectors, bridged to the coordinator contract via an
# adapter. Relative imports keep these independent of the package name so they
# are unaffected by the omniusgrid_agent -> opsgrid_agent rename.
from .adapter import coordinator_adapter
from .ethernet_ip import EthernetIPCollector
from .profinet import ProfinetCollector
from .bacnet import BACnetCollector
from .can_bus import CANBusCollector
from .http_rest import HTTPRestCollector
from .snmp import SNMPCollector
from .sparkplug_b import SparkplugBCollector
from .dnp3 import DNP3Collector
from .audio import AudioFeatureCollector
from .video import VideoFrameCollector
from .. import metrics
from ..analytics import pipeline as analytics_pipeline
# Relative import: rename-agnostic, like the adapter/metrics seam.
from ..quality import QualityAction, QualityConfig, QualityPipeline

logger = structlog.get_logger()


#: Config keys consumed by the agent rather than by a collector's constructor (FS-500).
#:
#: They live inside each collector's `config` block because that is where an operator
#: naturally writes them, and they are read from there by the coordinator, the adapter and
#: `main`. Splatting them into the constructor is what broke the four collectors that take
#: no `**kwargs`.
#: Whether a reading is published to Kafka the moment it arrives, in addition to being
#: buffered (FS-499). **False**, and the long comment in `_on_collector_message` says why:
#: the path raised on every message from the day it was written until FS-495, so
#: buffer-then-backfill is the only delivery behaviour that has ever shipped; and switching it
#: on needs the org in the topic, an ack-guaranteed send, and marking the buffered row sent,
#: or every reading is delivered twice.
IMMEDIATE_FORWARD_ENABLED = False

CROSS_CUTTING_KEYS = frozenset({"quality", "packml", "alerts", "oee"})


@dataclass
class CollectorConfig:
    """Configuration for a single collector instance"""
    collector_type: str  # mqtt, screen_scraper, file_watcher, opcua, modbus,
                         # ethernet_ip, profinet, bacnet, can_bus, http_rest
    asset_id: str
    config: Dict[str, Any]
    enabled: bool = True


class UnifiedCollectorCoordinator:
    """
    Coordinates all data collectors and manages their lifecycle.
    
    Features:
    - Starts/stops all configured collectors
    - Routes messages to buffering layer
    - Health monitoring of all collectors
    - Dynamic collector registration
    """
    
    SUPPORTED_COLLECTORS = {
        'bambu_mqtt': BambuCollector,
        'mqtt': MQTTCollector,
        'qidi_screen': QidiCollector,
        'sovol_screen': SovolCollector,
        'orca_file': OrcaSlicerCollector,
        'opcua': OPCUACollector,
        'modbus': ModbusCollector,
        # BaseCollector-style collectors wrapped for the coordinator contract.
        'ethernet_ip': coordinator_adapter(EthernetIPCollector),
        'profinet': coordinator_adapter(ProfinetCollector),
        'bacnet': coordinator_adapter(BACnetCollector),
        'can_bus': coordinator_adapter(CANBusCollector),
        'http_rest': coordinator_adapter(HTTPRestCollector),
        'snmp': coordinator_adapter(SNMPCollector),
        'sparkplug_b': coordinator_adapter(SparkplugBCollector),
        'dnp3': coordinator_adapter(DNP3Collector),
        'audio': coordinator_adapter(AudioFeatureCollector),
        'video': coordinator_adapter(VideoFrameCollector),
    }
    
    def __init__(
        self,
        buffer: StoreForwardBuffer,
        kafka_producer: Optional[Any] = None,
        max_concurrent: int = 20
    ):
        self.buffer = buffer
        self.kafka_producer = kafka_producer
        self.max_concurrent = max_concurrent
        
        # Collector instances
        self.collectors: Dict[str, Any] = {}
        self.collector_tasks: Dict[str, asyncio.Task] = {}
        
        # Configuration
        self.configs: Dict[str, CollectorConfig] = {}

        # Per-asset data-quality pipelines, built from each collector's optional
        # `config.quality` block. Absent block -> no pipeline -> passthrough.
        self._quality: Dict[str, QualityPipeline] = {}

        # Status tracking
        self._running = False
        self._health_check_task: Optional[asyncio.Task] = None
        #: The per-collector supervision tasks (FS-502). Held so they are not garbage
        #: collected mid-flight and so `stop_all` can cancel them.
        self._collector_tasks: List[asyncio.Task] = []
        #: True while the immediate Kafka forward is failing (FS-496). Used only to decide
        #: LOG LEVEL: the first failure since the last success is a warning, the rest are
        #: debug. Without this, either a broken path stays silent (what FS-495 did for its
        #: whole life) or an offline broker writes one warning per message.
        self._forward_failing = False
    
    def register_collector(self, config: CollectorConfig):
        """Register a collector configuration"""
        self.configs[config.asset_id] = config

        # Build a data-quality pipeline if this collector opted in. A malformed
        # block is logged and skipped rather than failing collector startup.
        raw_quality = (config.config or {}).get("quality")
        if raw_quality:
            try:
                self._quality[config.asset_id] = QualityPipeline(
                    QualityConfig.model_validate(raw_quality)
                )
            except Exception as e:  # pydantic ValidationError or bad shape
                logger.error(
                    "quality_config_invalid",
                    asset_id=config.asset_id,
                    error=str(e),
                )

        logger.info(
            "collector_registered",
            asset_id=config.asset_id,
            type=config.collector_type
        )
    
    async def start_all(self):
        """Start all registered collectors"""
        logger.info("starting_all_collectors", count=len(self.configs))
        self._running = True
        
        # Start collectors concurrently (up to max_concurrent)
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def start_with_limit(config: CollectorConfig):
            async with semaphore:
                await self._start_collector(config)
        
        # RETAINED, NOT DROPPED (FS-502). This built the list into a local that went out of
        # scope on the next line — never awaited, and with no strong reference, so the event
        # loop was free to garbage-collect a supervision task mid-flight and the exception
        # from a collector that failed to start had nowhere to surface. `all_collectors_started`
        # was then logged before any collector had started.
        #
        # These are long-lived supervisors, so they are NOT awaited here — `start_all` must
        # return. They are held on the instance and cancelled in `stop_all`.
        self._collector_tasks = [
            asyncio.create_task(start_with_limit(config))
            for config in self.configs.values()
            if config.enabled
        ]

        # Start health monitoring
        self._health_check_task = asyncio.create_task(self._health_monitor())
        
        logger.info(
            "collector_supervisors_started",
            count=len(self._collector_tasks),
        )
    
    async def _start_collector(self, config: CollectorConfig):
        """Start a single collector instance"""
        try:
            collector_class = self.SUPPORTED_COLLECTORS.get(config.collector_type)
            if not collector_class:
                logger.error(
                    "unknown_collector_type",
                    asset_id=config.asset_id,
                    type=config.collector_type
                )
                return
            
            # CROSS-CUTTING KEYS ARE STRIPPED FIRST (FS-500).
            #
            # `config.config` is splatted into the constructor, and four of its keys are not
            # the collector's business at all — they are read by other parts of the agent
            # out of the same dict:
            #
            #     quality  -> this class, `_quality` (line ~123)
            #     packml   -> `collectors/adapter.py:55`
            #     alerts   -> `main.py:506`
            #     oee      -> `main.py:512`
            #
            # Four of the seventeen registered collector types take no `**kwargs` — mqtt,
            # modbus, opcua and orca_file — so for those, a `quality:` or `alerts:` block
            # raised `TypeError: unexpected keyword argument`, which the handler below
            # catches and logs as `collector_start_failed`. **The collector then never ran**,
            # and the only symptom was one log line at startup describing a config key the
            # operator had every reason to think was supported. The adapter-wrapped
            # collectors were unaffected because they take the raw dict, which is why this
            # depended on which device you were talking to.
            collector = collector_class(
                **{k: v for k, v in (config.config or {}).items() if k not in CROSS_CUTTING_KEYS},
                on_message_callback=self._on_collector_message
            )
            
            self.collectors[config.asset_id] = collector
            
            # Start collector in background task
            task = asyncio.create_task(
                self._run_collector(config.asset_id, collector)
            )
            self.collector_tasks[config.asset_id] = task
            
            logger.info(
                "collector_started",
                asset_id=config.asset_id,
                type=config.collector_type
            )
            
        except Exception as e:
            logger.error(
                "collector_start_failed",
                asset_id=config.asset_id,
                error=str(e)
            )
    
    async def _run_collector(self, asset_id: str, collector: Any):
        """Run a collector and handle restarts"""
        restart_count = 0
        max_restarts = 10
        
        while self._running and restart_count < max_restarts:
            try:
                await collector.start()
                # A CLEAN RETURN IS STILL A RESTART (FS-501). Only the `except` branch
                # counted and slept, so a `start()` that RETURNS rather than raises spun this
                # loop as fast as the scheduler allowed, for the life of the process — no
                # counter moving, no delay, nothing in the log. A collector that exits
                # normally on a closed connection is the ordinary case, not an exotic one.
                restart_count += 1
                logger.warning(
                    "collector_returned",
                    asset_id=asset_id,
                    restart_count=restart_count,
                    note="start() returned without raising; treating as a restart",
                )
                await asyncio.sleep(5)
            except Exception as e:
                restart_count += 1
                logger.error(
                    "collector_crashed",
                    asset_id=asset_id,
                    error=str(e),
                    restart_count=restart_count
                )
                await asyncio.sleep(5)  # Delay before restart
        
        if restart_count >= max_restarts:
            logger.error(
                "collector_max_restarts",
                asset_id=asset_id,
                max_restarts=max_restarts
            )
    
    async def _on_collector_message(self, message: Dict):
        """Handle message from any collector"""
        try:
            asset_id = message.get('asset_id', 'unknown')
            collector_type = message.get('collector_type', 'unknown')

            # Data-quality processing: validate -> scale -> normalize units ->
            # deadband. Passthrough when no pipeline is registered for this asset.
            #   DROP       -> suppressed by deadband/rate-limit; discard silently
            #   QUARANTINE -> invalid; buffer under the 'quarantine' topic (kept
            #                 out of local analytics) so the cloud can dead-letter it
            #   FORWARD    -> use the cleaned/normalized reading
            quality_action = None
            pipe = self._quality.get(asset_id)
            if pipe is not None:
                result = pipe.process(message)
                metrics.record_quality(asset_id, result.action.value, result.flags)
                if result.action == QualityAction.DROP:
                    return
                message = result.reading
                quality_action = result.action

            topic = message.get('topic', 'telemetry')
            if quality_action == QualityAction.QUARANTINE:
                topic = 'quarantine'

            # Add metadata
            enriched_message = {
                **message,
                '_coordinator_received_at': asyncio.get_event_loop().time(),
            }
            
            # Store in buffer for store-and-forward. StoreForwardBuffer.store()
            # keeps edge-time and takes the payload separately — same mapping as
            # EdgeAgent._buffer_message(). (Fixes a call to a non-existent
            # store_message() that dropped every collector reading.)
            ts_raw = message.get('timestamp_edge')
            try:
                if isinstance(ts_raw, datetime):
                    timestamp_edge = ts_raw
                elif ts_raw:
                    timestamp_edge = datetime.fromisoformat(ts_raw)
                else:
                    timestamp_edge = datetime.now(timezone.utc)
            except ValueError:
                timestamp_edge = datetime.now(timezone.utc)

            await self.buffer.store(
                timestamp_edge=timestamp_edge,
                asset_id=asset_id,
                topic=topic,
                payload=message.get('payload', {}),
                sequence_num=message.get('sequence_num', 0),
            )

            # Observability: count the reading and its end-to-edge age.
            # Coerce naive edge timestamps to UTC before the aware-now math
            # (FS-96): a naive-vs-aware TypeError here was swallowed by the
            # handler's catch-all and silently DROPPED the reading.
            ts_aware = (timestamp_edge if timestamp_edge.tzinfo
                        else timestamp_edge.replace(tzinfo=timezone.utc))
            metrics.record_message(
                asset_id, collector_type,
                age_seconds=max(
                    0.0,
                    (datetime.now(timezone.utc) - ts_aware).total_seconds(),
                ),
            )

            # Local analytics (OEE from PackML states, anomaly detection, alerting).
            # Quarantined (invalid) readings are excluded so bad data does not
            # skew OEE/anomaly baselines.
            if quality_action != QualityAction.QUARANTINE:
                analytics_pipeline.record(message)

            # THE IMMEDIATE FORWARD IS OFF, DELIBERATELY (FS-499).
            #
            # FS-495 found that this path raised on every message since the day it was
            # written, so the delivery behaviour production has ALWAYS had is
            # buffer-then-backfill. Fixing the serialisation turned the path on for the first
            # time — and it publishes to `telemetry.{asset}` while the contract, stated in
            # `edge-agent-statefulset.yaml:60-63` and parsed at `workers/ingestion.py:219`,
            # is `telemetry.{org}.{asset}`. The worker rejects anything with fewer than three
            # parts as `invalid_topic_format`, so every live message became a backend warning
            # and a dropped copy while the backfill copy arrived correctly.
            #
            # Correcting only the topic is worse, not better: nothing marks the buffered row
            # sent (`mark_sent` is called by the backfill loop alone, `main.py:357`), so a
            # correct live publish would deliver every reading TWICE.
            #
            # Making it real needs three things together — the org in the topic, an
            # ack-guaranteed send (`send_and_wait`, since `send()` only awaits batching), and
            # marking the row sent so backfill skips it. That is a change to the delivery
            # semantics of the core data path and belongs to whoever owns that decision, not
            # to a defect fix. Until then this stays off, which is exactly what has shipped
            # all along.
            #
            # `_forward_to_kafka` is kept, and correct, so the work above is a wiring change
            # rather than a rewrite.
            if IMMEDIATE_FORWARD_ENABLED and self.kafka_producer:
                try:
                    await self._forward_to_kafka(enriched_message)
                    metrics.record_kafka_success()
                    if self._forward_failing:
                        self._forward_failing = False
                        logger.info("immediate_forward_recovered", asset_id=asset_id)
                except Exception as e:
                    metrics.record_kafka_error()
                    # WARNING, NOT DEBUG (FS-496). The message is already buffered and the
                    # backfill path will deliver it, so this is not data loss — which is
                    # why it was written at `debug`. But that reasoning holds for ONE
                    # failure, not for a path that fails every time: FS-495 was a 100%
                    # failure rate that produced no visible signal for as long as it
                    # existed, because the only two witnesses were a debug line and a
                    # counter nobody alerts on.
                    #
                    # The first failure since the last success is logged at warning; the
                    # rest stay at debug so a genuinely offline broker does not flood the
                    # log with one line per message.
                    if not self._forward_failing:
                        self._forward_failing = True
                        logger.warning(
                            "immediate_forward_failed",
                            asset_id=asset_id,
                            error=str(e),
                            note="message is buffered; delivery falls back to backfill",
                        )
                    else:
                        logger.debug(
                            "immediate_forward_still_failing",
                            asset_id=asset_id,
                            error=str(e),
                        )
            
            logger.debug(
                "collector_message_received",
                asset_id=asset_id,
                type=collector_type
            )
            
        except Exception as e:
            metrics.record_error(
                message.get('asset_id', 'unknown'),
                message.get('collector_type', 'unknown'),
            )
            logger.error(
                "collector_message_handler_error",
                error=str(e),
                message_preview=str(message)[:200]
            )
    
    async def _forward_to_kafka(self, message: Dict):
        """Forward a message to Kafka.

        THE PRODUCER SERIALISES, NOT THIS (FS-495). `main.py:259` builds the producer with
        `value_serializer=lambda v: json.dumps(v).encode('utf-8')` and hands that same
        object here (`main.py:270`). This method used to `json.dumps(...).encode()` first
        and pass the bytes as the value, so aiokafka then ran `json.dumps(b'{...}')` —
        **TypeError: Object of type bytes is not JSON serializable, on every message**,
        since the day it was written.

        It cost delivery latency rather than data: the message is buffered before this is
        attempted and the backfill path serialises correctly, so everything arrived by the
        slow route. But the immediate path never once worked, and the failure went to
        `logger.debug` (see the caller, fixed in FS-496).

        No test could see it because the producer double in
        `tests/test_edge_agent_integration.py:47-55` stores `value` verbatim and applies no
        serializer — a fake that is wrong at exactly the seam that is broken.
        `tests/test_live_forward_survives_the_serializer.py` models the real contract.
        """
        asset_id = message.get('asset_id', 'unknown')
        topic = f"telemetry.{asset_id}"

        await self.kafka_producer.send(topic, message)
    
    async def _health_monitor(self):
        """Monitor health of all collectors"""
        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                # Check each collector
                for asset_id, task in list(self.collector_tasks.items()):
                    if task.done():
                        logger.warning(
                            "collector_task_done",
                            asset_id=asset_id,
                            result=str(task.result()) if not task.exception() else None,
                            exception=str(task.exception()) if task.exception() else None
                        )
                        
                        # Attempt restart if configured
                        config = self.configs.get(asset_id)
                        if config and config.enabled:
                            logger.info("restarting_collector", asset_id=asset_id)
                            await self._start_collector(config)
                
                # Log status
                active_count = sum(
                    1 for t in self.collector_tasks.values()
                    if not t.done()
                )
                metrics.refresh_collector_stats(active_count, len(self.configs))
                logger.info(
                    "collector_health_check",
                    active=active_count,
                    total=len(self.configs)
                )

                # Publish per-collector liveness (1=active task, 0=down).
                for aid, cfg in self.configs.items():
                    task = self.collector_tasks.get(aid)
                    metrics.set_connection_state(
                        aid, cfg.collector_type,
                        up=task is not None and not task.done(),
                    )

            except Exception as e:
                logger.error("health_monitor_error", error=str(e))
    
    async def stop_all(self):
        """Stop all collectors"""
        logger.info("stopping_all_collectors")
        self._running = False
        
        # Cancel health monitor
        if self._health_check_task:
            self._health_check_task.cancel()

        # And the supervisors (FS-502). `self._running = False` above lets each loop exit at
        # its next iteration, but a supervisor sitting in `await collector.start()` does not
        # reach that check — so without this, `stop_all` returns while supervisors are still
        # awaiting sockets the stop below is about to close.
        for task in getattr(self, "_collector_tasks", []):
            task.cancel()
        self._collector_tasks = []
        
        # Stop all collectors
        stop_tasks = []
        for asset_id, collector in self.collectors.items():
            try:
                task = asyncio.create_task(collector.stop())
                stop_tasks.append(task)
            except Exception as e:
                logger.error(
                    "collector_stop_error",
                    asset_id=asset_id,
                    error=str(e)
                )
        
        # Wait for all to stop
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        # Cancel all tasks
        for task in self.collector_tasks.values():
            if not task.done():
                task.cancel()
        
        logger.info("all_collectors_stopped")
    
    async def stop_collector(self, asset_id: str):
        """Stop and deregister a single collector (used by config hot-reload)."""
        logger.info("stopping_collector", asset_id=asset_id)
        collector = self.collectors.pop(asset_id, None)
        if collector is not None:
            try:
                await collector.stop()
            except Exception as e:  # best-effort; we are tearing it down anyway
                logger.error("collector_stop_error", asset_id=asset_id, error=str(e))
        task = self.collector_tasks.pop(asset_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def restart_collector(self, asset_id: str):
        """Restart a specific collector"""
        logger.info("restarting_collector", asset_id=asset_id)
        
        # Stop existing
        if asset_id in self.collectors:
            try:
                await self.collectors[asset_id].stop()
            except:
                pass
        
        if asset_id in self.collector_tasks:
            self.collector_tasks[asset_id].cancel()
        
        # Start new
        config = self.configs.get(asset_id)
        if config:
            await self._start_collector(config)
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all collectors"""
        return {
            'running': self._running,
            'total_collectors': len(self.configs),
            'active_collectors': sum(
                1 for t in self.collector_tasks.values()
                if not t.done()
            ),
            'collectors': {
                asset_id: {
                    'type': config.collector_type,
                    'enabled': config.enabled,
                    'running': (
                        asset_id in self.collector_tasks and
                        not self.collector_tasks[asset_id].done()
                    )
                }
                for asset_id, config in self.configs.items()
            }
        }
