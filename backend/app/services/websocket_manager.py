"""WebSocket Manager for Real-Time Updates"""

import json
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
import structlog
from aiokafka import AIOKafkaConsumer

from app.core.config import settings

logger = structlog.get_logger()


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
    
    async def connect(self):
        """Initialize WebSocket manager and Kafka consumer"""
        try:
            self.consumer = AIOKafkaConsumer(
                bootstrap_servers=settings.REDPANDA_URL,
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                group_id='opsgrid-websocket-broadcast',
                auto_offset_reset='latest',
            )
            await self.consumer.start()
            
            # Subscribe to telemetry topics
            self.consumer.subscribe(pattern='^telemetry\\..*')
            
            self._running = True
            
            # Start broadcast loop
            import asyncio
            asyncio.create_task(self._broadcast_loop())
            
            logger.info("websocket_manager_connected")
        except Exception as e:
            logger.error("websocket_manager_connection_failed", error=str(e))
    
    async def disconnect(self):
        """Clean up connections"""
        self._running = False
        if self.consumer:
            await self.consumer.stop()
        logger.info("websocket_manager_disconnected")
    
    async def connect_client(self, websocket: WebSocket, organization_id: str):
        """Accept WebSocket connection from client"""
        await websocket.accept()
        
        if organization_id not in self.active_connections:
            self.active_connections[organization_id] = set()
        
        self.active_connections[organization_id].add(websocket)
        
        logger.info(
            "client_connected",
            organization_id=organization_id,
            total_clients=sum(len(s) for s in self.active_connections.values())
        )
    
    def disconnect_client(self, websocket: WebSocket, organization_id: str):
        """Remove client connection"""
        if organization_id in self.active_connections:
            self.active_connections[organization_id].discard(websocket)
        
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
    
    async def _broadcast_loop(self):
        """Continuously consume from Kafka and broadcast to clients"""
        try:
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
        except Exception as e:
            logger.error("broadcast_loop_error", error=str(e))


# Global instance
websocket_manager = WebSocketManager()
