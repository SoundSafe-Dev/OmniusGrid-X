"""Edge Agent Main Module"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, Any, List
import structlog

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
from opsgrid_agent.collectors.mqtt import BambuCollector, MQTTCollector
from opsgrid_agent.packml import PackMLStateMapper

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
        self.buffer = StoreForwardBuffer(
            buffer_path=self.config.get('buffer_path', '/var/lib/opsgrid-agent/buffer.db'),
            retention_hours=self.config.get('buffer_retention_hours', 24)
        )
        self.collectors: List[Any] = []
        self.kafka_producer = None
        self._running = False
        self._tasks: List[asyncio.Task] = []
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from environment"""
        return {
            'organization_id': os.getenv('ORGANIZATION_ID', 'dev-org'),
            'agent_id': os.getenv('AGENT_ID', 'agent-001'),
            'redpanda_url': os.getenv('REDPANDA_URL', 'localhost:9092'),
            'buffer_path': os.getenv('BUFFER_PATH', '/var/lib/opsgrid-agent/buffer.db'),
            'buffer_retention_hours': int(os.getenv('BUFFER_RETENTION_HOURS', '24')),
            'collectors': json.loads(os.getenv('COLLECTORS', '[]')),
        }
    
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
                            
                            except Exception as e:
                                logger.error(
                                    "backfill_send_failed",
                                    message_id=msg.id,
                                    error=str(e)
                                )
                                failed_ids.append(msg.id)
                        
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
    
    async def start(self):
        """Start the edge agent"""
        logger.info(
            "edge_agent_starting",
            agent_id=self.config['agent_id'],
            organization_id=self.config['organization_id']
        )
        
        self._running = True
        
        # Initialize Kafka producer
        await self._init_kafka_producer()
        
        # Start background workers
        self._tasks.append(asyncio.create_task(self._backfill_worker()))
        self._tasks.append(asyncio.create_task(self._cleanup_worker()))
        self._tasks.append(asyncio.create_task(self._stats_reporter()))
        
        # TODO: Initialize collectors from configuration
        # For now, we'll simulate with a test collector
        
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
        
        # Stop collectors
        for collector in self.collectors:
            await collector.stop()
        
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
