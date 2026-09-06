"""NetSuite connector — SuiteTalk REST.

WHAT WAS WRONG BEFORE. Three defects, any one of which made this connector
non-functional against a real NetSuite account:

1. **The API host did not exist.** It built
   `https://{account}.suitetalk.net/rest/services`. NetSuite's REST service lives
   at `https://{account}.suitetalk.api.netsuite.com/services/rest`, with the
   account id lowercased and underscores turned into hyphens. No request from this
   connector could ever have reached NetSuite.
2. **There was no authentication.** `authenticate()` read a static `access_token`
   out of config and sent `Authorization: Bearer <token>`. NetSuite's standard
   server-to-server mechanism is Token-Based Auth — OAuth 1.0a, HMAC-SHA256, with
   every request individually signed over its own method, URL and query string.
   A bearer header is rejected.
3. **Pagination was ignored.** `fetch_data` read `data["items"]` once and returned
   it. NetSuite pages results and reports `hasMore`/`offset`; anything past the
   first page was silently dropped, so a large query returned a plausible-looking
   truncated answer with no error.

Signing lives in `netsuite_auth.py` so it can be tested as a pure function.
"""

from typing import Any, Dict, List, Optional
import structlog
import aiohttp

from app.services.erp_connector_base import (
    ERPConnectorBase,
    ERPConfig,
)
from app.services.erp_connectors.netsuite_auth import (
    build_tba_header,
    oauth2_token_url,
    parse_oauth2_token_response,
    rest_base_url,
)

logger = structlog.get_logger()


