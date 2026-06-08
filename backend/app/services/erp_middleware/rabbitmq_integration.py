"""
RabbitMQ Integration Service

Service for integrating with RabbitMQ for ERP messaging:
- Queue and exchange management
- Message publishing and consuming
- AMQP protocol support
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog
import aiohttp
import json

from app.services.erp_connector_base import ERPConfig

logger = structlog.get_logger()


class RabbitMQIntegrationService:
    """
    Service for integrating with RabbitMQ for ERP messaging.
    
    Provides integration with RabbitMQ for reliable
    messaging between ERP systems and OmniusGrid.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        self.config = config
        self.organization_id = organization_id
        self.integration_id = integration_id
        
        # RabbitMQ configuration
        self.management_url = config.configuration.get("management_url")
        self.vhost = config.configuration.get("vhost", "/")
        self.username = config.auth_config.get("username")
        self.password = config.auth_config.get("password")
        
        logger.info(
            "rabbitmq_integration_service_initialized",
            management_url=self.management_url,
            vhost=self.vhost
        )
    
    async def create_queue(
        self,
        queue_name: str,
        queue_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a RabbitMQ queue.
        
        Args:
            queue_name: Name of the queue
            queue_config: Optional queue configuration
            
        Returns:
            Dict with queue creation status
        """
        # Default queue configuration
        default_config = {
            "durable": True,
            "auto_delete": False,
            "arguments": {
                "x-message-ttl": 86400000,  # 24 hours
                "x-max-length": 100000
            }
        }
        
        if queue_config:
            default_config.update(queue_config)
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # Encode credentials
        import base64
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        
        headers["Authorization"] = f"Basic {credentials}"
        
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{self.management_url}/api/queues/{self.vhost}/{queue_name}",
                headers=headers,
                json=default_config
            ) as response:
                if response.status in [200, 201]:
                    logger.info(
                        "rabbitmq_queue_created",
                        queue_name=queue_name
                    )
                    return {
                        "status": "success",
                        "queue_name": queue_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"RabbitMQ queue creation error: {response.status} - {error_text}")
    
    async def create_exchange(
        self,
        exchange_name: str,
        exchange_type: str = "direct",
        exchange_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a RabbitMQ exchange.
        
        Args:
            exchange_name: Name of the exchange
            exchange_type: Type of exchange (direct, topic, fanout, headers)
            exchange_config: Optional exchange configuration
            
        Returns:
            Dict with exchange creation status
        """
        # Default exchange configuration
        default_config = {
            "type": exchange_type,
            "durable": True,
            "auto_delete": False
        }
        
        if exchange_config:
            default_config.update(exchange_config)
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # Encode credentials
        import base64
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        
        headers["Authorization"] = f"Basic {credentials}"
        
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{self.management_url}/api/exchanges/{self.vhost}/{exchange_name}",
                headers=headers,
                json=default_config
            ) as response:
                if response.status in [200, 201]:
                    logger.info(
                        "rabbitmq_exchange_created",
                        exchange_name=exchange_name,
                        exchange_type=exchange_type
                    )
                    return {
                        "status": "success",
                        "exchange_name": exchange_name,
                        "exchange_type": exchange_type
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"RabbitMQ exchange creation error: {response.status} - {error_text}")
    
    async def create_binding(
        self,
        exchange_name: str,
        queue_name: str,
        routing_key: str,
        binding_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a binding between exchange and queue.
        
        Args:
            exchange_name: Name of the exchange
            queue_name: Name of the queue
            routing_key: Routing key
            binding_config: Optional binding configuration
            
        Returns:
            Dict with binding creation status
        """
        # Default binding configuration
        default_config = {
            "routing_key": routing_key
        }
        
        if binding_config:
            default_config.update(binding_config)
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # Encode credentials
        import base64
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        
        headers["Authorization"] = f"Basic {credentials}"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.management_url}/api/bindings/{self.vhost}/e/{exchange_name}/q/{queue_name}",
                headers=headers,
                json=default_config
            ) as response:
                if response.status in [200, 201]:
                    logger.info(
                        "rabbitmq_binding_created",
                        exchange_name=exchange_name,
                        queue_name=queue_name,
                        routing_key=routing_key
                    )
                    return {
                        "status": "success",
                        "exchange_name": exchange_name,
                        "queue_name": queue_name,
                        "routing_key": routing_key
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"RabbitMQ binding creation error: {response.status} - {error_text}")
    
    async def publish_message(
        self,
        exchange_name: str,
        routing_key: str,
        message: Dict[str, Any],
        message_properties: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Publish a message to an exchange.
        
        Args:
            exchange_name: Name of the exchange
            routing_key: Routing key
            message: Message content
            message_properties: Optional message properties
            
        Returns:
            Dict with publish status
        """
        # Default message properties
        default_properties = {
            "content_type": "application/json",
            "delivery_mode": 2,  # Persistent
            "headers": {
                "organization_id": self.organization_id,
                "integration_id": self.integration_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
        if message_properties:
            default_properties.update(message_properties)
        
        # Build message payload
        payload = {
            "properties": default_properties,
            "routing_key": routing_key,
            "payload": json.dumps(message),
            "payload_encoding": "string"
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # Encode credentials
        import base64
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        
        headers["Authorization"] = f"Basic {credentials}"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.management_url}/api/exchanges/{self.vhost}/{exchange_name}/publish",
                headers=headers,
                json=payload
            ) as response:
                if response.status in [200, 204]:
                    logger.info(
                        "rabbitmq_message_published",
                        exchange_name=exchange_name,
                        routing_key=routing_key
                    )
                    return {
                        "status": "success",
                        "exchange_name": exchange_name,
                        "routing_key": routing_key
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"RabbitMQ message publish error: {response.status} - {error_text}")
    
    async def get_messages(
        self,
        queue_name: str,
        count: int = 10,
        ack_mode: str = "ack_requeue_true"
    ) -> List[Dict[str, Any]]:
        """
        Get messages from a queue.
        
        Args:
            queue_name: Name of the queue
            count: Number of messages to get
            ack_mode: Acknowledgment mode
            
        Returns:
            List of messages
        """
        headers = {
            "Content-Type": "application/json"
        }
        
        # Encode credentials
        import base64
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        
        headers["Authorization"] = f"Basic {credentials}"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.management_url}/api/queues/{self.vhost}/{queue_name}/get",
                headers=headers,
                json={
                    "count": count,
                    "ackmode": ack_mode,
                    "encoding": "auto"
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(
                        "rabbitmq_messages_received",
                        queue_name=queue_name,
                        message_count=len(data)
                    )
                    return data
                else:
                    error_text = await response.text()
                    raise Exception(f"RabbitMQ message get error: {response.status} - {error_text}")
    
    async def delete_queue(self, queue_name: str) -> Dict[str, Any]:
        """
        Delete a RabbitMQ queue.
        
        Args:
            queue_name: Name of the queue
            
        Returns:
            Dict with deletion status
        """
        headers = {
            "Content-Type": "application/json"
        }
        
        # Encode credentials
        import base64
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        
        headers["Authorization"] = f"Basic {credentials}"
        
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{self.management_url}/api/queues/{self.vhost}/{queue_name}",
                headers=headers
            ) as response:
                if response.status in [200, 204]:
                    logger.info(
                        "rabbitmq_queue_deleted",
                        queue_name=queue_name
                    )
                    return {
                        "status": "success",
                        "queue_name": queue_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"RabbitMQ queue deletion error: {response.status} - {error_text}")
    
    async def get_queue_info(self, queue_name: str) -> Dict[str, Any]:
        """
        Get information about a queue.
        
        Args:
            queue_name: Name of the queue
            
        Returns:
            Dict with queue information
        """
        headers = {
            "Content-Type": "application/json"
        }
        
        # Encode credentials
        import base64
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        
        headers["Authorization"] = f"Basic {credentials}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.management_url}/api/queues/{self.vhost}/{queue_name}",
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    error_text = await response.text()
                    raise Exception(f"RabbitMQ queue info error: {response.status} - {error_text}")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on RabbitMQ connection.
        
        Returns:
            Dict with health status
        """
        try:
            # Try to get overview
            headers = {
                "Content-Type": "application/json"
            }
            
            # Encode credentials
            import base64
            credentials = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            
            headers["Authorization"] = f"Basic {credentials}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.management_url}/api/overview",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        return {
                            "status": "healthy",
                            "message": "RabbitMQ connection successful",
                            "vhost": self.vhost,
                            "checked_at": datetime.utcnow().isoformat()
                        }
                    else:
                        raise Exception(f"RabbitMQ health check failed: {response.status}")
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "vhost": self.vhost,
                "checked_at": datetime.utcnow().isoformat()
            }
