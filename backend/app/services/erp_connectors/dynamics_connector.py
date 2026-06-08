"""
Microsoft Dynamics 365 Connector

Connector for Microsoft Dynamics 365 using Dataverse API and Graph API:
- Dataverse API for finance, supply chain, projects
- Microsoft Graph API for CRM data
- Azure AD authentication with MSAL
- Power Automate webhook integration
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog
import aiohttp
import msal

from app.services.erp_connector_base import (
    ERPConnectorBase,
    ERPConfig,
    ERPType,
    AuthType
)

logger = structlog.get_logger()


class DynamicsConnector(ERPConnectorBase):
    """
    Microsoft Dynamics 365 connector.
    
    Connects to Dynamics 365 via Dataverse API and Graph API to fetch
    financial data, supply chain data, project data, and CRM data.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # Dynamics-specific configuration
        self.environment = config.configuration.get("environment")
        self.api_type = config.configuration.get("api_type", "dataverse")  # dataverse or graph
        
        # Build base URLs
        if self.api_type == "dataverse":
            self.api_url = f"https://{self.environment}.api.crm.dynamics.com/api/data/v9.2/"
        else:
            self.api_url = "https://graph.microsoft.com/v1.0/"
        
        # MSAL application
        self.msal_app = None
        self._init_msal_app()
        
        logger.info(
            "dynamics_connector_initialized",
            api_url=self.api_url,
            api_type=self.api_type,
            environment=self.environment
        )
    
    def _init_msal_app(self):
        """Initialize MSAL application for Azure AD authentication."""
        auth_config = self.config.auth_config
        
        self.msal_app = msal.ConfidentialClientApplication(
            client_id=auth_config.get("client_id"),
            client_credential=auth_config.get("client_secret"),
            authority=f"https://login.microsoftonline.com/{auth_config.get('tenant_id')}"
        )
    
    async def authenticate(self) -> str:
        """
        Authenticate with Microsoft using Azure AD.
        
        Returns:
            str: Access token
        """
        # Acquire token for the appropriate scope
        if self.api_type == "dataverse":
            scope = [f"https://{self.environment}.api.crm.dynamics.com/.default"]
        else:
            scope = ["https://graph.microsoft.com/.default"]
        
        result = self.msal_app.acquire_token_for_client(scopes=scope)
        
        if "access_token" in result:
            access_token = result["access_token"]
            
            logger.info(
                "dynamics_authentication_success",
                api_type=self.api_type
            )
            
            return access_token
        else:
            raise Exception(f"Authentication failed: {result.get('error_description')}")
    
    async def fetch_data(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch data from Dynamics 365 API.
        
        Args:
            entity_type: Dynamics entity type (e.g., 'invoices', 'accounts')
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of entity data dictionaries
        """
        # Get authentication token
        token = await self.get_auth_token()
        
        # Build API URL
        entity_url = f"{self.api_url}{entity_type}"
        
        # Build query parameters
        params = {}
        if filters:
            filter_string = self._build_filter_string(filters)
            params["$filter"] = filter_string
        
        if limit:
            params["$top"] = str(limit)
        
        params["$format"] = "json"
        
        # Execute request with retry
        async def _fetch():
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "OData-MaxVersion": "4.0",
                "OData-Version": "4.0"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(entity_url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("value", [])
                    else:
                        error_text = await response.text()
                        raise Exception(f"Dynamics API error: {response.status} - {error_text}")
        
        results = await self.execute_with_retry(_fetch)
        
        logger.info(
            "dynamics_data_fetched",
            entity_type=entity_type,
            record_count=len(results)
        )
        
        return results
    
    async def subscribe_to_events(self, event_types: List[str]) -> bool:
        """
        Subscribe to Dynamics events via Power Automate webhooks.
        
        Args:
            event_types: List of event types to subscribe to
            
        Returns:
            bool: Success status
        """
        # Dynamics 365 uses Power Automate for webhook subscriptions
        webhook_url = self.config.configuration.get("webhook_url")
        if not webhook_url:
            logger.warning("dynamics_webhook_not_configured")
            return False
        
        token = await self.get_auth_token()
        
        # Register webhook for each event type
        for event_type in event_types:
            subscription_url = f"{self.api_url}webhooks"
            
            subscription_data = {
                "name": f"OmniusGrid_{event_type}",
                "webhookUrl": webhook_url,
                "filter": self.config.configuration.get("event_filter", {}),
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
                            raise Exception(f"Dynamics webhook subscription error: {response.status} - {error_text}")
            
            await self.execute_with_retry(_subscribe)
        
        logger.info(
            "dynamics_event_subscriptions_created",
            event_types=event_types
        )
        
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Dynamics connection.
        
        Returns:
            Dict with health status and details
        """
        try:
            # Try to fetch a small amount of data
            if self.api_type == "dataverse":
                results = await self.fetch_data("accounts", limit=1)
            else:
                results = await self.fetch_data("contacts", limit=1)
            
            return {
                "status": "healthy",
                "message": "Dynamics connection successful",
                "environment": self.environment,
                "api_type": self.api_type,
                "checked_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "environment": self.environment,
                "api_type": self.api_type,
                "checked_at": datetime.utcnow().isoformat()
            }
    
    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build Dynamics OData filter string.
        
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
            elif isinstance(value, list):
                # IN clause (not directly supported in OData, use or)
                or_parts = [f"{field} eq '{v}'" if isinstance(v, str) else f"{field} eq {v}" for v in value]
                filter_parts.append(f"({' or '.join(or_parts)})")
        
        return " and ".join(filter_parts)
    
    async def fetch_invoices(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch invoices from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of invoices
        """
        return await self.fetch_data("invoices", filters, limit)
    
    async def fetch_payments(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch payments from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of payments
        """
        return await self.fetch_data("payments", filters, limit)
    
    async def fetch_products(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch products from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of products
        """
        return await self.fetch_data("products", filters, limit)
    
    async def fetch_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch sales orders from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of orders
        """
        return await self.fetch_data("salesorders", filters, limit)
    
    async def fetch_accounts(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch CRM accounts from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of accounts
        """
        return await self.fetch_data("accounts", filters, limit)
    
    async def fetch_contacts(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch CRM contacts from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of contacts
        """
        return await self.fetch_data("contacts", filters, limit)
    
    async def fetch_opportunities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch CRM opportunities from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of opportunities
        """
        return await self.fetch_data("opportunities", filters, limit)
    
    async def fetch_projects(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch projects from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of projects
        """
        return await self.fetch_data("msdyn_project", filters, limit)
    
    async def fetch_tasks(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch project tasks from Dynamics.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of tasks
        """
        return await self.fetch_data("msdyn_projecttask", filters, limit)
