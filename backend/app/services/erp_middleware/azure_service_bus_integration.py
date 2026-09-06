"""
Azure Service Bus Integration Service

Service for integrating with Azure Service Bus for ERP messaging:
- Service Bus queues and topics
- Event Grid integration
- Message batching and scheduling
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import structlog
import aiohttp
import json

from app.services.erp_connector_base import ERPConfig
from app.middleware.request_context import outbound_correlation_headers

logger = structlog.get_logger()


class AzureServiceBusIntegrationService:
    """
    Service for integrating with Azure Service Bus for ERP messaging.
    
    Provides integration with Azure Service Bus for reliable
    messaging between ERP systems and OmniusGrid.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        self.config = config
        self.organization_id = organization_id
        self.integration_id = integration_id
        
        # Azure Service Bus configuration
        self.namespace = config.configuration.get("namespace")
        self.resource_group = config.configuration.get("resource_group")
        self.subscription_id = config.configuration.get("subscription_id")
        
        # Build base URL for Azure Service Bus Management API
        self.api_url = f"https://management.azure.com/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/Microsoft.ServiceBus/namespaces/{self.namespace}"
        
        logger.info(
            "azure_service_bus_integration_service_initialized",
            namespace=self.namespace,
            resource_group=self.resource_group
        )
    

    def _session(self) -> aiohttp.ClientSession:
        """One session factory, so timeouts are set in exactly one place (FS-1008).

        Every `aiohttp.ClientSession()` in this file used to be constructed bare, which
        means aiohttp's default of **no total timeout**: a middleware host that accepts a
        connection and then stops responding holds the coroutine open indefinitely. The
        connector layer next door (`erp_connectors/*`) has always passed an explicit
        `ClientTimeout` built from `config.timeout`; the middleware layer never did, and
        the difference was invisible because both look like a session.

        A hung ERP middleware call is worse than a failed one: it consumes a slot in the
        pool FS-839 sized, it never reaches the retry classifier, and the circuit breaker
        in `erp_connector_base` cannot count a failure that has not happened yet.
        """
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            # FS-1014. Carries this request's correlation id outbound, so a failing ERP
            # call and the request that caused it can be joined. Empty outside a request
            # (a scheduled sync), because a freshly minted id would look like correlation
            # and correlate nothing.
            headers=outbound_correlation_headers(),
        )

    async def authenticate(self) -> str:
        """
        Authenticate with Azure using OAuth2.
        
        Returns:
            str: Access token
        """
        auth_config = self.config.auth_config
        
        # OAuth2 authentication with Azure AD
        token_url = f"https://login.microsoftonline.com/{auth_config.get('tenant_id')}/oauth2/token"
        
        async with self._session() as session:
            async with session.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": auth_config.get("client_id"),
                    "client_secret": auth_config.get("client_secret"),
                    "resource": "https://management.azure.com/"
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    access_token = data.get("access_token")
                    
                    logger.info("azure_service_bus_authentication_success")
                    return access_token
                else:
                    error_text = await response.text()
                    raise Exception(f"Azure authentication error: {response.status} - {error_text}")
    
    async def create_queue(
        self,
        queue_name: str,
        queue_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a Service Bus queue.
        
        Args:
            queue_name: Name of the queue
            queue_config: Optional queue configuration
            
        Returns:
            Dict with queue creation status
        """
        token = await self.authenticate()
        
        # Default queue configuration
        default_config = {
            "properties": {
                "lockDuration": "PT5M",
                "maxSizeInMegabytes": 1024,
                "requiresDuplicateDetection": False,
                "requiresSession": False,
                "defaultMessageTimeToLive": "P10675199DT2H48M5.4775807S",
                "deadLetteringOnMessageExpiration": False,
                "duplicateDetectionHistoryTimeWindow": "PT10M",
                "enableBatchedOperations": True,
                "enablePartitioning": True
            }
        }
        
        if queue_config:
            default_config["properties"].update(queue_config)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with self._session() as session:
            async with session.put(
                f"{self.api_url}/queues/{queue_name}?api-version=2022-10-01-preview",
                headers=headers,
                json=default_config
            ) as response:
                if response.status in [200, 201]:
                    logger.info(
                        "azure_service_bus_queue_created",
                        queue_name=queue_name
                    )
                    return {
                        "status": "success",
                        "queue_name": queue_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Azure Service Bus queue creation error: {response.status} - {error_text}")
    
    async def create_topic(
        self,
        topic_name: str,
        topic_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a Service Bus topic.
        
        Args:
            topic_name: Name of the topic
            topic_config: Optional topic configuration
            
        Returns:
            Dict with topic creation status
        """
        token = await self.authenticate()
        
        # Default topic configuration
        default_config = {
            "properties": {
                "lockDuration": "PT5M",
                "maxSizeInMegabytes": 1024,
                "requiresDuplicateDetection": False,
                "defaultMessageTimeToLive": "P10675199DT2H48M5.4775807S",
                "deadLetteringOnMessageExpiration": False,
                "duplicateDetectionHistoryTimeWindow": "PT10M",
                "enableBatchedOperations": True,
                "enablePartitioning": True
            }
        }
        
        if topic_config:
            default_config["properties"].update(topic_config)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with self._session() as session:
            async with session.put(
                f"{self.api_url}/topics/{topic_name}?api-version=2022-10-01-preview",
                headers=headers,
                json=default_config
            ) as response:
                if response.status in [200, 201]:
                    logger.info(
                        "azure_service_bus_topic_created",
                        topic_name=topic_name
                    )
                    return {
                        "status": "success",
                        "topic_name": topic_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Azure Service Bus topic creation error: {response.status} - {error_text}")
    
    async def create_subscription(
        self,
        topic_name: str,
        subscription_name: str,
        subscription_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a Service Bus topic subscription.
        
        Args:
            topic_name: Name of the topic
            subscription_name: Name of the subscription
            subscription_config: Optional subscription configuration
            
        Returns:
            Dict with subscription creation status
        """
        token = await self.authenticate()
        
        # Default subscription configuration
        default_config = {
            "properties": {
                "lockDuration": "PT5M",
                "requiresSession": False,
                "defaultMessageTimeToLive": "P10675199DT2H48M5.4775807S",
                "deadLetteringOnMessageExpiration": False,
                "deadLetteringOnFilterEvaluationExceptions": False,
                "enableBatchedOperations": True
            }
        }
        
        if subscription_config:
            default_config["properties"].update(subscription_config)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with self._session() as session:
            async with session.put(
                f"{self.api_url}/topics/{topic_name}/subscriptions/{subscription_name}?api-version=2022-10-01-preview",
                headers=headers,
                json=default_config
            ) as response:
                if response.status in [200, 201]:
                    logger.info(
                        "azure_service_bus_subscription_created",
                        topic_name=topic_name,
                        subscription_name=subscription_name
                    )
                    return {
                        "status": "success",
                        "topic_name": topic_name,
                        "subscription_name": subscription_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Azure Service Bus subscription creation error: {response.status} - {error_text}")
    
    async def send_message(
        self,
        queue_or_topic: str,
        message: Dict[str, Any],
        message_type: str = "queue"
    ) -> Dict[str, Any]:
        """
        Send a message to a Service Bus queue or topic.
        
        Args:
            queue_or_topic: Name of the queue or topic
            message: Message content
            message_type: Type ("queue" or "topic")
            
        Returns:
            Dict with send status
        """
        token = await self.authenticate()
        
        # Get connection string for sending messages
        connection_string = self.config.auth_config.get("connection_string")
        
        # In production, this would use the Azure Service Bus SDK
        # For now, we'll use the REST API
        message_body = {
            "body": json.dumps(message),
            "contentType": "application/json",
            "label": "ERP Event",
            "userProperties": {
                "organization_id": self.organization_id,
                "integration_id": self.integration_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        if message_type == "queue":
            url = f"{self.api_url}/queues/{queue_or_topic}/messages?api-version=2022-10-01-preview"
        else:
            url = f"{self.api_url}/topics/{queue_or_topic}/messages?api-version=2022-10-01-preview"
        
        async with self._session() as session:
            async with session.post(url, headers=headers, json=message_body) as response:
                if response.status == 201:
                    logger.info(
                        "azure_service_bus_message_sent",
                        queue_or_topic=queue_or_topic,
                        message_type=message_type
                    )
                    return {
                        "status": "success",
                        "queue_or_topic": queue_or_topic
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Azure Service Bus message send error: {response.status} - {error_text}")
    
    async def receive_messages(
        self,
        queue_or_subscription: str,
        message_type: str = "queue",
        max_messages: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Receive messages from a Service Bus queue or subscription.
        
        Args:
            queue_or_subscription: Name of the queue or subscription
            message_type: Type ("queue" or "subscription")
            max_messages: Maximum number of messages to receive
            
        Returns:
            List of messages
        """
        token = await self.authenticate()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        if message_type == "queue":
            url = f"{self.api_url}/queues/{queue_or_subscription}/messages/head?api-version=2022-10-01-preview&maxcount={max_messages}"
        else:
            # For subscriptions, format is topic/subscription
            topic, subscription = queue_or_subscription.split("/")
            url = f"{self.api_url}/topics/{topic}/subscriptions/{subscription}/messages/head?api-version=2022-10-01-preview&maxcount={max_messages}"
        
        async with self._session() as session:
            async with session.post(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(
                        "azure_service_bus_messages_received",
                        queue_or_subscription=queue_or_subscription,
                        message_count=len(data)
                    )
                    return data
                else:
                    error_text = await response.text()
                    raise Exception(f"Azure Service Bus message receive error: {response.status} - {error_text}")
    
    async def delete_queue(self, queue_name: str) -> Dict[str, Any]:
        """
        Delete a Service Bus queue.
        
        Args:
            queue_name: Name of the queue
            
        Returns:
            Dict with deletion status
        """
        token = await self.authenticate()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with self._session() as session:
            async with session.delete(
                f"{self.api_url}/queues/{queue_name}?api-version=2022-10-01-preview",
                headers=headers
            ) as response:
                if response.status in [200, 204]:
                    logger.info(
                        "azure_service_bus_queue_deleted",
                        queue_name=queue_name
                    )
                    return {
                        "status": "success",
                        "queue_name": queue_name
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"Azure Service Bus queue deletion error: {response.status} - {error_text}")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Azure Service Bus connection.
        
        Returns:
            Dict with health status
        """
        try:
            token = await self.authenticate()
            
            return {
                "status": "healthy",
                "message": "Azure Service Bus connection successful",
                "namespace": self.namespace,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "namespace": self.namespace,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
