"""Edge Agent Main Module"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import structlog

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
from opsgrid_agent.commands import CommandConsumer
from opsgrid_agent.config_bundle import collectors_from_bundle
from opsgrid_agent.collectors.coordinator import UnifiedCollectorCoordinator, CollectorConfig
from opsgrid_agent.ota import OTAUpdateExecutor
from opsgrid_agent import metrics

structlog.configure(
    processors=[
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
        self.config = self._load_config()
        metrics.configure(agent_id=self.config['agent_id'])
        self.buffer = StoreForwardBuffer(
            buffer_path=self.config.get('buffer_path', '/var/lib/opsgrid-agent/buffer.db'),
            retention_hours=self.config.get('buffer_retention_hours', 24)
        )
        self.kafka_producer = None
        self.command_consumer = None
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
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
        # Initialize collector coordinator
        self.coordinator = UnifiedCollectorCoordinator(
            buffer=self.buffer,
            kafka_producer=None  # Will be set after Kafka init
        )
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from environment"""
        config = {
            'organization_id': os.getenv('ORGANIZATION_ID', 'dev-org'),
            'agent_id': os.getenv('AGENT_ID', 'agent-001'),
            'redpanda_url': os.getenv('REDPANDA_URL', 'localhost:9092'),
            'command_topic': os.getenv('REDPANDA_COMMAND_TOPIC', 'opsgrid.commands'),
            'command_ack_topic': os.getenv('REDPANDA_COMMAND_ACK_TOPIC', 'opsgrid.commands.acks'),
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
            'buffer_path': os.getenv('BUFFER_PATH', '/var/lib/opsgrid-agent/buffer.db'),
            'buffer_retention_hours': int(os.getenv('BUFFER_RETENTION_HOURS', '24')),
            'collectors': json.loads(os.getenv('COLLECTORS', '[]')),
        }
        self._load_active_config_bundle(config)
        return config

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
            )
            self.ota_executor.register(self.command_consumer)

    async def _restart_runtime_after_update(self):
        """Restart collectors after an OTA config-bundle swap."""
        await self.coordinator.stop_all()
        self.config = self._load_config()
        self.coordinator.configs.clear()
        self.coordinator.collectors.clear()
        self.coordinator.collector_tasks.clear()
        if self.command_consumer:
            self.command_consumer.asset_ids = set(self._asset_ids())
        await self._initialize_collectors()
        await self.coordinator.start_all()
    
    async def _init_kafka_producer(self):
        """Initialize Kafka/Redpanda producer"""
        try:
            from aiokafka import AIOKafkaProducer
            
            self.kafka_producer = AIOKafkaProducer(
                bootstrap_servers=self.config['redpanda_url'],
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                key_serializer=lambda k: k.encode('utf-8') if k else None,
            )
            await self.kafka_producer.start()
            
            # Set coordinator's Kafka producer
            self.coordinator.kafka_producer = self.kafka_producer
            
            logger.info(
                "kafka_producer_started",
                brokers=self.config['redpanda_url']
            )
        except Exception as e:
            logger.error("kafka_producer_failed", error=str(e))
            self.kafka_producer = None
    
    async def _stop_kafka_producer(self):
        """Stop Kafka producer"""
        if self.kafka_producer:
            await self.kafka_producer.stop()
            logger.info("kafka_producer_stopped")
    
    async def _handle_message(self, message: Dict[str, Any]):
        """Handle message from collector"""
        try:
            # Add sequence number for ordering
            message['sequence_num'] = int(datetime.utcnow().timestamp() * 1000)
            
            # Try to publish to Kafka
            if self.kafka_producer:
                topic = f"telemetry.{self.config['organization_id']}.{message['asset_id']}"
                
                try:
                    await self.kafka_producer.send(
                        topic,
                        value=message,
                        key=message['asset_id']
                    )
                    logger.debug(
                        "message_published",
                        topic=topic,
                        asset_id=message['asset_id']
                    )
                except Exception as e:
                    # Publish failed, buffer locally
                    logger.warning(
                        "publish_failed_buffering",
                        topic=topic,
                        error=str(e)
                    )
                    await self._buffer_message(message)
            else:
                # No Kafka connection, buffer locally
                await self._buffer_message(message)
        
        except Exception as e:
            logger.error("message_handler_error", error=str(e))
    
    async def _buffer_message(self, message: Dict[str, Any]):
        """Buffer message locally"""
        success = await self.buffer.store(
            timestamp_edge=datetime.fromisoformat(message['timestamp_edge']),
            asset_id=message['asset_id'],
            topic=message.get('topic', 'unknown'),
            payload=message['payload'],
            sequence_num=message.get('sequence_num', 0)
        )
        
        if success:
            logger.debug(
                "message_buffered",
                asset_id=message['asset_id']
            )
    
    async def _backfill_worker(self):
        """Background task to backfill buffered messages"""
        logger.info("backfill_worker_started")
        
        while self._running:
            try:
                if self.kafka_producer:
                    # Get pending messages
                    messages = await self.buffer.get_pending_messages(batch_size=100)
                    
                    if messages:
                        logger.info(
                            "backfilling_messages",
                            count=len(messages)
                        )
                        
                        sent_ids = []
                        failed_ids = []
                        
                        for msg in messages:
                            try:
                                topic = f"telemetry.{self.config['organization_id']}.{msg.asset_id}"
                                
                                await self.kafka_producer.send(
                                    topic,
                                    value={
                                        'timestamp_edge': msg.timestamp_edge,
                                        'asset_id': msg.asset_id,
                                        'payload': json.loads(msg.payload),
                                        'sequence_num': msg.sequence_num,
                                        'backfilled': True
                                    },
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
                                metrics.record_kafka_error()
                        
                        # Mark sent messages as complete
                        if sent_ids:
                            await self.buffer.mark_sent(sent_ids)
                        
                        # Increment retry for failed
                        if failed_ids:
                            await self.buffer.increment_retry(failed_ids)
                
                # Wait before next batch
                await asyncio.sleep(5)
            
            except Exception as e:
                logger.error("backfill_worker_error", error=str(e))
                await asyncio.sleep(10)
    
    async def _cleanup_worker(self):
        """Background task for periodic cleanup"""
        while self._running:
            try:
                # Clean old messages
                deleted = await self.buffer.cleanup_old_messages()
                if deleted > 0:
                    logger.info(
                        "cleanup_completed",
                        deleted_messages=deleted
                    )
                
                # Vacuum database weekly
                stats = await self.buffer.get_stats()
                if stats['size_mb'] > 500:
                    await self.buffer.vacuum()
                
                # Wait 1 hour before next cleanup
                await asyncio.sleep(3600)
            
            except Exception as e:
                logger.error("cleanup_worker_error", error=str(e))
                await asyncio.sleep(3600)
    
    async def _stats_reporter(self):
        """Periodic stats reporting"""
        while self._running:
            try:
                stats = await self.buffer.get_stats()
                status = self.coordinator.get_status()
                metrics.refresh_buffer_stats(stats['total_messages'])
                metrics.refresh_collector_stats(
                    status['active_collectors'],
                    status['total_collectors'],
                )
                logger.info(
                    "buffer_stats",
                    total_messages=stats['total_messages'],
                    failed_messages=stats['failed_messages'],
                    size_mb=stats['size_mb'],
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
                collector_type = collector_conf.get('type')
                
                if not asset_id or not collector_type:
                    logger.error("invalid_collector_config", config=collector_conf)
                    continue
                
                # Create collector config
                config = CollectorConfig(
                    collector_type=collector_type,
                    asset_id=asset_id,
                    config=collector_conf.get('config', {}),
                    enabled=collector_conf.get('enabled', True)
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
    
    async def start(self):
        """Start the edge agent"""
        logger.info(
            "edge_agent_starting",
            agent_id=self.config['agent_id'],
            organization_id=self.config['organization_id']
        )
        
        self._running = True

        if os.getenv('METRICS_ENABLED', 'true').lower() != 'false':
            metrics.start_metrics_server(int(os.getenv('METRICS_PORT', '9100')))
        
        # Initialize Kafka producer
        await self._init_kafka_producer()
        
        # Start background workers
        self._tasks.append(asyncio.create_task(self._backfill_worker()))
        self._tasks.append(asyncio.create_task(self._cleanup_worker()))
        self._tasks.append(asyncio.create_task(self._stats_reporter()))
        
        # Initialize collectors from configuration
        await self._initialize_collectors()
        
        # Start all collectors via coordinator
        await self.coordinator.start_all()

        self._init_command_consumer()
        try:
            await self.command_consumer.start()
        except Exception as e:
            logger.error("command_consumer_failed", error=str(e))
        
        logger.info("edge_agent_started")
    
    async def stop(self):
        """Stop the edge agent"""
        logger.info("edge_agent_stopping")
        
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Stop all collectors via coordinator
        await self.coordinator.stop_all()

        if self.command_consumer:
            await self.command_consumer.stop()
        
        # Stop Kafka producer
        await self._stop_kafka_producer()
        
        logger.info("edge_agent_stopped")
    
    async def run(self):
        """Main run loop"""
        await self.start()
        
        try:
            # Keep running until interrupted
            while self._running:
                await asyncio.sleep(1)
        
        except asyncio.CancelledError:
            pass
        finally:
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
                lambda: asyncio.create_task(agent.stop())
            )
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
