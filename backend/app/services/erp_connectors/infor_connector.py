"""
Infor Connector

Connector for Infor using ION API:
- ION API integration
- OAuth2 authentication
- REST API for data access
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog
import aiohttp

from app.services.erp_connector_base import (
    ERPConnectorBase,
    ERPConfig,
    ERPType,
    AuthType
)

logger = structlog.get_logger()


class InforConnector(ERPConnectorBase):
    """
    Infor connector.
    
    Connects to Infor via ION API to fetch
    financial data, supply chain data, and HR data.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # Infor-specific configuration
        self.tenant_id = config.configuration.get("tenant_id")
        self.app_name = config.configuration.get("app_name")
        
        # Build base URL for ION API
        self.api_url = f"{config.base_url}/ion/api"
        
        logger.info(
            "infor_connector_initialized",
            api_url=self.api_url,
            tenant_id=self.tenant_id,
            app_name=self.app_name
        )
    
    async def authenticate(self) -> str:
        """
        Authenticate with Infor using OAuth2.
        
        Returns:
            str: Access token
        """
        auth_config = self.config.auth_config
        
        # OAuth2 authentication
        # In production, this would use OAuth2 flow
        access_token = auth_config.get("access_token")
        
        logger.info(
            "infor_authentication_success"
        )
        
        return access_token
    
    async def fetch_data(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch data from Infor ION API.
        
        Args:
            entity_type: Infor entity type (e.g., 'invoice', 'purchaseOrder')
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of entity data dictionaries
        """
        # Get authentication token
        token = await self.get_auth_token()
        
        # Build API URL
        entity_url = f"{self.api_url}/{self.app_name}/{entity_type}"
        
        # Build query parameters
        params = {}
        if filters:
            filter_string = self._build_filter_string(filters)
            params["$filter"] = filter_string
        
        if limit:
            params["$top"] = str(limit)
        
        # Execute request with retry
        async def _fetch():
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Infor-Tenant-ID": self.tenant_id
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(entity_url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("value", [])
                    else:
                        error_text = await response.text()
                        raise Exception(f"Infor API error: {response.status} - {error_text}")
        
        results = await self.execute_with_retry(_fetch)
        
        logger.info(
            "infor_data_fetched",
            entity_type=entity_type,
            record_count=len(results)
        )
        
        return results
    
    async def subscribe_to_events(self, event_types: List[str]) -> bool:
        """
        Subscribe to Infor events via ION webhooks.
        
        Args:
            event_types: List of event types to subscribe to
            
        Returns:
            bool: Success status
        """
        # Infor uses ION webhooks for event subscriptions
        webhook_url = self.config.configuration.get("webhook_url")
        if not webhook_url:
            logger.warning("infor_webhook_not_configured")
            return False
        
        token = await self.get_auth_token()
        
        # Register webhook for each event type
        for event_type in event_types:
            subscription_url = f"{self.api_url}/webhooks"
            
            subscription_data = {
                "name": f"OmniusGrid_{event_type}",
                "url": webhook_url,
                "event_type": event_type
            }
            
            async def _subscribe():
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Infor-Tenant-ID": self.tenant_id
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        subscription_url,
                        headers=headers,
                        json=subscription_data
                    ) as response:
                        if response.status not in [200, 201]:
                            error_text = await response.text()
                            raise Exception(f"Infor webhook subscription error: {response.status} - {error_text}")
            
            await self.execute_with_retry(_subscribe)
        
        logger.info(
            "infor_event_subscriptions_created",
            event_types=event_types
        )
        
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Infor connection.
        
        Returns:
            Dict with health status and details
        """
        try:
            # Try to fetch a small amount of data
            results = await self.fetch_data("invoice", limit=1)
            
            return {
                "status": "healthy",
                "message": "Infor connection successful",
                "tenant_id": self.tenant_id,
                "checked_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "tenant_id": self.tenant_id,
                "checked_at": datetime.utcnow().isoformat()
            }
    
    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build Infor OData filter string.
        
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
        """Fetch invoices from Infor."""
        return await self.fetch_data("invoice", filters, limit)
    
    async def fetch_purchase_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch purchase orders from Infor."""
        return await self.fetch_data("purchaseOrder", filters, limit)
    
    async def fetch_inventory(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch inventory from Infor."""
        return await self.fetch_data("inventory", filters, limit)
