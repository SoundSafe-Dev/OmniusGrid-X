"""WebSocket Manager for Real-Time Updates"""

import json
import asyncio
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
import structlog
from aiokafka import AIOKafkaConsumer
from datetime import datetime, timezone

from app.core.config import settings

logger = structlog.get_logger()


class WebSocketMessage:
    """Structured WebSocket message"""
    def __init__(
        self,
        msg_type: str,
        payload: Dict[str, Any],
        organization_id: Optional[str] = None,
        asset_id: Optional[str] = None
    ):
        self.type = msg_type
        self.payload = payload
        self.organization_id = organization_id
        self.asset_id = asset_id
        self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> dict:
        return {
            'type': self.type,
            'payload': self.payload,
            'organization_id': self.organization_id,
            'asset_id': self.asset_id,
            'timestamp': self.timestamp
        }


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts real-time updates.
    
    Flow:
    1. Clients connect via WebSocket
    2. Manager subscribes to Redpanda topics
    3. Messages from Redpanda are broadcast to connected clients
    """
    
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.consumer: AIOKafkaConsumer = None
        self._running = False
        
        # Track client subscriptions: websocket -> {asset_ids, message_types}
        self.subscriptions: Dict[WebSocket, Dict[str, Any]] = {}
        
        # Message queue for ingestion worker
        self._message_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._queue_task: Optional[asyncio.Task] = None
    
    async def connect(self):
        """Start the manager. The Kafka consumer is (re)created inside the
        broadcast loop with exponential backoff, so a broker that is down at
        startup no longer blocks the app or kills the loop permanently."""
        self._running = True

        # Start queue processor for ingestion worker messages
        self._queue_task = asyncio.create_task(self._process_message_queue())

        # Broadcast loop owns the consumer lifecycle + reconnection
        asyncio.create_task(self._broadcast_loop())

        logger.info("websocket_manager_started")

    async def _create_consumer(self) -> AIOKafkaConsumer:
        """Build, start, and subscribe a fresh Kafka consumer."""
        consumer = AIOKafkaConsumer(
            bootstrap_servers=settings.REDPANDA_URL,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='opsgrid-websocket-broadcast',
            auto_offset_reset='latest',
        )
        await consumer.start()
        consumer.subscribe(pattern='^telemetry\\..*')
        return consumer

    async def _safe_stop_consumer(self):
        """Stop the current consumer, swallowing errors, and clear it."""
        if self.consumer is not None:
            try:
                await self.consumer.stop()
            except Exception:
                pass
            self.consumer = None
    
    async def disconnect(self):
        """Clean up connections"""
        self._running = False
        
        # Stop queue processor
        if self._queue_task:
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass
        
        await self._safe_stop_consumer()
        logger.info("websocket_manager_disconnected")
    
    async def connect_client(self, websocket: WebSocket, organization_id: str,
                             subprotocol: str = None):
        """Accept WebSocket connection from client.

        subprotocol echoes the negotiated Sec-WebSocket-Protocol ("bearer.v1"
        token transport) back — browsers abort the handshake if they requested
        one and the server accepts with none.
        """
        await websocket.accept(subprotocol=subprotocol)
        
        if organization_id not in self.active_connections:
            self.active_connections[organization_id] = set()
        
        self.active_connections[organization_id].add(websocket)
        
        # Initialize empty subscription for this client
        self.subscriptions[websocket] = {
            'asset_ids': set(),  # Empty means all assets
            'message_types': {'telemetry', 'alarm', 'state', 'command_status'}
        }
        
        logger.info(
            "client_connected",
            organization_id=organization_id,
            total_clients=sum(len(s) for s in self.active_connections.values())
        )
        
        # Send connection confirmation
        try:
            await websocket.send_json({
                'type': 'connection_established',
                'payload': {'organization_id': organization_id}
            })
        except Exception:
            pass
    
    def disconnect_client(self, websocket: WebSocket, organization_id: str):
        """Remove client connection"""
        if organization_id in self.active_connections:
            self.active_connections[organization_id].discard(websocket)
        
        # Clean up subscriptions
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
        
        logger.info(
            "client_disconnected",
            organization_id=organization_id
        )
    
    async def broadcast_to_organization(self, organization_id: str, message: dict):
        """Broadcast message to all clients in an organization"""
        if organization_id not in self.active_connections:
            return
        
        disconnected = set()
        
        for connection in self.active_connections[organization_id]:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.active_connections[organization_id].discard(conn)
    
    def update_subscription(
        self,
        websocket: WebSocket,
        asset_ids: Optional[Set[str]] = None,
        message_types: Optional[Set[str]] = None
    ):
        """Update client subscription preferences"""
        if websocket not in self.subscriptions:
            self.subscriptions[websocket] = {'asset_ids': set(), 'message_types': set()}
        
        if asset_ids is not None:
            self.subscriptions[websocket]['asset_ids'] = set(asset_ids)
        
        if message_types is not None:
            self.subscriptions[websocket]['message_types'] = set(message_types)
        
        logger.debug(
            "subscription_updated",
            asset_ids=list(self.subscriptions[websocket]['asset_ids']),
            message_types=list(self.subscriptions[websocket]['message_types'])
        )
    
    def _should_send_to_client(self, websocket: WebSocket, message: WebSocketMessage) -> bool:
        """Check if message should be sent to client based on subscriptions"""
        if websocket not in self.subscriptions:
            return True  # No subscription filtering = send all
        
        sub = self.subscriptions[websocket]
        
        # Check message type filter
        if message.type not in sub['message_types']:
            return False
        
        # Check asset filter (empty set means all assets)
        if sub['asset_ids'] and message.asset_id and message.asset_id not in sub['asset_ids']:
            return False
        
        return True
    
    async def publish_telemetry(
        self,
        organization_id: str,
        asset_id: str,
        telemetry_data: Dict[str, Any],
        packml_state: Optional[str] = None
    ):
        """
        Publish telemetry update from ingestion worker.
        Called after successful database write.
        """
        message = WebSocketMessage(
            msg_type='telemetry',
            payload={
                'asset_id': asset_id,
                'telemetry': telemetry_data,
                'packml_state': packml_state
            },
            organization_id=organization_id,
            asset_id=asset_id
        )
        
        try:
            # Add to queue for async processing
            await self._message_queue.put(('org', organization_id, message))
        except asyncio.QueueFull:
            logger.warning("websocket_message_queue_full", dropped_message=True)
    
    async def publish_state_change(
        self,
        organization_id: str,
        asset_id: str,
        previous_state: Optional[str],
        new_state: str,
        metadata: Optional[Dict] = None
    ):
        """Publish PackML state change"""
        message = WebSocketMessage(
            msg_type='state',
            payload={
                'asset_id': asset_id,
                'previous_state': previous_state,
                'new_state': new_state,
                'metadata': metadata or {}
            },
            organization_id=organization_id,
            asset_id=asset_id
        )
        
        try:
            await self._message_queue.put(('org', organization_id, message))
        except asyncio.QueueFull:
            logger.warning("websocket_message_queue_full", dropped_message=True)
    
    async def publish_alarm(
        self,
        organization_id: str,
        asset_id: str,
        alarm_data: Dict[str, Any]
    ):
        """Publish alarm event"""
        message = WebSocketMessage(
            msg_type='alarm',
            payload={
                'asset_id': asset_id,
                **alarm_data
            },
            organization_id=organization_id,
            asset_id=asset_id
        )
        
        try:
            await self._message_queue.put(('org', organization_id, message))
        except asyncio.QueueFull:
            logger.warning("websocket_message_queue_full", dropped_message=True)
    
    async def _process_message_queue(self):
        """Process messages from ingestion worker and broadcast to clients.

        The error path here used to log and immediately re-enter the loop. That is
        safe only while every failure is transient: a PERSISTENT one (the queue bound
        to a dead event loop, below) raises on entry every time, so the loop spun at
        full CPU emitting the same line forever and never stopped. It was found by the
        API contract suite, where it made an operation hang indefinitely — each ASGI
        call runs on a new event loop, so after the first one this task could never
        succeed again. Two rules come out of it, and they apply to any `while running`
        worker: an error path with no delay is a spin, and a failure that cannot
        change is not something to retry.
        """
        consecutive_errors = 0
        while self._running:
            try:
                # Get message from queue with timeout
                try:
                    scope_type, scope_id, message = await asyncio.wait_for(
                        self._message_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Broadcast based on scope
                if scope_type == 'org':
                    await self._broadcast_filtered(scope_id, message)

                self._message_queue.task_done()
                consecutive_errors = 0

            except asyncio.CancelledError:
                # Shutdown, not a fault. Never swallow this into the retry path.
                raise
            except RuntimeError as e:
                # The queue's internal futures belong to the loop that first awaited
                # them. Once this task is running on a different loop, EVERY get()
                # raises and no amount of retrying helps, so stop rather than spin.
                if "different event loop" in str(e) or "attached to a different loop" in str(e):
                    logger.warning(
                        "message_queue_processor_stopped_wrong_loop",
                        error=str(e),
                        reason="queue is bound to another event loop; retrying cannot succeed",
                    )
                    return
                consecutive_errors += 1
                logger.error("message_queue_processor_error", error=str(e))
                await self._error_backoff(consecutive_errors)
            except Exception as e:
                consecutive_errors += 1
                logger.error("message_queue_processor_error", error=str(e))
                await self._error_backoff(consecutive_errors)

    async def _error_backoff(self, consecutive_errors: int) -> None:
        """Sleep between repeated failures so the loop cannot burn a core.

        Capped at 5s: long enough that a persistent fault costs nothing, short enough
        that recovery from a transient one is not noticeably delayed.
        """
        await asyncio.sleep(min(0.1 * (2 ** min(consecutive_errors - 1, 6)), 5.0))
    
    async def _broadcast_filtered(self, organization_id: str, message: WebSocketMessage):
        """Broadcast message to subscribed clients only"""
        if organization_id not in self.active_connections:
            return
        
        disconnected = set()
        
        for websocket in self.active_connections[organization_id]:
            try:
                # Check if client wants this message
                if self._should_send_to_client(websocket, message):
                    await websocket.send_json(message.to_dict())
            except Exception:
                disconnected.add(websocket)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.active_connections[organization_id].discard(conn)
            if conn in self.subscriptions:
                del self.subscriptions[conn]

    async def _broadcast_loop(self):
        """Continuously consume from Kafka and broadcast to clients.

        Owns the consumer lifecycle: if the broker drops or the consumer
        errors, the consumer is recreated with exponential backoff (1s -> 30s
        cap) instead of the loop exiting permanently."""
        backoff = 1.0
        backoff_cap = 30.0

        while self._running:
            try:
                if self.consumer is None:
                    self.consumer = await self._create_consumer()
                    logger.info("websocket_consumer_connected")
                backoff = 1.0  # reset after a successful (re)connect

                async for msg in self.consumer:
                    if not self._running:
                        break

                    try:
                        # Parse topic to extract organization
                        topic_parts = msg.topic.split('.')
                        if len(topic_parts) >= 2:
                            organization_id = topic_parts[1]

                            # Broadcast to relevant clients
                            await self.broadcast_to_organization(
                                organization_id,
                                {
                                    'type': 'telemetry',
                                    'topic': msg.topic,
                                    'data': msg.value,
                                    'timestamp': msg.timestamp
                                }
                            )
                    except Exception as e:
                        logger.error("broadcast_error", error=str(e))

            except asyncio.CancelledError:
                raise
            except Exception as e:
                await self._safe_stop_consumer()
                if not self._running:
                    break
                logger.error("broadcast_loop_error", error=str(e), reconnect_in_seconds=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, backoff_cap)


# Global instance
websocket_manager = WebSocketManager()
