"""
Epicor Connector

Connector for Epicor Kinetic using REST API:
- Epicor REST API integration
- OAuth2 or Basic authentication
- Business object queries
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


class EpicorConnector(ERPConnectorBase):
    """
    Epicor Kinetic connector.
    
    Connects to Epicor Kinetic via REST API to fetch
    financial data, supply chain data, and manufacturing data.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # Epicor-specific configuration
        self.company_id = config.configuration.get("company_id")
        self.site_id = config.configuration.get("site_id")
        
        # Build base URL for Epicor REST API
        self.api_url = f"{config.base_url}/api/v1"
        
        logger.info(
            "epicor_connector_initialized",
            api_url=self.api_url,
            company_id=self.company_id,
            site_id=self.site_id
        )
    
    async def authenticate(self) -> str:
        """
        Authenticate with Epicor using OAuth2 or Basic auth.
        
        Returns:
            str: Access token
        """
        auth_config = self.config.auth_config
        auth_type = self.config.auth_type
        
        if auth_type == AuthType.OAUTH2:
            # OAuth2 authentication
            access_token = auth_config.get("access_token")
        else:
            # Basic authentication
            access_token = auth_config.get("api_key")
        
        logger.info(
            "epicor_authentication_success",
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
        Fetch data from Epicor REST API.
        
        Args:
            entity_type: Epicor service name (e.g., 'Erp.BO.InvoiceSvc', 'Erp.BO.PartSvc')
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of entity data dictionaries
        """
        # Get authentication token
        token = await self.get_auth_token()
        
        # Build API URL
        entity_url = f"{self.api_url}/{entity_type}"
        
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
                "X-API-Key": self.company_id
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(entity_url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("value", [])
                    else:
                        error_text = await response.text()
                        raise Exception(f"Epicor API error: {response.status} - {error_text}")
        
        results = await self.execute_with_retry(_fetch)
        
        logger.info(
            "epicor_data_fetched",
            entity_type=entity_type,
            record_count=len(results)
        )
        
        return results
    
    async def subscribe_to_events(self, event_types: List[str]) -> bool:
        """
        Subscribe to Epicor events via webhooks.
        
        Args:
            event_types: List of event types to subscribe to
            
        Returns:
            bool: Success status
        """
        # Epicor uses webhooks for event subscriptions
        webhook_url = self.config.configuration.get("webhook_url")
        if not webhook_url:
            logger.warning("epicor_webhook_not_configured")
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
                    "X-API-Key": self.company_id
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        subscription_url,
                        headers=headers,
                        json=subscription_data
                    ) as response:
                        if response.status not in [200, 201]:
                            error_text = await response.text()
                            raise Exception(f"Epicor webhook subscription error: {response.status} - {error_text}")
            
            await self.execute_with_retry(_subscribe)
        
        logger.info(
            "epicor_event_subscriptions_created",
            event_types=event_types
        )
        
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Epicor connection.
        
        Returns:
            Dict with health status and details
        """
        try:
            # Try to fetch a small amount of data
            results = await self.fetch_data("Erp.BO.InvoiceSvc", limit=1)
            
            return {
                "status": "healthy",
                "message": "Epicor connection successful",
                "company_id": self.company_id,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "company_id": self.company_id,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
    
    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build Epicor OData filter string.
        
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
        """Fetch invoices from Epicor."""
        return await self.fetch_data("Erp.BO.InvoiceSvc", filters, limit)
    
    async def fetch_purchase_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch purchase orders from Epicor."""
        return await self.fetch_data("Erp.BO.PurchaseOrderSvc", filters, limit)
    
    async def fetch_parts(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch parts/inventory from Epicor."""
        return await self.fetch_data("Erp.BO.PartSvc", filters, limit)
    
    async def fetch_jobs(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch manufacturing jobs from Epicor."""
        return await self.fetch_data("Erp.BO.JobEntrySvc", filters, limit)
