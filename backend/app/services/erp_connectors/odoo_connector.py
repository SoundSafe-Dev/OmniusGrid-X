"""
Odoo Connector

Connector for Odoo using XML-RPC or REST API:
- XML-RPC API integration
- REST API integration
- OAuth2 or API key authentication
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


class OdooConnector(ERPConnectorBase):
    """
    Odoo connector.
    
    Connects to Odoo via XML-RPC or REST API to fetch
    sales data, inventory data, and accounting data.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # Odoo-specific configuration
        self.db_name = config.configuration.get("db_name")
        self.api_type = config.configuration.get("api_type", "rest")  # rest or xmlrpc
        
        # Build base URL
        if self.api_type == "rest":
            self.api_url = f"{config.base_url}/api"
        else:
            self.api_url = f"{config.base_url}/xmlrpc/2"
        
        logger.info(
            "odoo_connector_initialized",
            api_url=self.api_url,
            api_type=self.api_type,
            db_name=self.db_name
        )
    
    async def authenticate(self) -> str:
        """
        Authenticate with Odoo using API key or OAuth2.
        
        Returns:
            str: Access token
        """
        auth_config = self.config.auth_config
        auth_type = self.config.auth_type
        
        if auth_type == AuthType.OAUTH2:
            # OAuth2 authentication
            access_token = auth_config.get("access_token")
        else:
            # API key authentication
            access_token = auth_config.get("api_key")
        
        logger.info(
            "odoo_authentication_success",
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
        Fetch data from Odoo API.
        
        Args:
            entity_type: Odoo model name (e.g., 'sale.order', 'product.product')
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
            params["domain"] = filter_string
        
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
                        return data.get("result", [])
                    else:
                        error_text = await response.text()
                        raise Exception(f"Odoo API error: {response.status} - {error_text}")
        
        results = await self.execute_with_retry(_fetch)
        
        logger.info(
            "odoo_data_fetched",
            entity_type=entity_type,
            record_count=len(results)
        )
        
        return results
    
    async def subscribe_to_events(self, event_types: List[str]) -> bool:
        """
        Subscribe to Odoo events via webhooks.
        
        Args:
            event_types: List of event types to subscribe to
            
        Returns:
            bool: Success status
        """
        # Odoo uses webhooks for event subscriptions
        webhook_url = self.config.configuration.get("webhook_url")
        if not webhook_url:
            logger.warning("odoo_webhook_not_configured")
            return False
        
        token = await self.get_auth_token()
        
        # Register webhook for each event type
        for event_type in event_types:
            subscription_url = f"{self.api_url}/webhooks"
            
            subscription_data = {
                "name": f"OmniusGrid_{event_type}",
                "url": webhook_url,
                "model": event_type
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
                            raise Exception(f"Odoo webhook subscription error: {response.status} - {error_text}")
            
            await self.execute_with_retry(_subscribe)
        
        logger.info(
            "odoo_event_subscriptions_created",
            event_types=event_types
        )
        
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Odoo connection.
        
        Returns:
            Dict with health status and details
        """
        try:
            # Try to fetch a small amount of data
            results = await self.fetch_data("sale.order", limit=1)
            
            return {
                "status": "healthy",
                "message": "Odoo connection successful",
                "db_name": self.db_name,
                "checked_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "db_name": self.db_name,
                "checked_at": datetime.utcnow().isoformat()
            }
    
    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build Odoo domain filter string.
        
        Args:
            filters: Filter dictionary
            
        Returns:
            str: Filter string in Odoo domain format
        """
        filter_parts = []
        
        for field, value in filters.items():
            if isinstance(value, str):
                filter_parts.append(f"['{field}', '=', '{value}']")
            elif isinstance(value, int) or isinstance(value, float):
                filter_parts.append(f"['{field}', '=', {value}]")
            elif isinstance(value, bool):
                filter_parts.append(f"['{field}', '=', {str(value).lower()}]")
        
        return f"[{', '.join(filter_parts)}]"
    
    async def fetch_sales_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch sales orders from Odoo."""
        return await self.fetch_data("sale.order", filters, limit)
    
    async def fetch_products(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch products from Odoo."""
        return await self.fetch_data("product.product", filters, limit)
    
    async def fetch_customers(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch customers from Odoo."""
        return await self.fetch_data("res.partner", filters, limit)
    
    async def fetch_invoices(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch invoices from Odoo."""
        return await self.fetch_data("account.move", filters, limit)