class NetSuiteConnector(ERPConnectorBase):
    """
    NetSuite connector.
    
    Connects to NetSuite via SuiteTalk REST API to fetch
    financial data, inventory data, and CRM data.
    """

    #: NetSuite has no outbound-webhook REST API; the old implementation POSTed to
    #: `/rest/webhooks/v1`, which does not exist. Outbound notifications come from
    #: SuiteScript.
    EVENT_SUBSCRIPTION_MECHANISM = (
        "NetSuite exposes no webhook REST API. Use a SuiteScript user-event or "
        "scheduled script that calls out with N/https, or poll with fetch_data."
    )
    
    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)
        
        # NetSuite-specific configuration
        self.account_id = config.configuration.get("account_id")
        # `realm` defaults to the account id: NetSuite requires the OAuth realm to
        # match the account the credentials belong to, and rejects a mismatch with
        # an error that does not mention the realm.
        self.realm = config.configuration.get("realm") or self.account_id

        # Correct SuiteTalk REST base (see the module docstring for the old one).
        self.api_url = rest_base_url(self.account_id) if self.account_id else None

        # NetSuite pages results; this is the per-request page size. 1000 is the
        # service maximum — a smaller value only means more round trips.
        self.page_size = int(config.configuration.get("page_size", 1000))
        
        logger.info(
            "netsuite_connector_initialized",
            api_url=self.api_url,
            account_id=self.account_id,
            realm=self.realm,
            auth_mechanism="tba_oauth1" if self._uses_tba() else "oauth2",
        )
        # SAY IT ONCE, AT STARTUP, WHERE SOMEBODY CAN ACT ON IT (FS-994). NetSuite's
        # TBA retirement has real dates -- 2027.1 stops new TBA integrations being
        # created, 2028.2 retires SOAP -- and the failure mode for a deadline nobody
        # is reminded of is discovering it from a broken integration rather than from
        # a plan. This is a warning rather than a refusal on purpose: TBA works today,
        # and breaking a working ERP sync over a future date would be the worse bug.
        if self._uses_tba():
            logger.warning(
                "netsuite_using_deprecated_tba_auth",
                account_id=self.account_id,
                detail=(
                    "NetSuite Token-Based Auth (OAuth 1.0a) is on a retirement path: "
                    "2026.1 expects new integrations on REST + OAuth 2.0, 2027.1 blocks "
                    "creating new TBA-authenticated integrations. Add client_id and "
                    "client_secret to auth_config to migrate -- this connector already "
                    "supports OAuth 2.0 client credentials and will prefer them."
                ),
            )
    
    def _uses_tba(self) -> bool:
        """TBA only when OAuth 2.0 is NOT configured (FS-994).

        TBA (Token-Based Auth — OAuth 1.0a) is still NetSuite's most common
        server-to-server mechanism and needs no token endpoint, which is why it used
        to be preferred whenever its four credentials existed. **That preference was a
        migration trap.** NetSuite is retiring TBA: from 2026.1 new integrations are
        expected on REST + OAuth 2.0, 2027.1 blocks creating new SOAP- or
        TBA-authenticated integrations, and 2028.2 retires SOAP entirely. An account
        migrating to OAuth 2.0 would add `client_id`/`client_secret`, redeploy, and
        stay silently on TBA for as long as the old credentials were still sitting in
        config — which is exactly how a migration gets declared done while nothing
        moved.

        OAuth 2.0 now wins when it is explicitly configured. TBA still works, still
        needs no code change to keep using, and is still the fallback — but choosing
        it is now something config does deliberately rather than by leftover.
        """
        auth = self.config.auth_config
        if auth.get("client_id") and auth.get("client_secret"):
            return False
        return all(
            auth.get(k)
            for k in ("consumer_key", "consumer_secret", "token_id", "token_secret")
        )

    def _tba_header(self, method: str, url: str) -> str:
        """Sign one request. TBA signs per-request, so this cannot be cached."""
        auth = self.config.auth_config
        return build_tba_header(
            method=method,
            url=url,
            account_id=self.realm,
            consumer_key=auth["consumer_key"],
            consumer_secret=auth["consumer_secret"],
            token_id=auth["token_id"],
            token_secret=auth["token_secret"],
        )

    async def authenticate(self) -> str:
        """Obtain an OAuth 2.0 access token.

        Only called on the OAuth2 path. Under TBA there is nothing to authenticate
        *once* — each request carries its own signature — so `_request_headers`
        signs instead and this is never reached.
        """
        auth_config = self.config.auth_config

        if self._uses_tba():
            # Explicit rather than returning a fake token: a caller that reaches
            # here under TBA has a bug, and silently handing back a placeholder
            # would produce a 401 far from the cause.
            raise RuntimeError(
                "NetSuite is configured for TBA (OAuth 1.0a); requests are signed "
                "individually and there is no token to fetch. This is a call-path "
                "bug — use _request_headers()."
            )

        client_id = auth_config.get("client_id")
        client_secret = auth_config.get("client_secret")
        if not (client_id and client_secret):
            raise ValueError(
                "NetSuite OAuth2 needs client_id and client_secret in auth_config, "
                "or the four TBA credentials (consumer_key, consumer_secret, "
                "token_id, token_secret). A pre-shared `access_token` is not a "
                "supported configuration: it cannot be refreshed, so it fails "
                "silently the moment it expires."
            )

        token_url = oauth2_token_url(self.account_id)
        form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if auth_config.get("scope"):
            form["scope"] = auth_config["scope"]

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
                            f"NetSuite OAuth2 token request failed: "
                            f"{response.status} - {body}"
                        )
                    import json as _json
                    return _json.loads(body)

        payload = await self.execute_with_retry(_token)
        token, expires_in = parse_oauth2_token_response(payload)

        # Cache against the provider's OWN lifetime. The base class used to assume
        # one hour for every provider, so a shorter-lived token was served from
        # cache long after it died.
        self._set_token(token, expires_in)

        logger.info(
            "netsuite_authentication_success",
            auth_type="oauth2_client_credentials",
            expires_in=expires_in,
        )
        return token

    def _http_session(self) -> aiohttp.ClientSession:
        """One session factory, so timeouts are set in exactly one place."""
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout)
        )

    async def _request_headers(self, method: str, url: str) -> Dict[str, str]:
        """Auth headers for one request — signed under TBA, bearer under OAuth2."""
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._uses_tba():
            headers["Authorization"] = self._tba_header(method, url)
        else:
            headers["Authorization"] = f"Bearer {await self.get_auth_token()}"
        return headers
    
    async def fetch_data(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch data from NetSuite SuiteTalk API.
        
        Args:
            entity_type: NetSuite entity type (e.g., 'invoice', 'salesOrder')
            filters: Optional filters
            limit: Optional limit
            
        Returns:
            List of entity data dictionaries
        """
        from urllib.parse import urlencode

        entity_url = f"{self.api_url}/record/v1/{entity_type}"

        base_params: Dict[str, str] = {}
        if filters:
            base_params["q"] = self._build_filter_string(filters)

        results: List[Dict[str, Any]] = []
        offset = 0

        # PAGINATE. The previous implementation read `items` from the first
        # response and returned it, so any result set larger than NetSuite's page
        # size came back silently truncated — a plausible answer that is simply
        # missing rows, with no error to notice.
        while True:
            remaining = None if limit is None else limit - len(results)
            if remaining is not None and remaining <= 0:
                break

            page_limit = self.page_size if remaining is None else min(self.page_size, remaining)
            params = {**base_params, "limit": str(page_limit), "offset": str(offset)}

            # The signature must cover the query string, so build the full URL
            # first and sign THAT — signing the bare path produces a valid-looking
            # header that NetSuite rejects only on filtered/paginated requests.
            page_url = f"{entity_url}?{urlencode(params)}"

            async def _fetch(url=page_url):
                headers = await self._request_headers("GET", url)
                async with self._http_session() as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 401:
                            # The token is dead regardless of its stated expiry;
                            # drop it so the retry re-authenticates instead of
                            # replaying the same bad credential.
                            self.invalidate_token()
                        if response.status != 200:
                            error_text = await response.text()
                            raise Exception(
                                f"NetSuite API error: {response.status} - {error_text}"
                            )
                        return await response.json()

            data = await self.execute_with_retry(_fetch)
            items = data.get("items", []) or []
            results.extend(items)

            has_more = bool(data.get("hasMore"))
            if not has_more or not items:
                break
            # Trust our own count rather than an echoed offset: NetSuite omits
            # `offset` from some responses, and a missing key would restart at 0
            # and loop forever.
            offset += len(items)

        if limit is not None:
            results = results[:limit]

        logger.info(
            "netsuite_data_fetched",
            entity_type=entity_type,
            record_count=len(results),
            pages=(offset // self.page_size) + 1 if offset else 1,
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
        return await self.probe_health('invoice', details={"account_id": self.account_id})

    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build NetSuite SuiteTalk filter string.
        
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
        """Fetch invoices from NetSuite."""
        return await self.fetch_data("invoice", filters, limit)
    
    async def fetch_sales_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch sales orders from NetSuite."""
        return await self.fetch_data("salesOrder", filters, limit)
    
    async def fetch_inventory(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch inventory from NetSuite."""
        return await self.fetch_data("inventoryItem", filters, limit)
    
    async def fetch_customers(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch customers from NetSuite."""
        return await self.fetch_data("customer", filters, limit)
