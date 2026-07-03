"""
Unified Collector Coordinator
Manages all data source collectors in a single coordinated system
"""

import asyncio
import json
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
import structlog

from omniusgrid_agent.collectors.mqtt import BambuCollector, MQTTCollector
from omniusgrid_agent.collectors.screen_scraper import QidiCollector, SovolCollector
from omniusgrid_agent.collectors.file_watcher import OrcaSlicerCollector
from omniusgrid_agent.collectors.opcua_collector import OPCUACollector
from omniusgrid_agent.collectors.modbus_collector import ModbusCollector
from omniusgrid_agent.buffer.store_forward import StoreForwardBuffer

# BaseCollector-style collectors, bridged to the coordinator contract via an
# adapter. Relative imports keep these independent of the package name so they
# are unaffected by the omniusgrid_agent -> opsgrid_agent rename.
from .adapter import coordinator_adapter
from .ethernet_ip import EthernetIPCollector
from .profinet import ProfinetCollector
from .bacnet import BACnetCollector
from .can_bus import CANBusCollector
from .http_rest import HTTPRestCollector

logger = structlog.get_logger()


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
        
        # Status tracking
        self._running = False
        self._health_check_task: Optional[asyncio.Task] = None
    
    def register_collector(self, config: CollectorConfig):
        """Register a collector configuration"""
        self.configs[config.asset_id] = config
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
        
        # Create tasks for all collectors
        tasks = [
            asyncio.create_task(start_with_limit(config))
            for config in self.configs.values()
            if config.enabled
        ]
        
        # Start health monitoring
        self._health_check_task = asyncio.create_task(self._health_monitor())
        
        logger.info("all_collectors_started")
    
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
            
            # Create collector instance
            collector = collector_class(
                **config.config,
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
            
            # Add metadata
            enriched_message = {
                **message,
                '_coordinator_received_at': asyncio.get_event_loop().time(),
            }
            
            # Store in buffer for store-and-forward
            await self.buffer.store_message(enriched_message)
            
            # Also try to forward immediately if connected
            if self.kafka_producer:
                try:
                    await self._forward_to_kafka(enriched_message)
                except Exception as e:
                    # Already in buffer, will retry later
                    logger.debug(
                        "immediate_forward_failed",
                        asset_id=asset_id,
                        error=str(e)
                    )
            
            logger.debug(
                "collector_message_received",
                asset_id=asset_id,
                type=collector_type
            )
            
        except Exception as e:
            logger.error(
                "collector_message_handler_error",
                error=str(e),
                message_preview=str(message)[:200]
            )
    
    async def _forward_to_kafka(self, message: Dict):
        """Forward message to Kafka"""
        asset_id = message.get('asset_id', 'unknown')
        topic = f"telemetry.{asset_id}"
        
        # Serialize
        payload = json.dumps(message).encode('utf-8')
        
        # Send
        await self.kafka_producer.send(topic, payload)
    
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
                logger.info(
                    "collector_health_check",
                    active=active_count,
                    total=len(self.configs)
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
