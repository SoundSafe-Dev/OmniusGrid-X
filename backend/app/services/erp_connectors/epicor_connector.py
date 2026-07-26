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

from app.services.erp_connectors.oauth2 import fetch_client_credentials_token

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
        """Authenticate with Epicor Kinetic.

        The API-KEY and BASIC paths are legitimate: Epicor Kinetic genuinely
        accepts a long-lived API key (`X-API-Key`) and HTTP Basic credentials, so
        those are static by design and there is nothing to refresh.

        The OAuth2 path was NOT. It read a pre-shared `access_token` out of config
        and returned it, so it worked until the token expired and then every
        request 401'd with no refresh path. That now runs client_credentials.
        """
        auth_config = self.config.auth_config
        auth_type = self.config.auth_type

        if auth_type == AuthType.OAUTH2:
            token, expires_in = await fetch_client_credentials_token(
                token_url=auth_config.get("token_url"),
                client_id=auth_config.get("client_id"),
                client_secret=auth_config.get("client_secret"),
                scope=auth_config.get("scope"),
                timeout_seconds=self.config.timeout,
            )
            self._set_token(token, expires_in)
            logger.info(
                "epicor_authentication_success",
                auth_type=auth_type.value,
                expires_in=expires_in,
            )
            return token

        # Static credential: API key or Basic. Nothing expires, so no lifetime.
        credential = auth_config.get("api_key") or auth_config.get("password")
        if not credential:
            raise ValueError(
                "Epicor needs `api_key` (or Basic `username`/`password`) in "
                "auth_config, or OAuth2 client_id/client_secret/token_url."
            )
        logger.info("epicor_authentication_success", auth_type=auth_type.value)
        return credential

    def _auth_headers(self, token: str) -> Dict[str, str]:
        """Headers for one Epicor request.

        TWO FIXES HERE. `X-API-Key` was being set to `self.company_id` — the
        COMPANY IDENTIFIER, not a credential. Epicor uses that header for the API
        key; the company is scoping metadata and belongs in CallSettings.

        And a static API key was being sent as `Authorization: Bearer <key>`.
        Epicor expects the key in `X-API-Key` and Basic credentials in
        `Authorization: Basic`; a bearer header carrying an API key is rejected.
        """
        import base64
        import json as _json

        auth_config = self.config.auth_config
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self.config.auth_type == AuthType.OAUTH2:
            headers["Authorization"] = f"Bearer {token}"
        elif auth_config.get("username"):
            raw = f"{auth_config['username']}:{auth_config.get('password', '')}".encode()
            headers["Authorization"] = f"Basic {base64.b64encode(raw).decode()}"
        else:
            headers["X-API-Key"] = token

        # Company/site scoping travels in CallSettings, which is where Epicor
        # looks for it — not in the API-key header.
        call_settings = {}
        if self.company_id:
            call_settings["Company"] = self.company_id
        if self.site_id:
            call_settings["Plant"] = self.site_id
        if call_settings:
            headers["CallSettings"] = _json.dumps(call_settings)

        return headers
    
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
            headers = self._auth_headers(token)
            
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
                headers = self._auth_headers(token)
                
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
        """Health check that distinguishes a broken connection from a
        missing module. See ERPConnectorBase.probe_health.

        The probe entity 'Erp.BO.InvoiceSvc' is business-module dependent, so a tenant
        without it is reported DEGRADED rather than unhealthy — previously any
        exception here mapped to unhealthy, so a working integration on a
        tenant that had not licensed that module looked like an outage.
        """
        return await self.probe_health('Erp.BO.InvoiceSvc', details={"company_id": self.company_id})

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
