"""
SAP OData Connector

Connector for SAP S/4HANA systems using OData API:
- OData client implementation
- SAP S/4HANA API integration
- Batch request handling
- Delta token support for incremental updates
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
from app.services.erp_connectors.sap_batch import (
    extract_boundary,
    parse_batch_response,
    rows_from_batch,
)

logger = structlog.get_logger()


class SAPConnector(ERPConnectorBase):
    """
    SAP S/4HANA OData connector.
    
    Connects to SAP systems via OData API to fetch
    purchase orders, manufacturing orders, inventory, vendors, and work orders.
    """
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # SAP-specific configuration
        self.service_path = config.configuration.get("service_path", "/sap/opu/odata/sap")
        self.service_name = config.configuration.get("service_name", "API_PURCHASE_ORDER_SRV")
        self.system_id = config.configuration.get("system_id")
        self.client = config.configuration.get("client", "001")
        
        # Build base URL for OData service
        self.odata_url = f"{config.base_url}{self.service_path}/{self.service_name}"
        
        # OAuth2 session for authentication
        
        logger.info(
            "sap_connector_initialized",
            odata_url=self.odata_url,
            system_id=self.system_id,
            client=self.client
        )
    
    async def authenticate(self) -> str:
        """Authenticate with SAP using the client-credentials grant.

        TWO THINGS WERE WRONG HERE. The import of `requests_oauthlib` was never a
        declared dependency, so this module raised ImportError and the SAP
        connector could not be constructed at all. And the flow was
        `fetch_token(..., authorization_response=...)` — the AUTHORIZATION-CODE
        grant, which expects a browser redirect carrying a code. A scheduled
        server-to-server sync has no user and no browser, so it could never have
        completed even with the package installed.

        Server-to-server is client_credentials, and it is now run over aiohttp
        rather than a blocking `requests` session inside an async worker.
        """
        auth_config = self.config.auth_config

        token, expires_in = await fetch_client_credentials_token(
            token_url=auth_config.get("token_url"),
            client_id=auth_config.get("client_id"),
            client_secret=auth_config.get("client_secret"),
            scope=auth_config.get("scope"),
            timeout_seconds=self.config.timeout,
        )

        # Cache against SAP's own stated lifetime.
        self._set_token(token, expires_in)

        logger.info("sap_authentication_success", expires_in=expires_in)
        return token
    
    async def fetch_data(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch data from SAP OData service.
        
        Args:
            entity_type: SAP entity type (e.g., 'PurchaseOrder', 'ProductionOrder')
            filters: Optional OData filters
            limit: Optional limit on number of records
            
        Returns:
            List of entity data dictionaries
        """
        # Get authentication token
        token = await self.get_auth_token()
        
        # Build OData URL
        entity_url = f"{self.odata_url}/{entity_type}"
        
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
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(entity_url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("d", {}).get("results", [])
                    else:
                        error_text = await response.text()
                        raise Exception(f"SAP API error: {response.status} - {error_text}")
        
        results = await self.execute_with_retry(_fetch)
        
        logger.info(
            "sap_data_fetched",
            entity_type=entity_type,
            record_count=len(results)
        )
        
        return results
    
    async def fetch_with_delta(
        self,
        entity_type: str,
        delta_token: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Fetch data with delta token for incremental updates.
        
        Args:
            entity_type: SAP entity type
            delta_token: Previous delta token for incremental fetch
            limit: Optional limit
            
        Returns:
            Dict with results and new delta token
        """
        token = await self.get_auth_token()
        
        entity_url = f"{self.odata_url}/{entity_type}"
        
        params = {
            "$format": "json"
        }
        
        if delta_token:
            params["$deltatoken"] = delta_token
        
        if limit:
            params["$top"] = str(limit)
        
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
                        results = data.get("d", {}).get("results", [])
                        new_delta_token = data.get("d", {}).get("__delta", {}).get("deltatoken")
                        
                        return {
                            "results": results,
                            "delta_token": new_delta_token
                        }
                    else:
                        error_text = await response.text()
                        raise Exception(f"SAP API error: {response.status} - {error_text}")
        
        result = await self.execute_with_retry(_fetch)
        
        logger.info(
            "sap_delta_fetch",
            entity_type=entity_type,
            record_count=len(result["results"]),
            has_delta_token=bool(result["delta_token"])
        )
        
        return result
    
    async def batch_fetch(
        self,
        requests: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Execute batch OData requests.
        
        Args:
            requests: List of request dictionaries with entity_type and optional filters
            
        Returns:
            List of results for each request
        """
        token = await self.get_auth_token()
        
        # Build batch request body
        batch_boundary = "batch_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        batch_body = self._build_batch_body(requests, batch_boundary)
        
        batch_url = f"{self.odata_url}/$batch"
        
        async def _fetch():
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/mixed; boundary={batch_boundary}",
                "Accept": "multipart/mixed"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(batch_url, headers=headers, data=batch_body) as response:
                    if response.status == 202:
                        return await self._parse_batch_response(await response.text(), batch_boundary)
                    else:
                        error_text = await response.text()
                        raise Exception(f"SAP batch error: {response.status} - {error_text}")
        
        results = await self.execute_with_retry(_fetch)
        
        logger.info(
            "sap_batch_fetch",
            request_count=len(requests),
            result_count=len(results)
        )
        
        return results
    
    async def subscribe_to_events(self, event_types: List[str]) -> bool:
        """
        Subscribe to SAP Event Mesh for real-time events.
        
        Args:
            event_types: List of event types to subscribe to
            
        Returns:
            bool: Success status
        """
        # SAP Event Mesh integration
        # This would typically involve registering a webhook endpoint with SAP Event Mesh
        
        event_mesh_url = self.config.configuration.get("event_mesh_url")
        if not event_mesh_url:
            logger.warning("sap_event_mesh_not_configured")
            return False
        
        token = await self.get_auth_token()
        
        # Register subscription for each event type
        for event_type in event_types:
            subscription_url = f"{event_mesh_url}/subscriptions"
            
            subscription_data = {
                "eventType": event_type,
                "webhookUrl": self.config.configuration.get("webhook_url"),
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
                            raise Exception(f"Event Mesh subscription error: {response.status} - {error_text}")
            
            await self.execute_with_retry(_subscribe)
        
        logger.info(
            "sap_event_subscriptions_created",
            event_types=event_types
        )
        
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check that distinguishes a broken connection from a
        missing module. See ERPConnectorBase.probe_health.

        The probe entity 'PurchaseOrder' is business-module dependent, so a tenant
        without it is reported DEGRADED rather than unhealthy — previously any
        exception here mapped to unhealthy, so a working integration on a
        tenant that had not licensed that module looked like an outage.
        """
        return await self.probe_health('PurchaseOrder', details={"system_id": self.system_id, "client": self.client})

    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build OData filter string from filter dictionary.
        
        Args:
            filters: Filter dictionary
            
        Returns:
            str: OData filter string
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
                # IN clause
                value_str = ",".join([f"'{v}'" if isinstance(v, str) else str(v) for v in value])
                filter_parts.append(f"{field} in ({value_str})")
        
        return " and ".join(filter_parts)
    
    def _build_batch_body(self, requests: List[Dict[str, Any]], boundary: str) -> str:
        """
        Build multipart/mixed batch request body.
        
        Args:
            requests: List of request dictionaries
            boundary: Batch boundary string
            
        Returns:
            str: Batch request body
        """
        lines = []
        
        for i, request in enumerate(requests):
            entity_type = request.get("entity_type")
            filters = request.get("filters")
            limit = request.get("limit")
            
            lines.append(f"--{boundary}")
            lines.append("Content-Type: application/http")
            lines.append("Content-Transfer-Encoding: binary")
            lines.append("")
            lines.append(f"GET {self.odata_url}/{entity_type}?$format=json")
            
            if filters:
                filter_string = self._build_filter_string(filters)
                lines.append(f"$filter={filter_string}")
            
            if limit:
                lines.append(f"$top={limit}")
        
        lines.append(f"--{boundary}--")
        
        return "\r\n".join(lines)
    
    async def _parse_batch_response(
        self, response_text: str, boundary: str, content_type: str = ""
    ) -> List[Dict[str, Any]]:
        """Parse a multipart/mixed `$batch` response into rows.

        Delegates to `sap_batch.py`. The previous inline implementation split each
        part on the first blank line and read element [1] as JSON — but that is the
        HTTP status line and headers, not the body, so `json.loads` raised on every
        part and a bare `except` swallowed it. `$batch` returned an empty list while
        reporting success.

        The RESPONSE boundary is used when the server provides one: it is chosen by
        the server and is usually not the boundary that was sent, and parsing with
        the wrong one matches nothing — which looks identical to an empty result.
        """
        effective = extract_boundary(content_type) or boundary
        parts = parse_batch_response(response_text, effective)

        if not parts:
            logger.warning(
                "sap_batch_no_parts_parsed",
                boundary=effective,
                body_length=len(response_text),
            )
            return []

        # strict=False: surface partial failure loudly in the log but still return
        # the rows that did succeed, because a batch is a convenience wrapper over
        # independent reads. `rows_from_batch(strict=True)` is available where a
        # caller needs all-or-nothing.
        rows = rows_from_batch(parts, strict=False)

        logger.info(
            "sap_batch_parsed",
            parts=len(parts),
            failed=sum(1 for p in parts if not p.ok),
            rows=len(rows),
        )
        return rows

    async def fetch_purchase_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch purchase orders from SAP.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of purchase orders
        """
        return await self.fetch_data("A_PurchaseOrder", filters, limit)
    
    async def fetch_manufacturing_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch manufacturing orders from SAP.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of manufacturing orders
        """
        return await self.fetch_data("ProductionOrder", filters, limit)
    
    async def fetch_inventory(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch inventory data from SAP.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of inventory records
        """
        return await self.fetch_data("MaterialStock", filters, limit)
    
    async def fetch_vendors(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch vendor master data from SAP.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of vendors
        """
        return await self.fetch_data("Supplier", filters, limit)
    
    async def fetch_work_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch maintenance work orders from SAP.
        
        Args:
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of work orders
        """
        return await self.fetch_data("MaintenanceOrder", filters, limit)
