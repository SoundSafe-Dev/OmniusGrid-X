"""
Infor Connector

Connector for Infor using ION API:
- ION API integration
- OAuth2 authentication
- REST API for data access
"""

from typing import Dict, Any, Optional, List
import structlog
import aiohttp

from app.services.erp_connector_base import (
    ERPConnectorBase,
    ERPConfig,
)

logger = structlog.get_logger()


class InforConnector(ERPConnectorBase):
    """
    Infor connector.
    
    Connects to Infor via ION API to fetch
    financial data, supply chain data, and HR data.
    """

    #: Infor ION event subscriptions are configured in ION Desk / the ION API
    #: portal, not created by POSTing to `{api_url}/webhooks`.
    EVENT_SUBSCRIPTION_MECHANISM = (
        "Infor ION event subscriptions are configured in ION Desk / the ION API "
        "portal, not through the data API. Poll with fetch_data meanwhile."
    )
    
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
    
    def _http_session(self) -> aiohttp.ClientSession:
        """One session factory, so timeouts are configured in a single place."""
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout)
        )

    def _token_endpoint(self) -> str:
        """ION's OAuth2 token URL.

        Infor issues a `.ionapi` credentials document per service account; its `pu`
        (portal URL) and `ot` (OAuth token path) fields compose the token endpoint.
        `token_url` may be supplied directly for deployments that do not hand the
        raw document to the integration.
        """
        auth = self.config.auth_config
        explicit = auth.get("token_url")
        if explicit:
            return explicit

        portal = (auth.get("pu") or auth.get("portal_url") or "").rstrip("/")
        token_path = (auth.get("ot") or auth.get("oauth_token_path") or "").lstrip("/")
        if portal and token_path:
            return f"{portal}/{token_path}"

        raise ValueError(
            "Infor ION OAuth2 needs a token endpoint: supply `token_url`, or the "
            "`pu` and `ot` fields from the service account's .ionapi document."
        )

    async def authenticate(self) -> str:
        """Obtain an ION access token via OAuth2.

        WHAT THIS REPLACES. The previous implementation read a static
        `access_token` out of config and returned it, under a comment saying "In
        production, this would use OAuth2 flow". ION tokens are short-lived, so a
        pre-shared one works until it expires and then every request 401s with no
        refresh path and nothing pointing at the cause.

        Supports both grants ION issues for service accounts:
          * `password` — the .ionapi document's `saak`/`sask` service-account keys,
            which is what ION generates by default;
          * `client_credentials` — where the tenant has been configured for it.
        """
        auth = self.config.auth_config

        client_id = auth.get("ci") or auth.get("client_id")
        client_secret = auth.get("cs") or auth.get("client_secret")
        if not (client_id and client_secret):
            raise ValueError(
                "Infor ION OAuth2 needs client credentials: `ci`/`cs` from the "
                ".ionapi document, or client_id/client_secret. A pre-shared "
                "`access_token` is not supported — it cannot be refreshed, so it "
                "fails silently once it expires."
            )

        saak = auth.get("saak") or auth.get("service_account_key")
        sask = auth.get("sask") or auth.get("service_account_secret")

        form = {"client_id": client_id, "client_secret": client_secret}
        if saak and sask:
            # ION's default service-account grant.
            form.update({"grant_type": "password", "username": saak, "password": sask})
            grant = "password"
        else:
            form["grant_type"] = "client_credentials"
            grant = "client_credentials"
        if auth.get("scope"):
            form["scope"] = auth["scope"]

        token_url = self._token_endpoint()

        async def _token():
            async with self._http_session() as session:
                async with session.post(
                    token_url,
                    data=form,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ) as response:
                    body = await response.text()
                    if response.status != 200:
                        raise Exception(
                            f"Infor ION token request failed: {response.status} - {body}"
                        )
                    import json as _json
                    return _json.loads(body)

        payload = await self.execute_with_retry(_token)

        token = payload.get("access_token")
        if not token:
            raise ValueError(
                f"Infor ION token response has no access_token: {sorted(payload)}"
            )

        # Cache against ION's OWN lifetime rather than the base class's old
        # hardcoded hour.
        expires_in = payload.get("expires_in")
        try:
            expires_in = float(expires_in) if expires_in is not None else None
        except (TypeError, ValueError):
            expires_in = None
        self._set_token(token, expires_in)

        logger.info(
            "infor_authentication_success",
            grant_type=grant,
            expires_in=expires_in,
        )
        return token
    
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
    

    async def health_check(self) -> Dict[str, Any]:
        """Health check that distinguishes a broken connection from a
        missing module. See ERPConnectorBase.probe_health.

        The probe entity 'invoice' is business-module dependent, so a tenant
        without it is reported DEGRADED rather than unhealthy — previously any
        exception here mapped to unhealthy, so a working integration on a
        tenant that had not licensed that module looked like an outage.
        """
        return await self.probe_health('invoice', details={"tenant_id": self.tenant_id})

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
