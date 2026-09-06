"""
Oracle Cloud ERP Connector

Connector for Oracle Cloud ERP using REST API:
- Oracle Fusion Cloud API integration
- OAuth2 authentication with Oracle
- Bulk data import support
- Scheduled job management
"""

from typing import Dict, Any, Optional, List
import structlog
import aiohttp

from app.services.erp_connector_base import (
    ERPConnectorBase,
    ERPConfig,
)

from app.services.erp_connectors.oauth2 import fetch_client_credentials_token

logger = structlog.get_logger()


class OracleConnector(ERPConnectorBase):
    """
    Oracle Cloud ERP connector.
    
    Connects to Oracle Fusion Cloud ERP via REST API to fetch
    financial data, supply chain data, HR data, and project data.
    """

    #: Oracle Fusion has no generic `/eventSubscriptions` endpoint. Real-time
    #: integration uses Business Events and REST Atom feeds.
    EVENT_SUBSCRIPTION_MECHANISM = (
        "Oracle Fusion exposes no generic /eventSubscriptions endpoint. Use Business "
        "Events (Integration Cloud) or the REST Atom feeds, or poll with fetch_data."
    )
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # Oracle-specific configuration
        self.instance_name = config.configuration.get("instance_name")
        self.api_version = config.configuration.get("api_version", "v11")
        
        # Build base URL for Oracle Fusion Cloud API
        self.api_url = f"{config.base_url}/fscmRestApi/resources/{self.api_version}"
        
        # OAuth2 session for authentication
        
        logger.info(
            "oracle_connector_initialized",
            api_url=self.api_url,
            instance_name=self.instance_name
        )
    

    def _session(self) -> aiohttp.ClientSession:
        """One session factory, so timeouts are set in exactly one place (FS-1008).

        Bare `aiohttp.ClientSession()` has no total timeout: a host that accepts the
        connection and then stops responding hangs the coroutine forever, holding a pool
        slot and never reaching the retry classifier or the circuit breaker.
        """
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout)
        )

    async def authenticate(self) -> str:
        """Authenticate with Oracle Fusion using the client-credentials grant.

        Same two defects as the SAP connector: `requests_oauthlib` was never a
        declared dependency (so this module raised ImportError and the connector
        could not be constructed), and the flow was authorization-code, which
        expects a browser redirect that a scheduled sync does not have.

        Oracle Fusion tenants vary in whether they expect `scope` or `resource`;
        both are passed through when configured.
        """
        auth_config = self.config.auth_config

        token, expires_in = await fetch_client_credentials_token(
            token_url=auth_config.get("token_url"),
            client_id=auth_config.get("client_id"),
            client_secret=auth_config.get("client_secret"),
            scope=auth_config.get("scope"),
            resource=auth_config.get("resource"),
            timeout_seconds=self.config.timeout,
        )

        self._set_token(token, expires_in)

        logger.info("oracle_authentication_success", expires_in=expires_in)
        return token

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
            
            async with self._session() as session:
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
            
            async with self._session() as session:
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
    

    async def health_check(self) -> Dict[str, Any]:
        """Health check that distinguishes a broken connection from a
        missing module. See ERPConnectorBase.probe_health.

        The probe entity 'invoices' is business-module dependent, so a tenant
        without it is reported DEGRADED rather than unhealthy — previously any
        exception here mapped to unhealthy, so a working integration on a
        tenant that had not licensed that module looked like an outage.
        """
        return await self.probe_health('invoices', details={})

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
