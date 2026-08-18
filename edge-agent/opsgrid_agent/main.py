"""Edge Agent Main Module"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import structlog

from opsgrid_agent.analytics.alert_sink import LocalAlertSink
from opsgrid_agent.compression import compress
from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
from opsgrid_agent.commands import CommandConsumer
from opsgrid_agent.config_bundle import collectors_from_bundle
from opsgrid_agent.collectors.coordinator import UnifiedCollectorCoordinator, CollectorConfig
from opsgrid_agent.packml import PackMLStateMapper
from opsgrid_agent.resilience import ReconnectPolicy
from opsgrid_agent.ota import AgentSelfUpdateExecutor, OTAUpdateExecutor
from opsgrid_agent.remote_ops import (
    AgentRemoteOperations,
    capture_structured_log,
    structured_log_buffer,
)
from opsgrid_agent import metrics
from opsgrid_agent.versioning import (
    asset_ids_from_collectors,
    build_heartbeat_payload,
    build_manifest,
    compute_config_hash,
    persist_agent_state,
)

structlog.configure(
    processors=[
        capture_structured_log,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


#: Backfill pacing (FS-757). The old loop was `batch_size=100` then `sleep(5)`,
#: unconditionally — a hard ceiling of **20 messages per second** whether one row was
#: pending or four hundred thousand. That is not a throttle, it is the recovery rate, and it
#: is below the rate at which this agent's own collectors produce: at 50 msg/s ingest the
#: backlog grows forever with a perfectly healthy link.
#:
#: Measured against the 24-hour retention window, the ceiling is a data-loss mechanism
#: rather than a slowness: a 72-hour outage at 10 msg/s buffers 2.59M rows, which take 36
#: hours to drain, while retention deletes anything older than 24. The drain loses the race
#: to the cleaner, and the oldest readings — the ones the buffer exists to protect — go
#: first.
BACKFILL_IDLE_BATCH = 100
BACKFILL_MAX_BATCH = 5_000
BACKFILL_IDLE_SLEEP = 5.0
#: Not zero. A backlog drain must not starve the collector tasks sharing this event loop —
#: the readings still arriving are the ones with the best chance of being useful.
BACKFILL_DRAIN_SLEEP = 0.05

#: Consecutive backfill batches with zero successful sends before the uplink producer is
#: treated as dead and rebuilt (FS-756). Three rather than one because a single failed batch
#: is an ordinary transient — a leader election, a brief partition — and rebuilding on every
#: one would churn the connection at exactly the moment the broker is under stress.
UPLINK_DEAD_AFTER_BATCHES = 3


#: Exception type names that mean "the link failed", not "this message is bad" (FS-757).
#: Matched by name across the class hierarchy so aiokafka does not have to be importable
#: here — this module is loaded in environments where it is not, and an import guard that
#: silently classified everything as a message fault would be worse than no classifier.
_TRANSPORT_ERROR_NAMES = frozenset({
    "KafkaConnectionError", "ConnectionError", "ConnectionResetError",
    "ConnectionRefusedError", "BrokerNotAvailableError", "NodeNotReadyError",
    "RequestTimedOutError", "TimeoutError", "KafkaTimeoutError",
    "NotLeaderForPartitionError", "LeaderNotAvailableError",
    "CoordinatorNotAvailableError", "OSError", "SSLError",
})


def _is_transport_failure(exc: BaseException) -> bool:
    """Did the LINK fail, or did the broker reject this particular message? (FS-757)

    The distinction decides whether `retry_count` is incremented, and `retry_count` decides
    whether a row is ever drained again — five failures and `get_pending_messages` stops
    returning it. Counting a broker outage against individual messages means an outage
    silently condemns the backlog it created, which is the exact opposite of a
    store-and-forward buffer's purpose.

    A message-level rejection — too large, unserialisable, a topic the broker refuses — IS
    the message's fault, will fail identically forever, and should reach the dead-letter
    table. That is what the counter is for, and it keeps working.
    """
    for klass in type(exc).__mro__:
        if klass.__name__ in _TRANSPORT_ERROR_NAMES:
            return True
    return False


def _uplink_reconnect_settings() -> Optional[dict]:
    """Parse `UPLINK_RECONNECT` (JSON) into a `reconnect:` settings mapping (FS-756).

    Unset is the common case and means "use the shared defaults". A malformed value is a
    hard error rather than a fallback: an operator who set it meant to change something, and
    an agent that quietly ignores the setting they typed is how the uplink ends up retrying
    at a cadence nobody chose.
    """
    raw = os.getenv('UPLINK_RECONNECT')
    if not raw:
        return None
    try:
        settings = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"UPLINK_RECONNECT is not valid JSON: {e}") from e
    if not isinstance(settings, dict):
        raise ValueError(
            f"UPLINK_RECONNECT must be a JSON object, got {type(settings).__name__}"
        )
    return settings


class EdgeAgent:
    """
    Main Edge Agent coordinating collectors, buffering, and upstream communication.
    
    Responsibilities:
    - Manage multiple protocol collectors (MQTT, File, Screen, etc.)
    - Buffer messages locally during network outages
    - Backfill buffered messages when connection restored
    - Normalize states to PackML standard
    - Publish to message broker (Redpanda/Kafka)
    """
    
    def __init__(self):
        self.started_monotonic = time.monotonic()
        self.config = self._load_config()
        self.runtime_root = Path(self.config['runtime_root']).resolve()
        metrics.configure(agent_id=self.config['agent_id'])
        self.buffer = StoreForwardBuffer(
            buffer_path=self.config.get('buffer_path', '/var/lib/opsgrid-agent/buffer.db'),
            retention_hours=self.config.get('buffer_retention_hours', 24)
        )
        self.kafka_producer = None
        #: Consecutive backfill batches in which not one message landed (FS-756). Reset by
        #: any success; at `UPLINK_DEAD_AFTER_BATCHES` the producer is torn down so the
        #: supervisor can build a new one.
        self._uplink_failure_streak = 0
        #: True while the backfill worker is clearing a backlog (FS-757). Read by the
        #: cleanup worker, which suspends AGE-based expiry while it is set — retention
        #: deleting rows a drain has not reached yet is the loss this item is about.
        self._draining = False
        #: Set when the cloud link starts (FS-759). Declared here so `_serialize_uplink` has
        #: a defined answer before the first heartbeat, and on an agent with no cloud URL at
        #: all — both of which mean "raw only".
        self.heartbeat_reporter = None
        #: The batch size the backfill loop is currently using. Grows while there is more
        #: to send, falls back to idle when caught up.
        self._backfill_batch = BACKFILL_IDLE_BATCH
        self.command_consumer = None
        # ONE CLOCK ESTIMATOR, CREATED HERE RATHER THAN IN THE CLOUD LINK (FS-752).
        # It used to be built inside `_start_cloud_link`, which runs after the command
        # consumer and not at all when CLOUD_URL is unset. The consumer needs it to judge
        # whether a replayed command is stale — and the offline case is exactly when that
        # matters, so an estimator that only exists when the cloud does would be absent
        # precisely when it is needed. Uncalibrated is a meaningful state, not a missing
        # one: the consumer tightens its freshness window when the clock has never been
        # set against a trusted source.
        from opsgrid_agent.timesync import ClockSkewEstimator
        self._skew = ClockSkewEstimator()
        self.ota_executor = OTAUpdateExecutor(
            buffer=self.buffer,
            signing_public_key=self.config.get('ota_signing_public_key', ''),
            active_bundle_path=self.config.get(
                'ota_config_bundle_path',
                '/var/lib/opsgrid-agent/config_bundle.active',
            ),
            staging_dir=self.config.get(
                'ota_staging_dir',
                '/var/lib/opsgrid-agent/ota-staging',
            ),
            drain_timeout_seconds=self.config.get('ota_drain_timeout_seconds', 60),
            restart_callback=self._restart_runtime_after_update,
            bundle_validator=self._validate_config_bundle,
        )
        #: Buffer counters the heartbeat reports (FS-497), refreshed by `_stats_reporter`.
        #: Cached rather than queried because `_health_snapshot` is sync — it also serves the
        #: HTTP health server from another thread — while the buffer's `get_stats` is async.
        #: Zeros until the first stats pass, which is honest: nothing has been measured yet.
        self._buffer_snapshot: Dict[str, Any] = {}
        self.agent_update_executor = AgentSelfUpdateExecutor(
            buffer=self.buffer,
            signing_public_key=self.config.get('ota_signing_public_key', ''),
            runtime_root=str(self.runtime_root),
            drain_timeout_seconds=self.config.get('ota_drain_timeout_seconds', 60),
            preflight_timeout_seconds=self.config.get(
                'ota_agent_preflight_timeout_seconds',
                30,
            ),
            max_artifact_bytes=self.config.get(
                'ota_agent_artifact_max_bytes',
                64 * 1024 * 1024,
            ),
            max_uncompressed_bytes=self.config.get(
                'ota_agent_artifact_max_uncompressed_bytes',
                256 * 1024 * 1024,
            ),
            bootstrap_version=self.config.get('bootstrap_version', '1.0.0'),
            restart_callback=(
                self._request_process_restart
                if self.config.get('bootstrap_managed')
                else None
            ),
        )
        self._running = False
        self._restart_requested = asyncio.Event()
        self._tasks: List[asyncio.Task] = []
        self.config_hash = compute_config_hash(self.config.get('collectors', []))
        self.manifest = build_manifest(
            list(UnifiedCollectorCoordinator.SUPPORTED_COLLECTORS)
        )
        expected_running_version = os.getenv('OPSGRID_RUNNING_VERSION')
        if (
            self.config.get('bootstrap_managed')
            and expected_running_version
            and expected_running_version != self.manifest['agent_version']
        ):
            raise RuntimeError(
                "Bootstrap selected agent version "
                f"{expected_running_version}, but the package reports "
                f"{self.manifest['agent_version']}"
            )
        self.state_path = self.config.get('state_path') or str(
            Path(self.config['buffer_path']).with_name('agent_state.json')
        )
        
        # Durable local alarm storage (FS-755), beside the buffer but in its own file so
        # the buffer's size cap can never shed an alarm to make room for telemetry.
        self.alert_sink = LocalAlertSink(
            Path(self.config['buffer_path']).with_name('local_alerts.db'),
            retention_days=int(self.config.get('alert_retention_days', 30)),
        )

        # Initialize collector coordinator
        self.coordinator = UnifiedCollectorCoordinator(
            buffer=self.buffer,
            kafka_producer=None,  # Will be set after Kafka init
            alert_sink=self.alert_sink,
        )
        self.remote_operations = AgentRemoteOperations(
            agent_id=self.config['agent_id'],
            config_provider=lambda: self.config,
            manifest_provider=lambda: self.manifest,
            config_hash_provider=lambda: self.config_hash,
            buffer=self.buffer,
            coordinator=self.coordinator,
            kafka_connected=lambda: self.kafka_producer is not None,
            command_connected=lambda: bool(
                self.command_consumer
                and self.command_consumer.is_running
            ),
            log_buffer=structured_log_buffer,
            started_monotonic=self.started_monotonic,
        )
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from environment"""
        config = {
            'organization_id': os.getenv('ORGANIZATION_ID', 'dev-org'),
            'agent_id': os.getenv('AGENT_ID', 'agent-001'),
            'redpanda_url': os.getenv('REDPANDA_URL', 'localhost:9092'),
            'agent_status_topic': os.getenv('AGENT_STATUS_TOPIC', 'opsgrid.agent-status'),
            'heartbeat_interval_seconds': int(os.getenv('HEARTBEAT_INTERVAL_SECONDS', '60')),
            'command_topic': os.getenv('REDPANDA_COMMAND_TOPIC', 'opsgrid.commands'),
            'command_ack_topic': os.getenv('REDPANDA_COMMAND_ACK_TOPIC', 'opsgrid.commands.acks'),
            'command_dlq_topic': os.getenv('REDPANDA_COMMAND_DLQ_TOPIC', 'opsgrid.commands.dlq'),
            'ota_signing_public_key': os.getenv('OTA_SIGNING_PUBLIC_KEY', ''),
            'ota_config_bundle_path': os.getenv(
                'OTA_CONFIG_BUNDLE_PATH',
                '/var/lib/opsgrid-agent/config_bundle.active',
            ),
            'ota_staging_dir': os.getenv(
                'OTA_STAGING_DIR',
                '/var/lib/opsgrid-agent/ota-staging',
            ),
            'ota_drain_timeout_seconds': int(os.getenv('OTA_DRAIN_TIMEOUT_SECONDS', '60')),
            'ota_agent_preflight_timeout_seconds': int(
                os.getenv('OTA_AGENT_PREFLIGHT_TIMEOUT_SECONDS', '30')
            ),
            'ota_agent_artifact_max_bytes': int(
                os.getenv('OTA_AGENT_ARTIFACT_MAX_BYTES', str(64 * 1024 * 1024))
            ),
            'ota_agent_artifact_max_uncompressed_bytes': int(
                os.getenv(
                    'OTA_AGENT_ARTIFACT_MAX_UNCOMPRESSED_BYTES',
                    str(256 * 1024 * 1024),
                )
            ),
            'runtime_root': os.getenv(
                'OPSGRID_RUNTIME_ROOT',
                '/var/lib/opsgrid-agent/runtime',
            ),
            'bootstrap_version': os.getenv('OPSGRID_BOOTSTRAP_VERSION', '1.0.0'),
            'bootstrap_managed': (
                os.getenv('OPSGRID_BOOTSTRAP_MANAGED', 'false').lower() == 'true'
            ),
            'require_boot_health': (
                os.getenv('OPSGRID_REQUIRE_BOOT_HEALTH', 'false').lower() == 'true'
            ),
            'bootstrap_ready_file': os.getenv('OPSGRID_BOOTSTRAP_READY_FILE'),
            'buffer_path': os.getenv('BUFFER_PATH', '/var/lib/opsgrid-agent/buffer.db'),
            'state_path': os.getenv('AGENT_STATE_PATH'),
            'buffer_retention_hours': int(os.getenv('BUFFER_RETENTION_HOURS', '24')),
            'alert_retention_days': int(os.getenv('ALERT_RETENTION_DAYS', '30')),
            # FS-756. A JSON `reconnect:` block for the uplink supervisor, in the same shape
            # a collector takes. ONE variable rather than seven, so a site tunes the uplink
            # the way it tunes a collector, and `ReconnectPolicy.from_config` rejects an
            # unknown key rather than silently keeping the default — which is the failure
            # mode every config defect in this repository has had.
            #
            # Read here rather than in the supervisor so a malformed value fails at load,
            # where an operator is watching, instead of inside a background task where the
            # only symptom is an uplink that never reconnects.
            'uplink': {'reconnect': _uplink_reconnect_settings()},
            'collectors': self._load_collectors(),
        }
        self._load_active_config_bundle(config)
        return config

    def _load_collectors(self) -> List[Dict[str, Any]]:
        """Load and validate collector definitions.

        Source precedence: ``COLLECTORS_FILE`` (YAML path) if set, otherwise the
        ``COLLECTORS`` env var (JSON). Each entry is envelope-validated; invalid
        entries are logged and skipped rather than crashing the agent.
        """
        collectors_file = os.getenv('COLLECTORS_FILE')
        try:
            if collectors_file:
                import yaml  # lazy: only needed when COLLECTORS_FILE is set
                with open(collectors_file) as f:
                    doc = yaml.safe_load(f) or {}
                raw = doc.get('collectors', []) if isinstance(doc, dict) else (doc or [])
            else:
                raw = json.loads(os.getenv('COLLECTORS', '[]'))
        except (OSError, ValueError) as e:
            logger.error(
                "collectors_config_load_failed",
                source=collectors_file or 'env',
                error=str(e),
            )
            return []

        from opsgrid_agent.config_schema import CollectorEntry
        normalized: List[Dict[str, Any]] = []
        for entry in raw:
            try:
                normalized.append(
                    CollectorEntry.model_validate(entry).model_dump(by_alias=True)
                )
            except Exception as e:
                logger.error("invalid_collector_config", entry=entry, error=str(e))
        return normalized

    def _validate_config_bundle(self, bundle: bytes) -> None:
        collectors_from_bundle(bundle)

    def _load_active_config_bundle(self, config: Dict[str, Any]) -> None:
        bundle_path = Path(config['ota_config_bundle_path'])
        if not bundle_path.exists():
            return

        collectors = collectors_from_bundle(bundle_path.read_bytes())
        config['collectors'] = collectors
        logger.info(
            "config_bundle_loaded",
            path=str(bundle_path),
            collectors=len(collectors),
        )

    def register_command_handler(self, action_id: str, handler):
        """Register a remote command handler."""
        if self.command_consumer is None:
            self._init_command_consumer()
        self.command_consumer.register_handler(action_id, handler)

    def _asset_ids(self) -> List[str]:
        return [
            str(collector.get('asset_id'))
            for collector in self.config.get('collectors', [])
            if collector.get('asset_id')
        ]

    def _init_command_consumer(self):
        """Initialize command transport without starting network I/O."""
        if self.command_consumer is None:
            self.command_consumer = CommandConsumer(
                agent_id=self.config['agent_id'],
                organization_id=self.config['organization_id'],
                asset_ids=self._asset_ids(),
                redpanda_url=self.config['redpanda_url'],
                command_topic=self.config['command_topic'],
                ack_topic=self.config['command_ack_topic'],
                dlq_topic=self.config['command_dlq_topic'],
                clock=self._skew,
            )
            self.ota_executor.register(self.command_consumer)
            self.agent_update_executor.register(self.command_consumer)
            self.remote_operations.register(self.command_consumer)

    async def _restart_runtime_after_update(self):
        """Restart collectors after an OTA config-bundle swap."""
        await self.coordinator.stop_all()
        self.config = self._load_config()
        self.config_hash = compute_config_hash(self.config.get('collectors', []))
        self.coordinator.configs.clear()
        self.coordinator.collectors.clear()
        self.coordinator.collector_tasks.clear()
        if self.command_consumer:
            self.command_consumer.asset_ids = set(self._asset_ids())
        await self._initialize_collectors()
        await self.coordinator.start_all()

    async def _request_process_restart(self):
        """Tell the stable bootstrap to switch to the staged agent version."""
        logger.info(
            "agent_process_restart_requested",
            running_version=self.manifest['agent_version'],
        )
        self._restart_requested.set()

    def request_shutdown(self):
        """Wake the run loop for an orderly external shutdown."""
        self._restart_requested.set()
    
    def _load_identity(self):
        """The agent's key/cert identity, loaded once and shared.

        One instance serves both the cloud link (enrollment/heartbeat) and the
        Kafka TLS context, so rotation updates and the producer always see the
        same certificate rather than two independently-loaded copies.
        """
        if getattr(self, '_identity', None) is None:
            from opsgrid_agent.security.identity import AgentIdentity
            self._identity = AgentIdentity(
                os.getenv('IDENTITY_DIR', '/var/lib/opsgrid-agent/identity')
            ).load_or_create()
        return self._identity

    def _uplink_ssl_context(self):
        """SSL context for the Kafka uplink, honoring the TLS enforcement flag.

        Returns None for plaintext (dev/legacy). With KAFKA_SECURITY_PROTOCOL=SSL
        the enrolled identity's mTLS context is used; EDGE_REQUIRE_TLS=true
        additionally makes any failure to produce a context FATAL (fail closed)
        rather than degrading to plaintext.
        """
        require_tls = os.getenv('EDGE_REQUIRE_TLS', 'false').lower() == 'true'
        protocol = os.getenv('KAFKA_SECURITY_PROTOCOL', 'PLAINTEXT').upper()
        if not require_tls and protocol != 'SSL':
            return None

        from opsgrid_agent.security.mtls import build_client_context
        # Raises MTLSNotReady when unenrolled or (strict) missing CA bundle;
        # in require_tls mode the caller lets that abort startup.
        return build_client_context(self._load_identity(), strict=require_tls)

    async def _init_kafka_producer(self) -> bool:
        """Initialize Kafka/Redpanda producer (TLS when configured)."""
        require_tls = os.getenv('EDGE_REQUIRE_TLS', 'false').lower() == 'true'
        try:
            from aiokafka import AIOKafkaProducer

            ssl_context = self._uplink_ssl_context()
            kwargs = dict(
                bootstrap_servers=self.config['redpanda_url'],
                value_serializer=self._serialize_uplink,
                key_serializer=lambda k: k.encode('utf-8') if k else None,
            )
            if ssl_context is not None:
                kwargs['security_protocol'] = 'SSL'
                kwargs['ssl_context'] = ssl_context

            self.kafka_producer = AIOKafkaProducer(**kwargs)
            await self.kafka_producer.start()

            # Set coordinator's Kafka producer
            self.coordinator.kafka_producer = self.kafka_producer

            logger.info(
                "kafka_producer_started",
                brokers=self.config['redpanda_url'],
                tls=ssl_context is not None,
            )
            return True
        except Exception as e:
            if require_tls:
                # Fail closed: a required-TLS agent must not run with a broken
                # or absent secure uplink (store-and-forward would queue data
                # that could only ever leave in plaintext).
                logger.critical("kafka_tls_required_but_unavailable", error=str(e))
                raise
            logger.error("kafka_producer_failed", error=str(e))
            self.kafka_producer = None
            return False
    
    def _serialize_uplink(self, value) -> bytes:
        """JSON, then framed and compressed if the backend said it can decode it (FS-759).

        `compression.py` has been correct and tested since task 22 and had never been called
        by anything, because the receiving half did not exist — the agent's orphan register
        recorded it as "half a protocol, not unfinished wiring". The backend decoder now
        exists (`backend/app/services/wire_codec.py`), so this is the wiring.

        `_negotiated_codecs()` is raw-only until a heartbeat ack advertises otherwise. That
        default is load-bearing rather than cautious: a new agent pointed at an older backend
        would emit bytes it cannot parse, and the buffer marks a row sent the moment the
        broker accepts it — so the readings would be gone, not delayed, which is the one
        outcome store-and-forward exists to prevent.
        """
        body = json.dumps(value).encode("utf-8")
        framed, _ = compress(body, allowed=self._negotiated_codecs())
        return framed

    def _negotiated_codecs(self) -> tuple:
        reporter = getattr(self, "heartbeat_reporter", None)
        return getattr(reporter, "wire_codecs", ("raw",))

    async def _uplink_supervisor(self):
        """Keep trying to build the uplink producer while there is none (FS-756).

        THE DEFECT. `_init_kafka_producer` is called exactly once, from `start()`. When the
        broker is unreachable at that moment it logs, sets `self.kafka_producer = None` and
        returns False — and nothing ever calls it again. `_backfill_worker` then runs its
        whole life around `if self.kafka_producer:`, which is permanently false, so the
        buffer fills and drains nothing until somebody restarts the process.

        That is precisely the DDIL case inverted. An edge gateway powering up during an
        outage — a site coming back after a power cut, a van rolling out of coverage before
        it rolls back in — is the ordinary way for this to happen, not an edge case. The
        agent collected data correctly, buffered it correctly, and then held it forever
        after the link returned, because the one attempt it was allowed had already failed.

        REUSES `ReconnectPolicy` rather than a fresh `sleep(30)`, for the reason FS-473
        wrote it: eight collectors had already grown their own copies of the same constants.
        The uplink is the ninth reconnect loop in this agent and the only one that was not a
        collector, which is exactly why the existing guard did not cover it.

        FAILS OPEN HERE, unlike boot. `_init_kafka_producer` re-raises when `EDGE_REQUIRE_TLS`
        is set and TLS is unavailable, so that a required-TLS agent refuses to START with a
        broken secure uplink. Post-boot the agent is already running and already buffering;
        killing this task on that exception would silently restore the exact
        never-reconnects behaviour being fixed. So it is caught, counted as a failure, and
        retried — the data stays in the buffer either way, which is the fail-closed property
        that actually matters.
        """
        policy = ReconnectPolicy.from_config(self.config.get('uplink'))
        backoff, breaker = policy.instruments("uplink")

        while self._running:
            if self.kafka_producer is not None:
                backoff.reset()
                breaker.record_success()
                # Poll at the backoff CEILING while healthy, not at its floor. A supervisor
                # that wakes every second for the life of the agent to observe that nothing
                # is wrong is a cost with no benefit; a producer torn down by the backfill
                # worker is picked up within one ceiling and then retried from 1s.
                await asyncio.sleep(policy.max_delay)
                continue

            if not breaker.allow():
                await asyncio.sleep(max(breaker.time_until_retry(), policy.initial_delay))
                continue

            try:
                connected = await self._init_kafka_producer()
            except Exception as e:
                # Includes the require-TLS re-raise; see the docstring.
                logger.error("uplink_reconnect_attempt_failed", error=str(e))
                connected = False

            if connected:
                backoff.reset()
                breaker.record_success()
                # FS-757. The counts were failures against a producer that no longer
                # exists; carrying them over means the new link inherits the old one's
                # verdict and the first drain skips rows that failed five times against a
                # broker that has since come back.
                cleared = await self.buffer.reset_retry_counts()
                logger.info(
                    "uplink_reconnected",
                    retry_counts_cleared=cleared,
                    note="buffered readings will drain on the next backfill cycle",
                )
                # EVERY BRANCH AWAITS BEFORE LOOPING. This one used to `continue` straight
                # to the healthy check, which sleeps — correct, but it made the loop's only
                # protection against spinning live in a different branch. A mutation that
                # disabled the healthy check turned this into a hot loop that wedged the
                # test run, which is a fair demonstration of how thin that arrangement was.
                await asyncio.sleep(policy.max_delay)
                continue

            breaker.record_failure()
            delay = backoff.next_delay()
            logger.warning(
                "uplink_reconnect_pending",
                retry_in_seconds=round(delay, 1),
                breaker=breaker.state.value,
            )
            await asyncio.sleep(delay)

    async def _recycle_uplink(self) -> None:
        """Discard a producer that is no longer delivering, so the supervisor rebuilds it.

        Stopping it is best-effort by design: the reason we are here is that the broker is
        unreachable, and `stop()` talks to the broker. An exception must not prevent the
        one step that matters — setting the reference to None — or the recycle silently
        does nothing and the zombie producer stays installed.
        """
        logger.error(
            "uplink_declared_dead",
            consecutive_failed_batches=self._uplink_failure_streak,
            note="tearing the producer down; the supervisor will rebuild it with backoff",
        )
        try:
            await self._stop_kafka_producer()
        except Exception as e:
            logger.warning("uplink_stop_failed_during_recycle", error=str(e))
        self.kafka_producer = None
        self.coordinator.kafka_producer = None
        self._uplink_failure_streak = 0

    async def _stop_kafka_producer(self):
        """Stop Kafka producer"""
        if self.kafka_producer:
            await self.kafka_producer.stop()
            logger.info("kafka_producer_stopped")
    
    async def _backfill_worker(self):
        """Background task to backfill buffered messages"""
        logger.info("backfill_worker_started")
        
        while self._running:
            try:
                if self.kafka_producer:
                    # ADAPTIVE (FS-757). A fixed batch of 100 followed by a fixed 5-second
                    # sleep is a 20 msg/s ceiling regardless of how much is pending, which
                    # is below this agent's own ingest rate at 50 msg/s — the backlog grows
                    # forever on a healthy link — and loses the race to the 24-hour
                    # retention cleaner on any outage longer than about a day.
                    messages = await self.buffer.get_pending_messages(
                        batch_size=self._backfill_batch
                    )
                    
                    if messages:
                        logger.info(
                            "backfilling_messages",
                            count=len(messages)
                        )
                        
                        sent_ids = []
                        failed_ids = []
                        message_fault_ids = []
                        transport_failed = 0

                        for msg in messages:
                            try:
                                topic = f"telemetry.{self.config['organization_id']}.{msg.asset_id}"

                                payload = json.loads(msg.payload)
                                value = {
                                    'timestamp_edge': msg.timestamp_edge,
                                    'asset_id': msg.asset_id,
                                    'payload': payload,
                                    'sequence_num': msg.sequence_num,
                                    'backfilled': True
                                }
                                # Preserve PackML state through backfill: the
                                # backend ingestion reads packml_state at the top
                                # level, and collectors persist it inside payload.
                                # Without this, backfilled telemetry loses its
                                # state and breaks backend/historical OEE.
                                packml_state = payload.get('packml_state') if isinstance(payload, dict) else None
                                if packml_state is not None:
                                    value['packml_state'] = packml_state

                                await self.kafka_producer.send(
                                    topic,
                                    value=value,
                                    key=msg.asset_id
                                )
                                sent_ids.append(msg.id)
                                metrics.record_kafka_success()
                            
                            except Exception as e:
                                logger.error(
                                    "backfill_send_failed",
                                    message_id=msg.id,
                                    error=str(e)
                                )
                                failed_ids.append(msg.id)
                                if _is_transport_failure(e):
                                    transport_failed += 1
                                else:
                                    message_fault_ids.append(msg.id)
                                metrics.record_kafka_error()
                        
                        # Mark sent messages as complete
                        if sent_ids:
                            await self.buffer.mark_sent(sent_ids)
                        
                        # RETRY IS COUNTED AGAINST THE MESSAGE, NOT THE LINK (FS-757).
                        # `get_pending_messages` filters `retry_count < 5`, so a row that
                        # fails five times stops being drained at all. Counting a broker
                        # outage against individual rows means an outage condemns the
                        # backlog it created — five failures against a broker that is
                        # reachable but rejecting is an ordinary degraded reconnect. A
                        # message the broker refuses on its own merits still counts, still
                        # dead-letters, and is why the counter continues to exist.
                        if message_fault_ids:
                            await self.buffer.increment_retry(message_fault_ids)
                        if transport_failed:
                            logger.warning(
                                "backfill_transport_failures_not_counted",
                                count=transport_failed,
                                note="the link failed, not these messages; "
                                     "retry_count is unchanged so they stay drainable",
                            )

                        # A PRODUCER OBJECT IS NOT A WORKING UPLINK (FS-756). The
                        # supervisor rebuilds a producer that is None; nothing sets it to
                        # None once it exists. So a broker that dies AFTER a successful
                        # boot leaves an object here that fails every send forever, and
                        # `if self.kafka_producer:` above stays true the whole time — the
                        # never-reconnects defect with an extra step.
                        #
                        # Whole batches, not individual sends: one failure is an ordinary
                        # transient, three consecutive batches where NOTHING landed is a
                        # dead link. Tearing the producer down hands it to the supervisor,
                        # which retries with backoff instead of this loop's fixed 5s.
                        #
                        # This also bounds the damage from the retry counter: every failed
                        # send increments `retry_count`, and a row that reaches 5 stops
                        # appearing in any drain (recorded under FS-753). Recycling a dead
                        # producer after 3 batches rather than never is the difference
                        # between losing a backlog and delaying it.
                        if sent_ids:
                            self._uplink_failure_streak = 0
                        else:
                            self._uplink_failure_streak += 1
                            if self._uplink_failure_streak >= UPLINK_DEAD_AFTER_BATCHES:
                                await self._recycle_uplink()

                    # PACE FROM THE BACKLOG, NOT FROM A CONSTANT (FS-757).
                    #
                    # A full batch means `get_pending_messages` had at least as many rows
                    # as we asked for, so there is more waiting: grow the batch and take
                    # the short sleep. A short batch means we have caught up: fall back to
                    # the idle size and cadence so a quiet agent is not spinning.
                    #
                    # The short sleep is 0.05s rather than 0, deliberately. A drain that
                    # never yields starves the collector tasks on this event loop, and the
                    # readings still arriving are the ones most likely to matter.
                    caught_up = len(messages) < self._backfill_batch
                    if caught_up:
                        self._backfill_batch = BACKFILL_IDLE_BATCH
                        if self._draining:
                            self._draining = False
                            logger.info(
                                "backfill_drained",
                                note="retention resumes; the backlog is cleared",
                            )
                        await asyncio.sleep(BACKFILL_IDLE_SLEEP)
                    else:
                        if not self._draining:
                            self._draining = True
                            logger.warning(
                                "backfill_draining",
                                batch=self._backfill_batch,
                                note="age-based retention is suspended until this clears",
                            )
                        self._backfill_batch = min(
                            self._backfill_batch * 2, BACKFILL_MAX_BATCH
                        )
                        await asyncio.sleep(BACKFILL_DRAIN_SLEEP)
                else:
                    # No producer. The supervisor is working on it; do not spin.
                    self._draining = False
                    await asyncio.sleep(BACKFILL_IDLE_SLEEP)

            except Exception as e:
                logger.error("backfill_worker_error", error=str(e))
                await asyncio.sleep(10)
    
    async def _cleanup_worker(self):
        """Background task for periodic cleanup"""
        while self._running:
            try:
                # AGE-BASED EXPIRY IS SUSPENDED DURING A DRAIN (FS-757).
                #
                # Retention deletes rows older than `retention_hours`. A backlog being
                # drained is, by definition, made of the oldest rows in the buffer — so
                # while a recovery is in progress the cleaner and the drain are racing for
                # the same rows, and at the old 20 msg/s ceiling the cleaner won: a 72-hour
                # outage at 10 msg/s needs 36 hours to drain against a 24-hour window.
                #
                # The bound is not removed, it is CHANGED. `enforce_size_limit` below still
                # runs every cycle, and since FS-754 it sheds by priority — so a buffer that
                # cannot drain still gives up debug and bulk telemetry to stay within its
                # disk cap, and still keeps its alarms. Shedding the cheapest data is a
                # better answer than shedding the oldest, which is all age can express.
                if self._draining:
                    logger.info(
                        "retention_suspended_during_drain",
                        note="the size cap still applies and sheds by priority",
                    )
                    deleted = 0
                else:
                    deleted = await self.buffer.cleanup_old_messages()
                    metrics.record_expired(deleted)
                    if deleted > 0:
                        logger.info("cleanup_completed", deleted_messages=deleted)

                # Dead-letter retry-exhausted messages so they stop accumulating.
                dead = await self.buffer.move_exhausted_to_dead_letter(max_retry=5)
                metrics.record_dead_lettered(dead)

                # Enforce the on-disk size cap (drops oldest; also vacuums).
                dropped = await self.buffer.enforce_size_limit()
                metrics.record_dropped(dropped)

                # Wait 1 hour before next cleanup
                await asyncio.sleep(3600)

            except Exception as e:
                logger.error("cleanup_worker_error", error=str(e))
                await asyncio.sleep(3600)

    async def _heartbeat_payload(self) -> Dict[str, Any]:
        status = self.coordinator.get_status()
        update_status = self._safe_update_status()
        return build_heartbeat_payload(
            agent_id=self.config['agent_id'],
            organization_id=self.config['organization_id'],
            asset_ids=asset_ids_from_collectors(self.config.get('collectors', [])),
            manifest=self.manifest,
            config_hash=self.config_hash,
            collector_status=status,
            update_status=update_status,
        )

    async def _publish_heartbeat(self, *, required: bool = False):
        """Publish a best-effort fleet status heartbeat."""
        if not self.kafka_producer:
            if required:
                raise RuntimeError("Kafka producer unavailable for boot heartbeat")
            logger.debug("heartbeat_skipped_no_kafka")
            return False

        payload = await self._heartbeat_payload()
        if hasattr(self.kafka_producer, 'send_and_wait'):
            await self.kafka_producer.send_and_wait(
                self.config['agent_status_topic'],
                value=payload,
                key=self.config['agent_id'],
            )
        else:
            await self.kafka_producer.send(
                self.config['agent_status_topic'],
                value=payload,
                key=self.config['agent_id'],
            )
        logger.debug(
            "agent_heartbeat_published",
            topic=self.config['agent_status_topic'],
            agent_id=self.config['agent_id'],
            asset_count=len(payload['asset_ids']),
        )
        return True

    def _safe_update_status(self) -> Dict[str, Any]:
        try:
            journal = self.agent_update_executor.load_journal()
        except Exception as exc:
            logger.warning("agent_update_journal_unreadable", error=str(exc))
            return {"status": "journal_error", "running_version": self.manifest["agent_version"]}
        if not journal:
            return {}
        allowed = (
            "status",
            "phase",
            "attempted_version",
            "previous_version",
            "running_version",
            "rolled_back",
        )
        return {
            key: journal[key]
            for key in allowed
            if journal.get(key) not in (None, "")
        }

    async def _heartbeat_worker(self):
        """Background worker for fleet version/config visibility."""
        while self._running:
            try:
                await self._publish_heartbeat()
                await asyncio.sleep(self.config['heartbeat_interval_seconds'])
            except Exception as e:
                logger.warning("agent_heartbeat_failed", error=str(e))
                await asyncio.sleep(self.config['heartbeat_interval_seconds'])
    
    async def _stats_reporter(self):
        """Periodic stats reporting"""
        # Baseline stamp (FS-694): the staleness alert measures time() minus the
        # last-success timestamp, and a loop that NEVER succeeds would otherwise never
        # create the series — leaving the alert nothing to evaluate, which is the same
        # absent-series trap EdgeCollectorFailingEveryPoll's `unless` exists for. Stamping
        # here means "stats were current as of startup", after which the age grows
        # honestly until the first real success resets it.
        metrics.buffer_stats_last_success.set(time.time())
        while self._running:
            try:
                stats = await self.buffer.get_stats()
                metrics.set_buffer_stats(
                    pending=stats['total_messages'],
                    backfill_lag_seconds=stats.get('backfill_lag_seconds', 0.0),
                )
                # Converged: also publish integration's agent-level gauges.
                status = self.coordinator.get_status()
                # Cached for `_health_snapshot`, which is sync and cannot await the buffer
                # (FS-497). Refreshed on this loop's cadence, which is also the cadence the
                # buffer-depth alert reasons about.
                self._buffer_snapshot = {
                    "pending": stats.get('total_messages', 0),
                    "dead_lettered": stats.get('dead_lettered', 0),
                    "dropped": stats.get('dropped', 0),
                }
                metrics.refresh_buffer_stats(stats['total_messages'])
                metrics.refresh_collector_stats(
                    status['active_collectors'],
                    status['total_collectors'],
                )
                logger.info(
                    "buffer_stats",
                    total_messages=stats['total_messages'],
                    failed_messages=stats['failed_messages'],
                    dead_lettered=stats.get('dead_lettered', 0),
                    size_mb=stats['size_mb'],
                    backfill_lag_seconds=stats.get('backfill_lag_seconds', 0.0),
                    oldest_message=stats['oldest_message'],
                    newest_message=stats['newest_message']
                )

                await asyncio.sleep(300)  # Report every 5 minutes
            
            except Exception as e:
                logger.error("stats_reporter_error", error=str(e))
                await asyncio.sleep(300)
    
    async def _initialize_collectors(self):
        """Initialize collectors from configuration"""
        collectors_config = self.config.get('collectors', [])
        
        if not collectors_config:
            logger.warning("no_collectors_configured")
            return
        
        for collector_conf in collectors_config:
            try:
                asset_id = collector_conf.get('asset_id')
                collector_type = collector_conf.get('type') or collector_conf.get('collector_type')
                
                if not asset_id or not collector_type:
                    logger.error("invalid_collector_config", config=collector_conf)
                    continue
                
                # Create collector config
                collector_config = collector_conf.get('config', {})
                config = CollectorConfig(
                    collector_type=collector_type,
                    asset_id=asset_id,
                    config=collector_config,
                    enabled=collector_conf.get('enabled', True)
                )

                # Register any local alert rules declared for this asset.
                from opsgrid_agent.analytics import alerting_tracker, oee_tracker
                alerting_tracker.configure(asset_id, collector_config.get('alerts'))

                # And the machine's rated cycle time, without which local performance
                # cannot be computed (FS-463). Same key the backend reads per asset.
                oee_tracker.configure(
                    asset_id,
                    (collector_config.get('oee') or {}).get('ideal_cycle_time_seconds'),
                )

                # Register with coordinator
                self.coordinator.register_collector(config)
                
                logger.info(
                    "collector_registered",
                    asset_id=asset_id,
                    type=collector_type
                )
            
            except Exception as e:
                logger.error(
                    "collector_registration_failed",
                    config=collector_conf,
                    error=str(e)
                )

    def _assert_collectors_healthy(self):
        expected = sum(
            1
            for config in self.coordinator.configs.values()
            if config.enabled
        )
        status = self.coordinator.get_status()
        if status['active_collectors'] != expected:
            raise RuntimeError(
                "Collector self-check failed: "
                f"{status['active_collectors']} of {expected} enabled collectors are running"
            )

    def _requires_boot_health(self) -> bool:
        if self.config.get('require_boot_health'):
            return True
        try:
            status = self.agent_update_executor.load_journal().get('status')
        except Exception:
            return True
        return status in {
            "switch_requested",
            "restart_requested",
            "booting",
            "rollback_booting",
        }

    def _mark_boot_ready(self):
        if not self.config.get('bootstrap_managed'):
            return
        configured_path = self.config.get('bootstrap_ready_file')
        ready_path = Path(configured_path) if configured_path else (
            self.runtime_root / 'boot-ready.json'
        )
        persist_agent_state(
            ready_path,
            {
                "agent_version": self.manifest["agent_version"],
                "pid": os.getpid(),
                "ready_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    
    def _health_snapshot(self) -> Dict[str, Any]:
        """Synchronous health for /healthz (called from the HTTP server thread).

        Uses only sync, thread-safe reads (coordinator.get_status() + the running
        flag) — no awaiting the async buffer from off the event loop.
        """
        try:
            status = self.coordinator.get_status()
        except Exception:  # pragma: no cover - defensive
            status = {}
        # THE KEY NAMES ARE THE HEARTBEAT'S (FS-497). This returned `collectors_total` and
        # `collectors_active` and no buffer keys at all, while `heartbeat.build_payload`
        # reads `active_collectors`, `total_collectors`, `buffer_pending`, `dead_lettered`
        # and `dropped` (`heartbeat.py:48-52`). Every field defaulted, so **every heartbeat
        # this agent has ever sent reported five zeros** — and the backend feeds
        # `edge_agent_buffer_pending` from one of them (`app/services/edge_fleet.py:69`),
        # so `EdgeAgentBufferHigh` (`infra/prometheus/alerts.yml:241`) could never fire.
        #
        # Both spellings are emitted. `/healthz` consumers may read the old ones, and a
        # rename is not worth a second silent break to fix the first.
        #
        # The buffer numbers come from a cache, not a query: this method is sync and
        # thread-safe on purpose (it serves the HTTP health server), and the buffer's
        # `get_stats()` is async. `_stats_reporter` already computes them every five
        # minutes and previously only logged them.
        return {
            "status": "ok" if self._running else "stopping",
            "running": self._running,
            "collectors_total": status.get("total_collectors", 0),
            "collectors_active": status.get("active_collectors", 0),
            "total_collectors": status.get("total_collectors", 0),
            "active_collectors": status.get("active_collectors", 0),
            "buffer_pending": self._buffer_snapshot.get("pending", 0),
            "dead_lettered": self._buffer_snapshot.get("dead_lettered", 0),
            "dropped": self._buffer_snapshot.get("dropped", 0),
        }

    async def start(self):
        """Start the edge agent"""
        logger.info(
            "edge_agent_starting",
            agent_id=self.config['agent_id'],
            organization_id=self.config['organization_id']
        )
        
        self._running = True
        self._restart_requested.clear()
        require_boot_health = self._requires_boot_health()

        try:
            persist_agent_state(
                self.state_path,
                {
                    "agent_id": self.config['agent_id'],
                    "agent_version": self.manifest["agent_version"],
                    "build_id": self.manifest.get("build_id"),
                    "git_sha": self.manifest.get("git_sha"),
                    "config_hash": self.config_hash,
                    "asset_ids": asset_ids_from_collectors(self.config.get('collectors', [])),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as e:
            logger.warning("agent_state_persist_failed", error=str(e), path=self.state_path)

        # Prometheus /metrics + /healthz. Default-on (METRICS_ENABLED=false to
        # disable); METRICS_PORT overrides the default. The metrics_server module
        # serves the same registry as opsgrid_agent.metrics plus /healthz.
        #
        # FS-519. The default was 9100 and matched NOTHING: the StatefulSet declares
        # containerPort 9108, the compose simulator publishes 9108, and both scrape
        # jobs target 9108. So any deployment that did not set METRICS_PORT explicitly
        # listened on a port nothing scraped — the agent looked healthy, exported a full
        # registry, and every edge alert stayed silent because no series existed. 9100 is
        # also the node_exporter port, so on a host running one the agent would have been
        # scraped as the node exporter or failed to bind.
        if os.getenv('METRICS_ENABLED', 'true').lower() != 'false':
            from opsgrid_agent.metrics_server import start_metrics_server
            start_metrics_server(
                int(os.getenv('METRICS_PORT', '9108')),
                health_provider=self._health_snapshot,
                # FS-755. The only alarm surface that does not cross the link.
                alerts_provider=lambda: self.alert_sink.recent(hours=24, limit=200),
            )

        try:
            # Enroll before Kafka startup so required mTLS has a certificate.
            await self._start_cloud_link()

            kafka_ready = await self._init_kafka_producer()
            if require_boot_health and not kafka_ready:
                raise RuntimeError("Kafka producer failed the agent boot self-check")

            await self._initialize_collectors()
            await self.coordinator.start_all()
            await asyncio.sleep(0)
            if require_boot_health:
                self._assert_collectors_healthy()

            self._init_command_consumer()
            try:
                await self.command_consumer.start(consume=False)
            except Exception as e:
                logger.error("command_consumer_failed", error=str(e))
                if require_boot_health:
                    raise

            await self._publish_heartbeat(required=require_boot_health)
            if self.command_consumer and self.command_consumer.is_running:
                await self.agent_update_executor.complete_pending_update(
                    self.command_consumer
                )

            self._mark_boot_ready()

            if self.command_consumer and self.command_consumer.is_running:
                self.command_consumer.start_consuming()
            # FS-756. Started even when the boot connect succeeded: a producer can be
            # lost later, and a supervisor that only runs after a failed boot would not be
            # there when it is.
            self._tasks.append(asyncio.create_task(self._uplink_supervisor()))
            self._tasks.append(asyncio.create_task(self._backfill_worker()))
            self._tasks.append(asyncio.create_task(self._cleanup_worker()))
            self._tasks.append(asyncio.create_task(self._stats_reporter()))
            self._tasks.append(asyncio.create_task(self._heartbeat_worker()))

            logger.info(
                "edge_agent_started",
                agent_version=self.manifest['agent_version'],
                bootstrap_managed=self.config.get('bootstrap_managed'),
            )
        except Exception:
            await self.stop()
            raise
    
    async def _start_cloud_link(self):
        """Enroll with the cloud and start the heartbeat + cert-rotation loops.

        No-op unless CLOUD_URL is set, so offline/air-gapped deployments and
        tests are unaffected. Failures degrade gracefully: the agent keeps
        collecting locally (store-and-forward) and retries on the next beat.
        """
        cloud_url = os.getenv('CLOUD_URL')
        if not cloud_url:
            return
        try:
            from opsgrid_agent.security.enrollment import EnrollmentClient
            from opsgrid_agent.security.rotation import CertificateRotationManager
            from opsgrid_agent.heartbeat import HeartbeatReporter
            from opsgrid_agent.timesync import ClockSkewEstimator
            from opsgrid_agent.security.enrollment import _default_post

            identity = self._load_identity()

            bootstrap = os.getenv('EDGE_BOOTSTRAP_TOKEN', '')
            enrollment = EnrollmentClient(identity, cloud_url, bootstrap)
            if not identity.has_certificate() and bootstrap:
                try:
                    await asyncio.to_thread(enrollment.enroll)
                except Exception as exc:
                    logger.warning("cloud_enrollment_failed", error=str(exc))

            # Cert rotation loop (renews before expiry via re-enrollment).
            self._rotation = CertificateRotationManager(identity, enrollment)
            self._tasks.append(asyncio.create_task(self._rotation.start()))

            # Heartbeat loop: health snapshot + cert expiry; the ack's server
            # time feeds the clock-skew estimator.
            # Reuses the estimator built in __init__ — replacing it here would hand the
            # command consumer a detached object that never calibrates.

            def _health():
                snapshot = dict(self._health_snapshot() or {})
                info = identity.certificate_info()
                if info is not None:
                    snapshot['cert_expires_in_seconds'] = int(info.seconds_until_expiry())
                return snapshot

            def _post(url, body, headers):
                headers = {**headers, 'X-Client-Cert':
                           identity.crt_path.read_text().replace('\n', '\\n')
                           if identity.has_certificate() else ''}
                # Proof-of-possession: sign the request with the agent's private
                # key so the (public) certificate header can't be replayed by an
                # observer — the backend verifies against the cert's public key.
                # The skew offset keeps drifted clocks inside the server's
                # freshness window (see ClockSkewEstimator).
                if identity.has_certificate():
                    from opsgrid_agent.security.request_signing import sign_request
                    headers.update(sign_request(
                        identity, body,
                        skew_seconds=self._skew.offset_seconds if self._skew else 0.0,
                    ))
                return _default_post(url, body, headers)

            reporter = HeartbeatReporter(
                cloud_url, os.getenv('AGENT_VERSION', 'dev'),
                _health, post_fn=_post, skew_estimator=self._skew,
            )
            # HELD ON THE AGENT (FS-759). `_serialize_uplink` reads `wire_codecs` off this
            # reporter to decide whether it may compress. A local `reporter` variable would
            # leave the serialiser reading the default forever and the negotiation would be
            # a feature that runs and changes nothing — precisely how `compression.py` spent
            # its first year.
            self.heartbeat_reporter = reporter
            interval = float(os.getenv('HEARTBEAT_INTERVAL', '30'))

            async def _heartbeat_loop():
                while self._running:
                    try:
                        await asyncio.to_thread(reporter.send_once)
                    except Exception as exc:  # never kill the loop
                        logger.warning("heartbeat_loop_error", error=str(exc))
                    await asyncio.sleep(interval)

            self._tasks.append(asyncio.create_task(_heartbeat_loop()))
            logger.info("cloud_link_started", cloud_url=cloud_url,
                        enrolled=identity.has_certificate(), interval=interval)
        except Exception as exc:
            logger.error("cloud_link_setup_failed", error=str(exc))

    async def stop(self):
        """Stop the edge agent"""
        logger.info("edge_agent_stopping")
        
        self._running = False
        self._restart_requested.set()
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        
        # Stop all collectors via coordinator
        await self.coordinator.stop_all()

        if self.command_consumer:
            await self.command_consumer.stop()
        
        # Stop Kafka producer
        await self._stop_kafka_producer()
        
        logger.info("edge_agent_stopped")
    
    async def run(self):
        """Main run loop"""
        try:
            await self.start()
            await self._restart_requested.wait()
        except asyncio.CancelledError:
            pass
        finally:
            if self._running:
                await self.stop()


async def main():
    """Entry point"""
    agent = EdgeAgent()
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in ('SIGINT', 'SIGTERM'):
        try:
            loop.add_signal_handler(
                getattr(__import__('signal'), sig),
                agent.request_shutdown,
            )
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    await agent.run()


def run():
    """Console-script entrypoint (pyproject [project.scripts])."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
