"""
NetSuite Connector

Connector for NetSuite using SuiteTalk REST API:
- SuiteTalk REST API integration
- OAuth2 or Token-based authentication
- Saved search integration
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import structlog
import aiohttp

from app.services.erp_connector_base import (
    ERPConnectorBase,
    ERPConfig,
    ERPType,
    AuthType
)

logger = structlog.get_logger()


class NetSuiteConnector(ERPConnectorBase):
    """
    NetSuite connector.
    
    Connects to NetSuite via SuiteTalk REST API to fetch
    financial data, inventory data, and CRM data.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # NetSuite-specific configuration
        self.account_id = config.configuration.get("account_id")
        self.realm = config.configuration.get("realm")
        
        # Build base URL for SuiteTalk REST API
        self.api_url = f"https://{self.account_id}.suitetalk.net/rest/services"
        
        logger.info(
            "netsuite_connector_initialized",
            api_url=self.api_url,
            account_id=self.account_id,
            realm=self.realm
        )
    
    async def authenticate(self) -> str:
        """
        Authenticate with NetSuite using OAuth2 or Token-based auth.
        
        Returns:
            str: Access token
        """
        auth_config = self.config.auth_config
        auth_type = self.config.auth_type
        
        if auth_type == AuthType.OAUTH2:
            # OAuth2 authentication
            # In production, this would use OAuth2 flow
            access_token = auth_config.get("access_token")
        else:
            # Token-based authentication
            access_token = auth_config.get("token")
        
        logger.info(
            "netsuite_authentication_success",
            auth_type=auth_type.value
        )
        
        return access_token
    
    async def fetch_data(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch data from NetSuite SuiteTalk API.
        
        Args:
            entity_type: NetSuite entity type (e.g., 'invoice', 'salesOrder')
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of entity data dictionaries
        """
        # Get authentication token
        token = await self.get_auth_token()
        
        # Build API URL
        entity_url = f"{self.api_url}/record/v1/{entity_type}"
        
        # Build query parameters
        params = {}
        if filters:
            filter_string = self._build_filter_string(filters)
            params["q"] = filter_string
        
        if limit:
            params["limit"] = str(limit)
        
        # Execute request with retry
        async def _fetch():
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(entity_url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("items", [])
                    else:
                        error_text = await response.text()
                        raise Exception(f"NetSuite API error: {response.status} - {error_text}")
        
        results = await self.execute_with_retry(_fetch)
        
        logger.info(
            "netsuite_data_fetched",
            entity_type=entity_type,
            record_count=len(results)
        )
        
        return results
    
    async def subscribe_to_events(self, event_types: List[str]) -> bool:
        """
        Subscribe to NetSuite events via saved search webhooks.
        
        Args:
            event_types: List of event types to subscribe to
            
        Returns:
            bool: Success status
        """
        # NetSuite uses saved search webhooks for event subscriptions
        webhook_url = self.config.configuration.get("webhook_url")
        if not webhook_url:
            logger.warning("netsuite_webhook_not_configured")
            return False
        
        token = await self.get_auth_token()
        
        # Register webhook for each event type
        for event_type in event_types:
            subscription_url = f"{self.api_url}/rest/webhooks/v1"
            
            subscription_data = {
                "name": f"OmniusGrid_{event_type}",
                "url": webhook_url,
                "event_type": event_type
            }
            
            async def _subscribe():
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
                        if response.status not in [200, 201]:
                            error_text = await response.text()
                            raise Exception(f"NetSuite webhook subscription error: {response.status} - {error_text}")
            
            await self.execute_with_retry(_subscribe)
        
        logger.info(
            "netsuite_event_subscriptions_created",
            event_types=event_types
        )
        
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on NetSuite connection.
        
        Returns:
            Dict with health status and details
        """
        try:
            # Try to fetch a small amount of data
            results = await self.fetch_data("invoice", limit=1)
            
            return {
                "status": "healthy",
                "message": "NetSuite connection successful",
                "account_id": self.account_id,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "account_id": self.account_id,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
    
    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build NetSuite SuiteTalk filter string.
        
        Args:
            filters: Filter dictionary
            
        Returns:
            str: Filter string
        """
        filter_parts = []
        
        for field, value in filters.items():
            if isinstance(value, str):
                filter_parts.append(f"{field} eq '{value}'")
            elif isinstance(value, int) or isinstance(value, float):
                filter_parts.append(f"{field} eq {value}")
            elif isinstance(value, bool):
                filter_parts.append(f"{field} eq {str(value).lower()}")
        
        return " and ".join(filter_parts)
    
    async def fetch_invoices(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch invoices from NetSuite."""
        return await self.fetch_data("invoice", filters, limit)
    
    async def fetch_sales_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch sales orders from NetSuite."""
        return await self.fetch_data("salesOrder", filters, limit)
    
    async def fetch_inventory(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch inventory from NetSuite."""
        return await self.fetch_data("inventoryItem", filters, limit)
    
    async def fetch_customers(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch customers from NetSuite."""
        return await self.fetch_data("customer", filters, limit)
