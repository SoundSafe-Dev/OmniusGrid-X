"""
MuleSoft Integration Service

Service for integrating with MuleSoft Anypoint Platform:
- MuleSoft API Manager integration
- Event-driven architecture support
- API proxy and gateway patterns
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import structlog
import aiohttp

from app.services.erp_connector_base import ERPConfig

logger = structlog.get_logger()


class MuleSoftIntegrationService:
    """
    Service for integrating with MuleSoft Anypoint Platform.
    
    Provides integration with MuleSoft for API management,
    event-driven architecture, and middleware patterns.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        self.config = config
        self.organization_id = organization_id
        self.integration_id = integration_id
        
        # MuleSoft-specific configuration
        self.api_manager_url = config.configuration.get("api_manager_url")
        self.runtime_manager_url = config.configuration.get("runtime_manager_url")
        self.environment = config.configuration.get("environment", "production")
        
        logger.info(
            "mulesoft_integration_service_initialized",
            api_manager_url=self.api_manager_url,
            environment=self.environment
        )
    
    async def authenticate(self) -> str:
        """
        Authenticate with MuleSoft using OAuth2.
        
        Returns:
            str: Access token
        """
        auth_config = self.config.auth_config
        
        # OAuth2 authentication with MuleSoft
        token_url = f"{self.api_manager_url}/accounts/login/oauth2/token"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                token_url,
                data={
                    "client_id": auth_config.get("client_id"),
                    "client_secret": auth_config.get("client_secret"),
                    "grant_type": "client_credentials"
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    access_token = data.get("access_token")
                    
                    logger.info("mulesoft_authentication_success")
                    return access_token
                else:
                    error_text = await response.text()
                    raise Exception(f"MuleSoft authentication error: {response.status} - {error_text}")
    
    async def invoke_api(
        self,
        api_name: str,
        endpoint: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Invoke an API through MuleSoft API Manager.
        
        Args:
            api_name: API name
            endpoint: API endpoint
            method: HTTP method
            payload: Optional request payload
            
        Returns:
            Dict with API response
        """
        token = await self.authenticate()
        
        # Build API URL
        api_url = f"{self.api_manager_url}/api/{api_name}/{endpoint}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(api_url, headers=headers) as response:
                    return await self._handle_response(response)
            elif method == "POST":
                async with session.post(api_url, headers=headers, json=payload) as response:
                    return await self._handle_response(response)
            elif method == "PUT":
                async with session.put(api_url, headers=headers, json=payload) as response:
                    return await self._handle_response(response)
            elif method == "DELETE":
                async with session.delete(api_url, headers=headers) as response:
                    return await self._handle_response(response)
    
    async def _handle_response(self, response: aiohttp.ClientResponse) -> Dict[str, Any]:
        """Handle API response."""
        if response.status in [200, 201, 204]:
            try:
                data = await response.json()
                return {
                    "status": "success",
                    "data": data,
                    "status_code": response.status
                }
            # FS-982. Was a bare `except:`, which catches BaseException -- so a
            # `asyncio.CancelledError` raised while awaiting the body was absorbed and
            # reported as a SUCCESS with no data, and the caller carried on inside a task
            # that was supposed to be stopping. A 204 legitimately has no body and a
            # non-JSON 200 is a real MuleSoft response shape, so returning success without
            # `data` is correct for those; it is not correct for a cancellation.
            #
            # `aiohttp` raises ContentTypeError for a non-JSON content type and
            # ValueError/JSONDecodeError for a malformed body; both are the intended case
            # here, and both are Exception subclasses.
            except (aiohttp.ContentTypeError, ValueError) as exc:
                logger.debug(
                    "mulesoft_response_had_no_json_body",
                    status_code=response.status,
                    error=str(exc),
                )
                return {
                    "status": "success",
                    "status_code": response.status
                }
        else:
            error_text = await response.text()
            return {
                "status": "error",
                "error": error_text,
                "status_code": response.status
            }
    
    async def subscribe_to_events(
        self,
        event_source: str,
        event_types: List[str],
        callback_url: str
    ) -> Dict[str, Any]:
        """
        Subscribe to events through MuleSoft event hub.
        
        Args:
            event_source: Event source (e.g., ERP system)
            event_types: List of event types to subscribe to
            callback_url: Callback URL for event delivery
            
        Returns:
            Dict with subscription status
        """
        token = await self.authenticate()
        
        subscription_url = f"{self.runtime_manager_url}/events/subscriptions"
        
        subscription_data = {
            "eventSource": event_source,
            "eventTypes": event_types,
            "callbackUrl": callback_url,
            "organizationId": self.organization_id,
            "integrationId": self.integration_id
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                subscription_url,
                headers=headers,
                json=subscription_data
            ) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    logger.info(
                        "mulesoft_event_subscription_created",
                        event_source=event_source,
                        event_types=event_types
                    )
                    return {
                        "status": "success",
                        "subscription_id": data.get("subscriptionId"),
                        "event_types": event_types
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"MuleSoft event subscription error: {response.status} - {error_text}")
    
    async def publish_event(
        self,
        event_type: str,
        event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Publish an event to MuleSoft event hub.
        
        Args:
            event_type: Event type
            event_data: Event data
            
        Returns:
            Dict with publish status
        """
        token = await self.authenticate()
        
        event_url = f"{self.runtime_manager_url}/events/publish"
        
        event_payload = {
            "eventType": event_type,
            "eventData": event_data,
            "organizationId": self.organization_id,
            "integrationId": self.integration_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                event_url,
                headers=headers,
                json=event_payload
            ) as response:
                if response.status in [200, 201]:
                    logger.info(
                        "mulesoft_event_published",
                        event_type=event_type
                    )
                    return {
                        "status": "success",
                        "event_type": event_type
                    }
                else:
                    error_text = await response.text()
                    raise Exception(f"MuleSoft event publish error: {response.status} - {error_text}")
    
    async def get_api_policies(
        self,
        api_name: str
    ) -> List[Dict[str, Any]]:
        """
        Get API policies from MuleSoft API Manager.
        
        Args:
            api_name: API name
            
        Returns:
            List of API policies
        """
        token = await self.authenticate()
        
        policies_url = f"{self.api_manager_url}/api/{api_name}/policies"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(policies_url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("policies", [])
                else:
                    error_text = await response.text()
                    raise Exception(f"MuleSoft API policies error: {response.status} - {error_text}")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on MuleSoft connection.
        
        Returns:
            Dict with health status
        """
        try:
            token = await self.authenticate()
            
            return {
                "status": "healthy",
                "message": "MuleSoft connection successful",
                "environment": self.environment,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "environment": self.environment,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
