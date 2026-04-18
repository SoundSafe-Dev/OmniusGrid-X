"""
Secure Cloud Gateway - Outbound-only mTLS Bridge
Sends feature vectors to cloud without allowing inbound connections
"""

import asyncio
import json
import ssl
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import structlog
import aiomqtt

from app.core.config import settings

logger = structlog.get_logger()


@dataclass
class CloudEndpoint:
    """Cloud endpoint configuration"""
    host: str
    port: int
    topic_prefix: str
    client_id: str
    use_mtls: bool = True


class CloudGateway:
    """
    Secure outbound-only cloud gateway.
    
    Architecture:
    - Local rack initiates OUTBOUND mTLS connection to cloud
    - Cloud NEVER connects inbound to factory
    - Feature vectors and events are queued locally
    - Batched transmission with exponential backoff on failure
    """
    
    def __init__(self):
        self.endpoint = CloudEndpoint(
            host=settings.CLOUD_MQTT_HOST or 'cloud.opsgrid.io',
            port=settings.CLOUD_MQTT_PORT or 8883,
            topic_prefix=settings.CLOUD_TOPIC_PREFIX or 'opsgrid/factories/dev',
            client_id=f"opsgrid-edge-{settings.ORGANIZATION_ID}",
            use_mtls=settings.MTLS_ENABLED
        )

        self._queue: List[Dict] = []
        self._client: Optional[aiomqtt.Client] = None
        self._connected = False
        self._max_queue_size = 10000
        self._batch_size = 100
        self._flush_interval = 30  # seconds

        # mTLS configuration
        self._ssl_context: Optional[ssl.SSLContext] = None
        if self.endpoint.use_mtls:
            self._setup_mtls()
    
    def _setup_mtls(self):
        """Setup mutual TLS authentication"""
        self._ssl_context = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH,
            cafile=settings.MTLS_CA_CERT_PATH or '/certs/cloud-ca.crt'
        )
        
        # Load client certificate for mutual auth
        self._ssl_context.load_cert_chain(
            certfile=settings.MTLS_CLIENT_CERT_PATH or '/certs/edge-client.crt',
            keyfile=settings.MTLS_CLIENT_KEY_PATH or '/certs/edge-client.key'
        )
        
        # Require certificate verification
        self._ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        logger.info("mtls_configured", 
                   ca_cert=settings.MTLS_CA_CERT_PATH,
                   client_cert=settings.MTLS_CLIENT_CERT_PATH)
    
    async def queue_feature_vector(self, vector: Dict):
        """Queue a feature vector for cloud egress"""
        if len(self._queue) >= self._max_queue_size:
            # Drop oldest if queue full (shedding)
            self._queue.pop(0)
            logger.warning("cloud_queue_shedded_oldest")
        
        vector['_queued_at'] = datetime.utcnow().isoformat()
        self._queue.append(vector)
    
    async def queue_discrete_event(self, event_type: str, data: Dict):
        """Queue a discrete event (state change, alarm, etc.)"""
        event = {
            'type': 'discrete_event',
            'event_type': event_type,
            'data': data,
            'timestamp': datetime.utcnow().isoformat(),
            '_queued_at': datetime.utcnow().isoformat(),
        }
        await self.queue_feature_vector(event)
    
    async def start(self):
        """Start the cloud gateway"""
        logger.info("cloud_gateway_starting", 
                   host=self.endpoint.host,
                   port=self.endpoint.port)
        
        asyncio.create_task(self._connection_manager())
        asyncio.create_task(self._flush_loop())
    
    async def _connection_manager(self):
        """Manage persistent outbound connection"""
        reconnect_delay = 5
        max_reconnect_delay = 300  # 5 minutes
        
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self.endpoint.host,
                    port=self.endpoint.port,
                    client_id=self.endpoint.client_id,
                    tls_context=self._ssl_context,
                    tls_insecure=False,
                ) as client:
                    self._client = client
                    self._connected = True
                    reconnect_delay = 5  # Reset on success
                    
                    logger.info("cloud_connected", 
                               host=self.endpoint.host,
                               client_id=self.endpoint.client_id)
                    
                    # Keep connection alive
                    while self._connected:
                        await asyncio.sleep(1)
                        
            except Exception as e:
                self._connected = False
                self._client = None
                
                logger.error("cloud_connection_failed",
                           error=str(e),
                           reconnect_delay=reconnect_delay)
                
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
    
    async def _flush_loop(self):
        """Periodically flush queued data to cloud"""
        while True:
            await asyncio.sleep(self._flush_interval)
            
            if not self._connected or not self._client:
                continue
            
            if len(self._queue) == 0:
                continue
            
            await self._flush_batch()
    
    async def _flush_batch(self):
        """Send batched data to cloud"""
        if not self._client:
            return
        
        # Take batch from queue
        batch_size = min(self._batch_size, len(self._queue))
        batch = self._queue[:batch_size]
        
        try:
            # Publish each message
            for msg in batch:
                asset_id = msg.get('asset_id', 'unknown')
                msg_type = msg.get('type', 'unknown')
                
                # Determine topic
                topic = f"{self.endpoint.topic_prefix}/{asset_id}/{msg_type}"
                
                # Publish
                await self._client.publish(
                    topic,
                    json.dumps(msg),
                    qos=1  # At least once delivery
                )
            
            # Remove sent messages from queue
            self._queue = self._queue[batch_size:]
            
            logger.info("cloud_batch_sent", 
                       count=batch_size,
                       queue_remaining=len(self._queue))
            
        except Exception as e:
            logger.error("cloud_batch_failed", 
                        error=str(e),
                        batch_size=batch_size)
            # Messages stay in queue for retry
    
    async def stop(self):
        """Stop the gateway"""
        logger.info("cloud_gateway_stopping")
        self._connected = False
        if self._client:
            await self._client.disconnect()
    
    def get_stats(self) -> Dict:
        """Get gateway statistics"""
        return {
            'connected': self._connected,
            'queue_size': len(self._queue),
            'endpoint': self.endpoint.host,
            'mtls_enabled': self.endpoint.use_mtls,
        }


# Global instance
cloud_gateway = CloudGateway()
