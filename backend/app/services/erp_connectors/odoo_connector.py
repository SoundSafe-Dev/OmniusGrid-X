"""
Odoo Connector

Connector for Odoo using XML-RPC or REST API:
- XML-RPC API integration
- REST API integration
- OAuth2 or API key authentication
"""

from typing import Dict, Any, Optional, List
import asyncio
import structlog
import aiohttp

from app.services.erp_connector_base import (
    ERPConnectorBase,
    ERPConfig,
    AuthType
)

from app.services.erp_connectors.oauth2 import fetch_client_credentials_token
from app.middleware.request_context import outbound_correlation_headers

logger = structlog.get_logger()


class OdooConnector(ERPConnectorBase):
    """
    Odoo connector.
    
    Connects to Odoo via XML-RPC or REST API to fetch
    sales data, inventory data, and accounting data.
    """

    #: VERIFIED against a live Odoo 17: `POST /webhooks` is 404, and the URL this
    #: connector used (`/xmlrpc/2/webhooks`) returns HTTP 200 with an XML-RPC fault
    #: body -- which is exactly why the old implementation reported success.
    #: Odoo core has no webhook REST endpoint. Odoo 17 sends outgoing webhooks from
    #: `base.automation` automated-action records, which are created through the ORM
    #: (execute_kw on `base.automation`), not through a REST call.
    EVENT_SUBSCRIPTION_MECHANISM = (
        "Odoo has no webhook REST endpoint (verified: /webhooks 404s and "
        "/xmlrpc/2/webhooks returns HTTP 200 with an XML-RPC fault). Create a "
        "base.automation automated action with an outgoing-webhook action via the "
        "ORM, or poll with fetch_data."
    )
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # Odoo-specific configuration
        self.db_name = config.configuration.get("db_name")
        self.api_type = config.configuration.get("api_type", "rest")  # rest or xmlrpc
        # XML-RPC IS ON A CLOCK (FS-1003). Odoo deprecated `/xmlrpc`, `/xmlrpc/2` and
        # `/jsonrpc` in v19 (Oct 2025) in favour of a bearer-token JSON-2 API, with
        # removal targeted for Odoo Online around 19.1/21.1 and later for on-premise.
        #
        # It is not migrated here because `api_type` defaults to "rest": an operator only
        # reaches the deprecating path by explicitly selecting it, and rewriting a
        # protocol this repository cannot exercise against a live Odoo would be a guess
        # shipped as a fix. What is resolvable is that the choice stops being silent.
        
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
        if self.api_type != "rest":
            logger.warning(
                "odoo_connector_using_deprecated_xmlrpc",
                api_type=self.api_type,
                detail=(
                    "Odoo deprecated XML-RPC/JSON-RPC in v19 in favour of a "
                    "bearer-token JSON-2 API, with removal targeted for Odoo Online "
                    "around 19.1/21.1. `api_type: rest` is the default and is not "
                    "affected; this instance has explicitly selected the older protocol."
                ),
            )
    

    def _session(self) -> aiohttp.ClientSession:
        """One session factory, so timeouts are set in exactly one place (FS-1008).

        Bare `aiohttp.ClientSession()` has no total timeout: a host that accepts the
        connection and then stops responding hangs the coroutine forever, holding a pool
        slot and never reaching the retry classifier or the circuit breaker.
        """
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            # FS-1014. Carries this request's correlation id outbound, so a failing ERP
            # call and the request that caused it can be joined. Empty outside a request
            # (a scheduled sync), because a freshly minted id would look like correlation
            # and correlate nothing.
            headers=outbound_correlation_headers(),
        )

    async def authenticate(self) -> str:
        """Authenticate with Odoo.

        The API-KEY path is legitimate — Odoo API keys are long-lived and are used
        as the password in its standard RPC auth, so there is nothing to refresh.
        The OAuth2 path was not: it read a pre-shared `access_token` from config,
        which works until it expires and then 401s forever with no refresh.
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
                "odoo_authentication_success",
                auth_type=auth_type.value,
                expires_in=expires_in,
            )
            return token

        credential = auth_config.get("api_key") or auth_config.get("password")
        if not credential:
            raise ValueError(
                "Odoo needs `api_key` (or `password`) in auth_config, or OAuth2 "
                "client_id/client_secret/token_url."
            )
        logger.info("odoo_authentication_success", auth_type=auth_type.value)
        return credential

    async def _jsonrpc(self, service: str, method: str, args: list) -> Any:
        """Call Odoo's JSON-RPC endpoint.

        WHY THIS EXISTS. `api_type` accepted "xmlrpc", set `api_url` to
        `{base}/xmlrpc/2`, and then `fetch_data` issued an HTTP GET with an
        `Authorization: Bearer` header regardless — REST semantics against an RPC
        endpoint. XML-RPC requires a POST with an XML body and has no bearer
        concept, so that mode could never have returned data.

        JSON-RPC is used rather than XML-RPC: same endpoints and semantics, but a
        JSON body, so it needs no XML dependency and is far easier to verify.
        Odoo exposes it at `/jsonrpc` on every standard deployment.
        """
        import json as _json

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": 1,
        }
        url = f"{self.config.base_url.rstrip('/')}/jsonrpc"

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout)
        ) as session:
            async with session.post(
                url, json=payload, headers={"Content-Type": "application/json"}
            ) as response:
                body = await response.text()
                if response.status != 200:
                    raise Exception(f"Odoo JSON-RPC error: {response.status} - {body}")
                data = _json.loads(body)

        # JSON-RPC reports application errors in the BODY with HTTP 200. Treating
        # 200 as success is how an Odoo access-rights failure becomes an empty
        # result set instead of an error.
        if "error" in data:
            err = data["error"]
            message = err.get("data", {}).get("message") or err.get("message")
            raise Exception(f"Odoo JSON-RPC fault: {message}")

        return data.get("result")

    async def _rpc_uid(self) -> int:
        """Resolve the Odoo user id, authenticating once per connector.

        SERIALISED, for the same reason `get_auth_token` is. The unguarded
        check-then-fill below is a classic cache stampede: every concurrent caller
        arriving before the first one finishes misses the cache and issues its own
        `common.authenticate`. Measured against a real Odoo 17: 15 concurrent
        fetches produced 15 authentication RPCs.

        The base class lock does not cover this, because Odoo's uid is a
        SECOND credential resolved after `get_auth_token()` returns — for the
        API-key path that returns immediately from config, so the base lock is
        never contended and every caller sails through to here.
        """
        if getattr(self, "_odoo_uid", None):
            return self._odoo_uid

        if getattr(self, "_uid_lock", None) is None:
            self._uid_lock = asyncio.Lock()

        async with self._uid_lock:
            # Double-check: the winner may have filled it while we waited.
            if getattr(self, "_odoo_uid", None):
                return self._odoo_uid
            return await self._resolve_uid()

    async def _resolve_uid(self) -> int:
        credential = await self.get_auth_token()
        login = self.config.auth_config.get("username") or self.config.auth_config.get("login")
        if not (self.db_name and login):
            raise ValueError(
                "Odoo RPC needs `db_name` in configuration and `username` in "
                "auth_config alongside the API key."
            )
        uid = await self._jsonrpc("common", "authenticate", [self.db_name, login, credential, {}])
        if not uid:
            raise Exception("Odoo authentication returned no uid — check db, login and API key")
        self._odoo_uid = uid
        return uid
    
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
        # RPC is Odoo's standard integration surface. The `/api` REST path only
        # exists if a third-party module provides it, so REST stays opt-in and RPC
        # is what a stock Odoo deployment actually answers.
        if self.api_type != "rest":
            return await self._fetch_via_rpc(entity_type, filters, limit)

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
            
            async with self._session() as session:
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
    
    async def _fetch_via_rpc(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Read a model via `execute_kw` + `search_read`, paginating.

        `entity_type` is an Odoo model name (`sale.order`, `stock.picking`).
        Odoo caps a single read, so results are paged rather than assuming one
        call returns everything — the same silent-truncation trap NetSuite had.
        """
        uid = await self._rpc_uid()
        credential = await self.get_auth_token()

        domain = self._build_rpc_domain(filters)
        page_size = int(self.config.configuration.get("page_size", 200))

        rows: List[Dict[str, Any]] = []
        offset = 0
        while True:
            remaining = None if limit is None else limit - len(rows)
            if remaining is not None and remaining <= 0:
                break
            batch = page_size if remaining is None else min(page_size, remaining)

            page = await self._jsonrpc(
                "object",
                "execute_kw",
                [
                    self.db_name,
                    uid,
                    credential,
                    entity_type,
                    "search_read",
                    [domain],
                    {"limit": batch, "offset": offset},
                ],
            ) or []

            rows.extend(page)
            if len(page) < batch:
                break
            offset += len(page)

        logger.info(
            "odoo_data_fetched",
            entity_type=entity_type,
            record_count=len(rows),
            transport="jsonrpc",
        )
        return rows

    def _build_rpc_domain(self, filters: Optional[Dict[str, Any]]) -> list:
        """Translate a flat filter dict into an Odoo domain.

        Odoo domains are lists of (field, operator, value) triples, not the
        querystring the REST path builds — passing the REST filter string to RPC
        would raise a server-side fault.
        """
        if not filters:
            return []
        return [(field, "=", value) for field, value in filters.items()]


    async def verify_credentials(self) -> None:
        """Round-trip the credential against Odoo.

        The base default calls `get_auth_token()`, which for the API-key path just
        returns the value out of config — a wrong key would pass. `_rpc_uid()`
        actually calls `common.authenticate`, so a bad key fails here where it
        belongs rather than being misreported as a missing module.
        """
        await self._rpc_uid()

    async def health_check(self) -> Dict[str, Any]:
        """Health check via the shared three-state probe.

        `res.users` exists in every Odoo database, so a failure here really is a
        connection or credential fault rather than a missing module. This used to
        probe `sale.order`, which only exists with the Sales module installed —
        found by running against a real Odoo, and the reason
        ERPConnectorBase.probe_health now separates degraded from unhealthy for
        every connector.
        """
        return await self.probe_health("res.users", details={"db_name": self.db_name})

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
