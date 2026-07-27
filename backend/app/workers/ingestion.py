"""Ingestion Worker - Consumes from Redpanda and writes to TimescaleDB"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from uuid import UUID
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

import sys
sys.path.insert(0, '/app')

from app.core.config import settings
from app.workers.health_server import start_health_server
from app.core.datetime_utils import aware_utc
from app.db.database import AsyncSessionLocal
from app.db.models import (
    Alarm,
    Asset,
    AssetAgentCollector,
    PackMLState,
    Telemetry,
)
from app.services.data_shedding import data_shedder
from app.services.fleet_targeting import semver_asset_values
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


def _health_port():
    """WORKER_HEALTH_PORT, or None outside Kubernetes (tests/local runs)."""
    raw = os.getenv('WORKER_HEALTH_PORT')
    return int(raw) if raw else None


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
        self._producer: Optional[AIOKafkaProducer] = None
        self._running = False
        self._topics = ['telemetry', 'state', 'alarms']
        self.agent_status_topic = os.getenv(
            'AGENT_STATUS_TOPIC',
            settings.AGENT_STATUS_TOPIC,
        )
        self.dlq_topic = settings.REDPANDA_INGESTION_DLQ_TOPIC
        # Heartbeat for the liveness probe (see workers/health_server.py).
        # Telemetry is continuous, so a 5-minute gap means wedged, not idle.
        self._health = start_health_server(
            'ingestion', port=_health_port(), stale_after_seconds=300.0
        )
    
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
        
        # Producer for the dead-letter topic: a message this worker can't process
        # is published here (best-effort) before its offset advances, so poison
        # data is preserved for inspection/replay instead of vanishing.
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.broker_url,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        )
        await self._producer.start()

        # Subscribe to all relevant topics
        await self.consumer.start()
        
        # Subscribe to topic patterns
        topic_patterns = [f'^{t}\\..*' for t in self._topics]
        topic_patterns.append(f'^{re.escape(self.agent_status_topic)}$')
        self.consumer.subscribe(pattern='|'.join(topic_patterns))
        
        logger.info("consumer_started", topics=self._topics)
        if self._health:
            self._health.ready()
        
        self._running = True
        
        try:
            async for msg in self.consumer:
                if not self._running:
                    break
                
                try:
                    await self._process_message(msg)
                    if self._health:
                        self._health.beat()
                except Exception as e:
                    logger.error(
                        "message_processing_failed",
                        topic=msg.topic,
                        error=str(e)
                    )
                    # Preserve the poison message in the DLQ before the offset
                    # auto-commits past it — otherwise it is silently lost.
                    await self._dead_letter(msg, e)

        finally:
            await self.consumer.stop()
            if self._producer is not None:
                await self._producer.stop()
            logger.info("ingestion_worker_stopped")

    async def _dead_letter(self, msg, error: Exception) -> None:
        """Publish an unprocessable message to the ingestion DLQ (best-effort).

        Best-effort by design: if the DLQ publish itself fails we log loudly but
        don't crash the worker or block the partition. The envelope carries the
        original payload plus enough provenance (topic/partition/offset) to
        replay it after the underlying bug is fixed.
        """
        if self._producer is None:
            return
        try:
            envelope = {
                "schema_version": 1,
                "message_type": "dead_letter",
                "reason": str(error),
                "error_type": type(error).__name__,
                "source_topic": msg.topic,
                "source_partition": msg.partition,
                "source_offset": msg.offset,
                "consumer": "opsgrid-ingestion-workers",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": msg.value,
            }
            key = (msg.key if isinstance(msg.key, (bytes, bytearray)) else None)
            await self._producer.send_and_wait(self.dlq_topic, envelope, key=key)
            logger.warning(
                "ingestion_dead_lettered",
                source_topic=msg.topic,
                source_offset=msg.offset,
                error=str(error),
            )
        except Exception as dlq_error:  # noqa: BLE001 — DLQ failure must not crash the worker
            logger.error(
                "ingestion_dead_letter_failed",
                source_topic=getattr(msg, "topic", None),
                error=str(dlq_error),
                original_error=str(error),
            )
    
    async def _process_message(self, msg):
        """Process a single message"""
        topic = msg.topic
        data = msg.value

        if topic == self.agent_status_topic:
            async with AsyncSessionLocal() as session:
                try:
                    await self._process_agent_heartbeat(session, data)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
            return
        
        # Parse topic structure: telemetry.{org}.{asset_id}
        topic_parts = topic.split('.')
        if len(topic_parts) < 3:
            logger.warning("invalid_topic_format", topic=topic)
            return
        
        msg_type = topic_parts[0]
        organization_id = topic_parts[1]
        asset_id = topic_parts[2]

        # Validate both identifiers before using the tenant value as an RLS GUC.
        organization_id = str(UUID(organization_id))
        asset_id = str(UUID(asset_id))
        
        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    text("SELECT set_config('app.current_org_id', :org_id, true)"),
                    {"org_id": organization_id},
                )
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
        asset_uuid = UUID(asset_id)
        await data_shedder.refresh_tenant_policies(session, organization_id)

        # Parse timestamp
        timestamp_str = data.get('timestamp_edge') or data.get('timestamp')
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            timestamp = datetime.now(timezone.utc)
        
        packml_state = data.get('packml_state')
        payload = data.get('payload', {})
        
        # Extract telemetry fields from payload
        telemetry_data = payload.get('telemetry', payload)
        
        if isinstance(telemetry_data, dict):
            for metric_name, value in telemetry_data.items():
                if value is not None:
                    # Check data shedding - drop low priority data if system overloaded
                    if data_shedder.should_shed(
                        metric_name,
                        timestamp,
                        organization_id=organization_id,
                    ):
                        logger.debug(
                            "data_shedded",
                            metric=metric_name,
                            asset_id=asset_id,
                            reason="load_shedding"
                        )
                        continue
                    
                    telemetry = Telemetry(
                        time=timestamp,
                        asset_id=asset_uuid,
                        metric_name=metric_name,
                        value=float(value) if isinstance(value, (int, float)) else 0,
                        unit=self._infer_unit(metric_name),
                        packml_state=packml_state,
                        meta_data=payload,
                        sequence_num=data.get('sequence_num', 0)
                    )
                    session.add(telemetry)
        
        # Update asset last_seen
        await session.execute(
            update(Asset)
            .where(Asset.id == asset_uuid)
            .values(
                last_seen=timestamp,
                current_packml_state=packml_state or 'Idle',
            )
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

    async def _process_agent_heartbeat(self, session: AsyncSession, data: Dict):
        """Update asset fleet-version fields from an edge-agent heartbeat."""
        if data.get('message_type') != 'agent_heartbeat':
            logger.warning("invalid_agent_heartbeat_type", message_type=data.get('message_type'))
            return

        organization_id = data.get('organization_id')
        raw_asset_ids = data.get('asset_ids')
        if not organization_id or not isinstance(raw_asset_ids, list):
            logger.warning(
                "invalid_agent_heartbeat",
                organization_id=organization_id,
                asset_count=len(raw_asset_ids) if isinstance(raw_asset_ids, list) else None,
            )
            return

        try:
            org_uuid = UUID(str(organization_id))
            if len(raw_asset_ids) > 5000:
                raise ValueError("agent heartbeat contains too many assets")
            asset_ids = list(dict.fromkeys(UUID(str(asset_id)) for asset_id in raw_asset_ids))
        except (TypeError, ValueError) as exc:
            logger.warning("invalid_agent_heartbeat_uuid", error=str(exc))
            return

        timestamp_str = data.get('timestamp')
        received_at = datetime.now(timezone.utc)
        try:
            if timestamp_str:
                reported_at = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                if reported_at.tzinfo is None:
                    reported_at = reported_at.replace(tzinfo=timezone.utc)
            else:
                reported_at = received_at
        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning("invalid_agent_heartbeat_timestamp", error=str(exc))
            return
        if reported_at > received_at + timedelta(minutes=5):
            reported_at = received_at
        agent_id = data.get('agent_id')
        if not isinstance(agent_id, str) or not agent_id.strip() or len(agent_id) > 255:
            logger.warning("invalid_agent_heartbeat_agent_id")
            return
        agent_id = agent_id.strip()

        # Agent status is consumed outside an HTTP tenant dependency. Set the same
        # transaction-local tenant context explicitly so FORCE RLS remains usable.
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_uuid)},
        )

        stale_candidates = list(
            (
                await session.execute(
                    select(Asset.id).where(
                        Asset.organization_id == org_uuid,
                        Asset.agent_id == agent_id,
                        Asset.id.not_in(asset_ids),
                        or_(
                            Asset.agent_reported_at.is_(None),
                            Asset.agent_reported_at < reported_at,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        stale_asset_ids: list[UUID] = []
        if stale_candidates:
            stale_asset_ids = list(
                (
                    await session.execute(
                        update(Asset)
                        .where(
                            Asset.organization_id == org_uuid,
                            Asset.id.in_(stale_candidates),
                            Asset.agent_id == agent_id,
                            or_(
                                Asset.agent_reported_at.is_(None),
                                Asset.agent_reported_at < reported_at,
                            ),
                        )
                        .values(
                            agent_id=None,
                            agent_version=None,
                            agent_config_hash=None,
                            agent_build_id=None,
                            agent_last_heartbeat=None,
                            agent_reported_at=reported_at,
                            **semver_asset_values(None),
                        )
                        .returning(Asset.id)
                    )
                )
                .scalars()
                .all()
            )
            if stale_asset_ids:
                await session.execute(
                    delete(AssetAgentCollector).where(
                        AssetAgentCollector.organization_id == org_uuid,
                        AssetAgentCollector.asset_id.in_(stale_asset_ids),
                    )
                )

        raw_version = data.get('agent_version')
        if raw_version is not None and (
            not isinstance(raw_version, str) or len(raw_version) > 100
        ):
            raw_version = None
        version_values = semver_asset_values(raw_version)
        config_hash = data.get('config_hash')
        if config_hash is not None and (
            not isinstance(config_hash, str) or len(config_hash) > 64
        ):
            config_hash = None
        build_id = data.get('build_id')
        if build_id is not None and (
            not isinstance(build_id, str) or len(build_id) > 255
        ):
            build_id = None
        updated_ids = list(
            (
                await session.execute(
                    update(Asset)
                    .where(
                        Asset.organization_id == org_uuid,
                        Asset.id.in_(asset_ids),
                        or_(
                            Asset.agent_reported_at.is_(None),
                            Asset.agent_reported_at < reported_at,
                        ),
                    )
                    .values(
                        agent_id=agent_id,
                        agent_version=raw_version,
                        agent_config_hash=config_hash,
                        agent_build_id=build_id,
                        agent_last_heartbeat=received_at,
                        agent_reported_at=reported_at,
                        last_seen=received_at,
                        **version_values,
                    )
                    .returning(Asset.id)
                )
            )
            .scalars()
            .all()
        )

        if updated_ids:
            await session.execute(
                delete(AssetAgentCollector).where(
                    AssetAgentCollector.organization_id == org_uuid,
                    AssetAgentCollector.asset_id.in_(updated_ids),
                )
            )

        collector_status = data.get('collector_status') or {}
        collectors = collector_status.get('collectors') if isinstance(collector_status, dict) else {}
        collectors = collectors if isinstance(collectors, dict) else {}
        # UUIDString-backed asset IDs are returned as strings on every dialect,
        # while heartbeat payload validation produces UUID objects. Compare the
        # canonical text form so collector facts are not silently discarded.
        updated_id_set = {str(asset_id) for asset_id in updated_ids}
        for raw_asset_id, collector in collectors.items():
            try:
                collector_asset_id = str(UUID(str(raw_asset_id)))
            except (TypeError, ValueError):
                continue
            if collector_asset_id not in updated_id_set or not isinstance(collector, dict):
                continue
            collector_type = collector.get('type')
            if (
                not isinstance(collector_type, str)
                or not collector_type.strip()
                or len(collector_type.strip()) > 100
            ):
                continue
            session.add(
                AssetAgentCollector(
                    organization_id=org_uuid,
                    asset_id=collector_asset_id,
                    collector_type=collector_type.strip(),
                    enabled=bool(collector.get('enabled', True)),
                    running=bool(collector.get('running', False)),
                    heartbeat_at=received_at,
                )
            )

        logger.info(
            "agent_heartbeat_ingested",
            agent_id=agent_id,
            organization_id=str(org_uuid),
            asset_count=len(asset_ids),
            updated_assets=len(updated_ids),
            retired_assets=len(stale_asset_ids),
        )
    
    async def _process_state(self, session: AsyncSession, asset_id: str, data: Dict, organization_id: str):
        """Process PackML state transitions"""
        new_state = data.get('packml_state')
        previous_state = data.get('previous_state')
        timestamp_str = data.get('timestamp_edge') or data.get('timestamp')
        
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            timestamp = datetime.now(timezone.utc)
        
        if not new_state:
            return

        asset_uuid = UUID(asset_id)

        # Close previous state if exists.
        #
        # Both statements here used to be f-strings passed bare to
        # session.execute(). SQLAlchemy 2.x refuses a plain str, so this raised
        # ObjectNotExecutableError before any SQL ran — and since _handle_message
        # rolls back and re-raises, *every* state message failed and no PackML
        # row was ever written by this worker. Done via the ORM (as the telemetry
        # and alarm paths already do) so it is both parameterised and portable:
        # the old EXTRACT(EPOCH FROM ...::timestamp) was Postgres-only.
        if previous_state:
            open_states = (
                await session.execute(
                    select(PackMLState).where(
                        PackMLState.asset_id == asset_uuid,
                        PackMLState.state == previous_state,
                        PackMLState.state_exited_at.is_(None),
                    )
                )
            ).scalars().all()

            for record in open_states:
                # state_entered_at reads back naive on SQLite; comparing it to an
                # aware timestamp raises TypeError, which the caller would turn
                # into a dropped message.
                entered_at = aware_utc(record.state_entered_at)
                record.state_exited_at = timestamp
                record.duration_seconds = (timestamp - entered_at).total_seconds()

        # Create new state entry
        state_record = PackMLState(
            asset_id=asset_uuid,
            state=new_state,
            previous_state=previous_state,
            state_entered_at=timestamp,
            meta_data=data.get('metadata', {})
        )
        session.add(state_record)

        # Update asset current state
        await session.execute(
            update(Asset)
            .where(Asset.id == asset_uuid)
            .values(current_packml_state=new_state)
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
            meta_data=data.get('metadata', {}),
            occurred_at=datetime.now(timezone.utc)
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
