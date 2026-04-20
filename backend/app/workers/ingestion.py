"""Ingestion Worker - Consumes from Redpanda and writes to TimescaleDB"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
import structlog
from aiokafka import AIOKafkaConsumer
from sqlalchemy.ext.asyncio import AsyncSession

import sys
sys.path.insert(0, '/app')

from app.db.database import AsyncSessionLocal
from app.db.models import Telemetry, PackMLState, Asset, Alarm
from app.services.data_shedding import data_shedder
from app.services.websocket_manager import websocket_manager
from app.services.oee_calculator import oee_calculator

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


class IngestionWorker:
    """
    Consumes messages from Redpanda/Kafka and writes to TimescaleDB.
    
    Handles:
    - Telemetry data ingestion
    - PackML state tracking
    - Alarm detection and storage
    - Duplicate detection via sequence numbers
    """
    
    def __init__(self):
        self.broker_url = os.getenv('REDPANDA_URL', 'redpanda:29092')
        self.consumer: Optional[AIOKafkaConsumer] = None
        self._running = False
        self._topics = ['telemetry', 'state', 'alarms']
    
    async def start(self):
        """Start the ingestion worker"""
        logger.info("ingestion_worker_starting", broker=self.broker_url)
        
        self.consumer = AIOKafkaConsumer(
            bootstrap_servers=self.broker_url,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='opsgrid-ingestion-workers',
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            auto_commit_interval_ms=5000,
        )
        
        # Subscribe to all relevant topics
        await self.consumer.start()
        
        # Subscribe to topic patterns
        topic_patterns = [f'^{t}\\..*' for t in self._topics]
        self.consumer.subscribe(pattern='|'.join(topic_patterns))
        
        logger.info("consumer_started", topics=self._topics)
        
        self._running = True
        
        try:
            async for msg in self.consumer:
                if not self._running:
                    break
                
                try:
                    await self._process_message(msg)
                except Exception as e:
                    logger.error(
                        "message_processing_failed",
                        topic=msg.topic,
                        error=str(e)
                    )
        
        finally:
            await self.consumer.stop()
            logger.info("ingestion_worker_stopped")
    
    async def _process_message(self, msg):
        """Process a single message"""
        topic = msg.topic
        data = msg.value
        
        # Parse topic structure: telemetry.{org}.{asset_id}
        topic_parts = topic.split('.')
        if len(topic_parts) < 3:
            logger.warning("invalid_topic_format", topic=topic)
            return
        
        msg_type = topic_parts[0]
        organization_id = topic_parts[1]
        asset_id = topic_parts[2]
        
        async with AsyncSessionLocal() as session:
            try:
                if msg_type == 'telemetry':
                    await self._process_telemetry(session, asset_id, data, organization_id)
                elif msg_type == 'state':
                    await self._process_state(session, asset_id, data, organization_id)
                elif msg_type == 'alarms':
                    await self._process_alarm(session, asset_id, data, organization_id)
                
                await session.commit()
            
            except Exception as e:
                await session.rollback()
                raise
    
    async def _process_telemetry(self, session: AsyncSession, asset_id: str, data: Dict, organization_id: str):
        """Process telemetry data with intelligent shedding"""
        # Parse timestamp
        timestamp_str = data.get('timestamp_edge') or data.get('timestamp')
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            timestamp = datetime.utcnow()
        
        packml_state = data.get('packml_state')
        payload = data.get('payload', {})
        
        # Extract telemetry fields from payload
        telemetry_data = payload.get('telemetry', payload)
        
        if isinstance(telemetry_data, dict):
            for metric_name, value in telemetry_data.items():
                if value is not None:
                    # Check data shedding - drop low priority data if system overloaded
                    if data_shedder.should_shed(metric_name, timestamp):
                        logger.debug(
                            "data_shedded",
                            metric=metric_name,
                            asset_id=asset_id,
                            reason="load_shedding"
                        )
                        continue
                    
                    telemetry = Telemetry(
                        time=timestamp,
                        asset_id=asset_id,
                        metric_name=metric_name,
                        value=float(value) if isinstance(value, (int, float)) else 0,
                        unit=self._infer_unit(metric_name),
                        packml_state=packml_state,
                        metadata=payload,
                        sequence_num=data.get('sequence_num', 0)
                    )
                    session.add(telemetry)
        
        # Update asset last_seen
        await session.execute(
            f"""
            UPDATE assets 
            SET last_seen = '{timestamp.isoformat()}', 
                current_packml_state = '{packml_state or 'Idle'}'
            WHERE id = '{asset_id}'
            """
        )
        
        logger.debug(
            "telemetry_ingested",
            asset_id=asset_id,
            timestamp=timestamp.isoformat()
        )
        
        # Publish to WebSocket for real-time updates
        try:
            # Extract just the telemetry values for broadcast
            telemetry_summary = {
                metric_name: float(value) if isinstance(value, (int, float)) else value
                for metric_name, value in telemetry_data.items()
                if value is not None and isinstance(value, (int, float, str, bool))
            }
            
            await websocket_manager.publish_telemetry(
                organization_id=organization_id,
                asset_id=asset_id,
                telemetry_data=telemetry_summary,
                packml_state=packml_state
            )
        except Exception as e:
            # Don't fail ingestion if WebSocket fails
            logger.warning("websocket_publish_failed", error=str(e), asset_id=asset_id)
        
        # Update OEE part counters
        try:
            await oee_calculator.process_telemetry(
                asset_id=asset_id,
                organization_id=organization_id,
                telemetry=telemetry_data
            )
        except Exception as e:
            logger.warning("oee_telemetry_tracking_failed", error=str(e), asset_id=asset_id)
    
    async def _process_state(self, session: AsyncSession, asset_id: str, data: Dict, organization_id: str):
        """Process PackML state transitions"""
        new_state = data.get('packml_state')
        previous_state = data.get('previous_state')
        timestamp_str = data.get('timestamp_edge') or data.get('timestamp')
        
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            timestamp = datetime.utcnow()
        
        if not new_state:
            return
        
        # Close previous state if exists
        if previous_state:
            await session.execute(
                f"""
                UPDATE packml_states 
                SET state_exited_at = '{timestamp.isoformat()}',
                    duration_seconds = EXTRACT(EPOCH FROM ('{timestamp.isoformat()}'::timestamp - state_entered_at))
                WHERE asset_id = '{asset_id}'
                AND state = '{previous_state}'
                AND state_exited_at IS NULL
                """
            )
        
        # Create new state entry
        state_record = PackMLState(
            asset_id=asset_id,
            state=new_state,
            previous_state=previous_state,
            state_entered_at=timestamp,
            metadata=data.get('metadata', {})
        )
        session.add(state_record)
        
        # Update asset current state
        await session.execute(
            f"""
            UPDATE assets 
            SET current_packml_state = '{new_state}'
            WHERE id = '{asset_id}'
            """
        )
        
        logger.info(
            "state_transition",
            asset_id=asset_id,
            from_state=previous_state,
            to_state=new_state,
            timestamp=timestamp.isoformat()
        )
        
        # Publish state change to WebSocket
        try:
            await websocket_manager.publish_state_change(
                organization_id=organization_id,
                asset_id=asset_id,
                previous_state=previous_state,
                new_state=new_state,
                metadata=data.get('metadata', {})
            )
        except Exception as e:
            logger.warning("websocket_state_publish_failed", error=str(e), asset_id=asset_id)
        
        # Update OEE tracking
        try:
            await oee_calculator.process_state_change(
                asset_id=asset_id,
                organization_id=organization_id,
                previous_state=previous_state,
                new_state=new_state,
                timestamp=timestamp
            )
        except Exception as e:
            logger.warning("oee_state_tracking_failed", error=str(e), asset_id=asset_id)
    
    async def _process_alarm(self, session: AsyncSession, asset_id: str, data: Dict, organization_id: str):
        """Process alarm events"""
        alarm = Alarm(
            asset_id=asset_id,
            alarm_code=data.get('alarm_code', 'UNKNOWN'),
            severity=data.get('severity', 'medium'),
            message=data.get('message', 'Unknown alarm'),
            description=data.get('description'),
            metadata=data.get('metadata', {}),
            occurred_at=datetime.utcnow()
        )
        session.add(alarm)
        
        logger.warning(
            "alarm_ingested",
            asset_id=asset_id,
            alarm_code=alarm.alarm_code,
            severity=alarm.severity
        )
        
        # Publish alarm to WebSocket
        try:
            await websocket_manager.publish_alarm(
                organization_id=organization_id,
                asset_id=asset_id,
                alarm_data={
                    'alarm_code': alarm.alarm_code,
                    'severity': alarm.severity,
                    'message': alarm.message,
                    'description': alarm.description,
                    'occurred_at': alarm.occurred_at.isoformat()
                }
            )
        except Exception as e:
            logger.warning("websocket_alarm_publish_failed", error=str(e), asset_id=asset_id)
    
    def _infer_unit(self, metric_name: str) -> Optional[str]:
        """Infer unit from metric name"""
        metric_lower = metric_name.lower()
        
        if 'temp' in metric_lower:
            return '°C'
        elif 'speed' in metric_lower or 'rpm' in metric_lower:
            return 'mm/s'
        elif 'progress' in metric_lower:
            return '%'
        elif 'layer' in metric_lower:
            return 'count'
        elif 'time' in metric_lower:
            return 's'
        
        return None
    
    async def stop(self):
        """Stop the ingestion worker"""
        logger.info("stopping_ingestion_worker")
        self._running = False
        if self.consumer:
            await self.consumer.stop()


async def main():
    """Entry point"""
    worker = IngestionWorker()
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def shutdown_handler():
        asyncio.create_task(worker.stop())
    
    import signal
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            pass
    
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
