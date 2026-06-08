"""
Oracle Cloud ERP Connector

Connector for Oracle Cloud ERP using REST API:
- Oracle Fusion Cloud API integration
- OAuth2 authentication with Oracle
- Bulk data import support
- Scheduled job management
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog
import aiohttp
from requests_oauthlib import OAuth2Session

from app.services.erp_connector_base import (
    ERPConnectorBase,
    ERPConfig,
    ERPType,
    AuthType
)

logger = structlog.get_logger()


class OracleConnector(ERPConnectorBase):
    """
    Oracle Cloud ERP connector.
    
    Connects to Oracle Fusion Cloud ERP via REST API to fetch
    financial data, supply chain data, HR data, and project data.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # Oracle-specific configuration
        self.instance_name = config.configuration.get("instance_name")
        self.api_version = config.configuration.get("api_version", "v11")
        
        # Build base URL for Oracle Fusion Cloud API
        self.api_url = f"{config.base_url}/fscmRestApi/resources/{self.api_version}"
        
        # OAuth2 session for authentication
        self.oauth_session: Optional[OAuth2Session] = None
        
        logger.info(
            "oracle_connector_initialized",
            api_url=self.api_url,
            instance_name=self.instance_name
        )
    
    async def authenticate(self) -> str:
        """
        Authenticate with Oracle using OAuth2.
        
        Returns:
            str: Access token
        """
        auth_config = self.config.auth_config
        
        # Create OAuth2 session
        self.oauth_session = OAuth2Session(
            client_id=auth_config.get("client_id"),
            redirect_uri=auth_config.get("redirect_uri", "urn:ietf:wg:oauth:2.0:oob")
        )
        
        # Fetch token
        token = self.oauth_session.fetch_token(
            token_url=auth_config.get("token_url"),
            client_secret=auth_config.get("client_secret"),
            authorization_response=auth_config.get("authorization_response")
        )
        
        access_token = token.get("access_token")
        
        logger.info(
            "oracle_authentication_success",
            token_type=token.get("token_type")
        )
        
        return access_token
    
    async def fetch_data(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch data from Oracle Fusion Cloud API.
        
        Args:
            entity_type: Oracle entity type (e.g., 'invoices', 'shipments')
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
                        raise Exception(f"Oracle API error: {response.status} - {error_text}")
        
        results = await self.execute_with_retry(_fetch)
        
        logger.info(
            "oracle_data_fetched",
            entity_type=entity_type,
            record_count=len(results)
        )
        
        return results
    
    async def bulk_import(
        self,
        entity_type: str,
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Bulk import data to Oracle.
        
        Args:
            entity_type: Entity type
            data: List of data to import
            
        Returns:
            Dict with import results
        """
        token = await self.get_auth_token()
        
        entity_url = f"{self.api_url}/{entity_type}"
        
        async def _import():
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/vnd.oracle.adf.resourceitem+json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    entity_url,
                    headers=headers,
                    json={"items": data}
                ) as response:
                    if response.status in [200, 201]:
                        result = await response.json()
                        return {
                            "status": "success",
                            "imported_count": len(data),
                            "result": result
                        }
                    else:
                        error_text = await response.text()
                        raise Exception(f"Oracle bulk import error: {response.status} - {error_text}")
        
        result = await self.execute_with_retry(_import)
        
        logger.info(
            "oracle_bulk_import_completed",
            entity_type=entity_type,
            imported_count=result.get("imported_count")
        )
        
        return result
    
    async def subscribe_to_events(self, event_types: List[str]) -> bool:
        """
        Subscribe to Oracle events for real-time updates.
        
        Args:
            event_types: List of event types to subscribe to
            
        Returns:
            bool: Success status
        """
        # Oracle event subscription via webhook registration
        webhook_url = self.config.configuration.get("webhook_url")
        if not webhook_url:
            logger.warning("oracle_webhook_not_configured")
            return False
        
        token = await self.get_auth_token()
        
        # Register webhook for each event type
        for event_type in event_types:
            subscription_url = f"{self.api_url}/eventSubscriptions"
            
            subscription_data = {
                "eventType": event_type,
                "webhookUrl": webhook_url,
                "filter": self.config.configuration.get("event_filter", {})
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
                            raise Exception(f"Oracle event subscription error: {response.status} - {error_text}")
            
            await self.execute_with_retry(_subscribe)
        
        logger.info(
            "oracle_event_subscriptions_created",
            event_types=event_types
        )
        
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Oracle connection.
        
        Returns:
            Dict with health status and details
        """
        try:
            # Try to fetch a small amount of data
            results = await self.fetch_data("invoices", limit=1)
            
            return {
                "status": "healthy",
                "message": "Oracle connection successful",
                "instance_name": self.instance_name,
                "checked_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "instance_name": self.instance_name,
                "checked_at": datetime.utcnow().isoformat()
            }
    
    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build Oracle REST API filter string.
        
        Args:
            filters: Filter dictionary
            
        Returns:
            str: Filter string
        """
        filter_parts = []
        
        for field, value in filters.items():
            if isinstance(value, str):
                filter_parts.append(f"{field}='{value}'")
            elif isinstance(value, int) or isinstance(value, float):
                filter_parts.append(f"{field}={value}")
            elif isinstance(value, bool):
                filter_parts.append(f"{field}={str(value).lower()}")
            elif isinstance(value, list):
                # IN clause
                value_str = ",".join([f"'{v}'" if isinstance(v, str) else str(v) for v in value])
                filter_parts.append(f"{field} in ({value_str})")
        
        return " and ".join(filter_parts)
    
    async def fetch_invoices(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch invoices from Oracle.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of invoices
        """
        return await self.fetch_data("invoices", filters, limit)
    
    async def fetch_shipments(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch shipments from Oracle.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of shipments
        """
        return await self.fetch_data("shipments", filters, limit)
    
    async def fetch_employees(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch employee data from Oracle.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of employees
        """
        return await self.fetch_data("workers", filters, limit)
    
    async def fetch_projects(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch project data from Oracle.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of projects
        """
        return await self.fetch_data("projects", filters, limit)
