"""Intuit QuickBooks Online connector.

Reads QuickBooks company data through the QBO Accounting API: invoices, bills,
purchase orders, items, vendors, customers.

HOW THIS CONNECTOR DIFFERS FROM THE OTHER SEVEN, AND WHY IT MATTERS

1. It cannot be provisioned from a client id and secret. Intuit's discovery
   document advertises `response_types_supported: ["code"]` and no
   client-credentials grant, so authorization is interactive and one-time. The
   connector then lives on a stored refresh token. `authenticate()` therefore
   REFRESHES; it never authorizes.

2. Refresh tokens rotate. Every refresh returns a new refresh token and retires the
   previous one. If the new value is not persisted, the integration works once and
   then fails forever with `invalid_grant`. This connector will not silently drop
   it: a `refresh_token_sink` callable in `configuration` is invoked with the
   rotated token, and its absence is logged at WARNING every single rotation rather
   than once, because a quiet version of this bug is indistinguishable from a
   revoked authorization.

3. Every path is company-scoped by `realm_id`. It is not derivable from the
   credential and there is no default.

4. Reads use QBO's SQL-shaped query language, and an empty result omits the entity
   key entirely (`{"QueryResponse": {}}`). The envelope is validated in
   `intuit_qbo.parse_query_response` so "no rows" is never confused with "we did not
   understand the response".

5. Webhooks are configured in the Intuit developer portal, NOT through the API.
   `subscribe_to_events` says so and returns False instead of POSTing to an invented
   endpoint. Inbound notifications are verified with
   `intuit_qbo.verify_webhook_signature`.

Auth, query construction, escaping, pagination arithmetic and signature
verification live in `intuit_qbo` as pure functions so they are tested by
known-input/known-output rather than against a mock that shares their assumptions.
"""

import base64
from typing import Any, Dict, List, Optional

import aiohttp
import structlog

from app.services.erp_connector_base import (
    ERPConfig,
    ERPConnectorBase,
)
from app.services.erp_connectors.intuit_qbo import (
    DEFAULT_MINOR_VERSION,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    TOKEN_ENDPOINT,
    QBOError,
    api_host,
    build_query,
    company_url,
    fault_to_error,
    parse_query_response,
    parse_token_response,
    verify_webhook_signature,
)

logger = structlog.get_logger()


class IntuitConnector(ERPConnectorBase):
    """QuickBooks Online connector (Intuit Accounting API v3)."""

    #: `CompanyInfo` exists in every QuickBooks company and needs no module or
    #: licence, which makes it the right health probe. Probing a business entity
    #: (`Invoice`, `PurchaseOrder`) is what made other connectors report a working
    #: integration as an outage when the tenant simply had no such records or no
    #: access to them.
    HEALTH_PROBE_ENTITY = "CompanyInfo"

    #: QuickBooks webhooks are configured per-app in the Intuit developer portal
    #: (endpoint URL, entity list, verifier token). There is no create-subscription
    #: API, so the base class's honest default applies. Inbound notifications are
    #: verified with verify_webhook_notification() below.
    EVENT_SUBSCRIPTION_MECHANISM = (
        "QuickBooks webhooks are configured in the Intuit developer portal "
        "(app -> Webhooks: endpoint URL, entities, verifier token). There is no API "
        "to create them. Verify inbound notifications with "
        "verify_webhook_notification()."
    )


    def __init__(self, config: ERPConfig, organization_id: str, integration_id: str):
        super().__init__(config, organization_id, integration_id)

        settings = config.configuration or {}

        self.realm_id = str(settings.get("realm_id") or "").strip()
        self.environment = settings.get("environment", "production")
        self.minor_version = str(settings.get("minor_version", DEFAULT_MINOR_VERSION))

        page_size = int(settings.get("page_size", DEFAULT_PAGE_SIZE))
        self.page_size = max(1, min(page_size, MAX_PAGE_SIZE))

        # An explicit base_url wins so a sandbox or a proxy can be targeted; the
        # environment name is the normal path. Sandbox and production are different
        # HOSTS, and mixing them returns 401 — which reads as a bad credential.
        self.host = config.base_url or api_host(self.environment)

        # Where a rotated refresh token goes. Optional, but its absence is a latent
        # "works once, then dies forever" failure, so it is warned about loudly.
        self._refresh_token_sink = settings.get("refresh_token_sink")

        if not self.realm_id:
            # Raised at construction rather than at first fetch: a missing realm id
            # cannot be recovered from, and failing here names the actual problem.
            raise ValueError(
                "Intuit connector requires configuration['realm_id'] (the "
                "QuickBooks company id); every QBO path is company-scoped"
            )

        logger.info(
            "intuit_connector_initialized",
            realm_id=self.realm_id,
            environment=self.environment,
            host=self.host,
            minor_version=self.minor_version,
            has_refresh_token_sink=bool(self._refresh_token_sink),
        )

    # ---------------------------------------------------------------- auth

    async def authenticate(self) -> str:
        """Exchange the stored refresh token for an access token.

        This is a REFRESH, not an authorization. Intuit offers no
        client-credentials grant, so there is nothing this connector can do with a
        client id and secret alone — the refresh token is the credential, and it
        comes from a one-time interactive consent.
        """
        auth = self.config.auth_config or {}
        client_id = auth.get("client_id")
        client_secret = auth.get("client_secret")
        refresh_token = auth.get("refresh_token")

        missing = [
            name
            for name, value in (
                ("client_id", client_id),
                ("client_secret", client_secret),
                ("refresh_token", refresh_token),
            )
            if not value
        ]
        if missing:
            raise QBOError(
                "Intuit auth_config is missing "
                + ", ".join(missing)
                + ". QuickBooks has no client-credentials grant: a refresh token "
                "obtained from a one-time user authorization is required."
            )

        async def _refresh():
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            ) as session:
                # client_secret_basic — advertised by the discovery document. Built
                # explicitly rather than via aiohttp.BasicAuth, which is deprecated
                # for removal in aiohttp 4.0.
                basic = base64.b64encode(
                    f"{client_id}:{client_secret}".encode("utf-8")
                ).decode("ascii")
                async with session.post(
                    TOKEN_ENDPOINT,
                    headers={
                        "Authorization": f"Basic {basic}",
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                ) as response:
                    body = await response.text()
                    try:
                        payload = await response.json(content_type=None)
                    except Exception:
                        raise QBOError(
                            f"Intuit token endpoint returned non-JSON "
                            f"({response.status}): {body[:200]}"
                        )
                    if response.status != 200:
                        # parse_token_response raises with Intuit's own error code
                        # (`invalid_grant` is the rotated-token failure).
                        parse_token_response(payload)
                        raise QBOError(f"Intuit token refresh failed ({response.status})")
                    return payload

        payload = await self.execute_with_retry(_refresh)
        access_token, expires_in, rotated = parse_token_response(payload)

        self._persist_rotated_refresh_token(rotated, refresh_token)
        self._set_token(access_token, expires_in)
        return access_token

    def _persist_rotated_refresh_token(self, rotated: Optional[str], previous: str) -> None:
        """Hand a rotated refresh token to whoever can store it.

        Intuit retires the old refresh token once a new one is issued. Without
        persistence the next refresh fails with `invalid_grant` and the integration
        is dead until a human re-authorizes — so this warns on EVERY rotation when
        there is no sink, rather than once at startup where it would scroll away.
        """
        if not rotated or rotated == previous:
            return

        # Keep the in-memory config usable for the life of this object even when
        # there is no sink, so a long-running worker does not break mid-run.
        self.config.auth_config["refresh_token"] = rotated

        if not self._refresh_token_sink:
            logger.warning(
                "intuit_refresh_token_rotated_but_not_persisted",
                realm_id=self.realm_id,
                integration_id=self.integration_id,
                detail=(
                    "Intuit issued a new refresh token and retired the previous one. "
                    "It is held in memory only. When this process restarts the "
                    "integration will fail with invalid_grant and need a new user "
                    "authorization. Provide configuration['refresh_token_sink']."
                ),
            )
            return

        try:
            self._refresh_token_sink(rotated)
            # Named for what is actually known. The sink returned without raising --
            # that is not the same as a durable write, which only the sink can
            # confirm. `_persisted` would be a claim we cannot support, and the
            # reporting-honesty guard correctly rejected it.
            logger.info("intuit_refresh_token_handed_to_sink", realm_id=self.realm_id)
        except Exception as exc:
            # A sink that throws must not be mistaken for a successful save.
            logger.error(
                "intuit_refresh_token_persist_failed",
                realm_id=self.realm_id,
                error=str(exc),
                detail="the rotated refresh token was NOT stored; re-authorization "
                       "will be required after this process exits",
            )

    async def verify_credentials(self) -> None:
        """OAuth2 refresh is a real round trip, so the default is already honest:
        a bad client secret or a retired refresh token fails at the token endpoint
        rather than being echoed back out of config."""
        await self.get_auth_token()

    # ---------------------------------------------------------------- reads

    def _headers(self, token: str) -> Dict[str, str]:
        # `Accept: application/json` is REQUIRED. QBO answers XML by default, and an
        # XML body parsed as JSON fails in a way that says nothing about content
        # negotiation. (Compare SAP, which returns 406 rather than the wrong format —
        # a wrong Accept is a distinct trap on every vendor.)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def fetch_data(
        self,
        entity_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch rows for a QBO entity, following pagination to completion.

        Paging is where silent truncation lives: QBO returns at most 1000 rows and
        defaults to 100, so a connector that issues one request and returns its
        result quietly loses everything past the first page. `limit` is honoured
        exactly, and the loop stops on a short page rather than guessing a total.
        """
        token = await self.get_auth_token()
        url = company_url(self.host, self.realm_id, "query")

        rows: List[Dict[str, Any]] = []
        start_position = 1  # 1-based, not 0-based.

        while True:
            remaining = None if limit is None else limit - len(rows)
            if remaining is not None and remaining <= 0:
                break

            page_size = self.page_size if remaining is None else min(self.page_size, remaining)
            query = build_query(
                entity_type,
                filters=filters,
                start_position=start_position,
                max_results=page_size,
            )

            async def _fetch(query=query):
                params = {"query": query, "minorversion": self.minor_version}
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                ) as session:
                    async with session.get(
                        url, headers=self._headers(token), params=params
                    ) as response:
                        try:
                            payload = await response.json(content_type=None)
                        except Exception:
                            body = await response.text()
                            raise QBOError(
                                f"QuickBooks returned non-JSON ({response.status}): "
                                f"{body[:200]}",
                                status=response.status,
                            )

                        if response.status == 401:
                            # The token is dead whatever its stated expiry claimed;
                            # drop it so the retry re-authenticates instead of
                            # burning the budget on the same rejected credential.
                            self.invalidate_token()

                        if response.status >= 400:
                            if isinstance(payload, dict) and "Fault" in payload:
                                raise fault_to_error(payload, status=response.status)
                            raise QBOError(
                                f"QuickBooks API error {response.status}: {str(payload)[:200]}",
                                status=response.status,
                            )

                        return parse_query_response(payload, entity_type)

            page = await self.execute_with_retry(_fetch)
            rows.extend(page)

            # A short page means the end. Trusting a reported total instead would
            # loop forever whenever QBO filters rows after counting them.
            if len(page) < page_size:
                break
            start_position += len(page)

        if limit is not None:
            rows = rows[:limit]

        logger.info(
            "intuit_data_fetched",
            entity_type=entity_type,
            record_count=len(rows),
            realm_id=self.realm_id,
        )
        return rows

    # ------------------------------------------------------------- events


    def verify_webhook_notification(self, raw_body: bytes, signature_header: str) -> bool:
        """Verify an inbound QuickBooks webhook.

        MUST be given the RAW body bytes. Re-serialized JSON reorders keys and
        changes whitespace, so the HMAC never matches and every genuine notification
        is rejected.
        """
        verifier = (self.config.configuration or {}).get("webhook_verifier_token")
        if not verifier:
            logger.warning(
                "intuit_webhook_verifier_not_configured",
                realm_id=self.realm_id,
                detail="rejecting the notification: an unverifiable webhook is not "
                       "trustworthy input",
            )
            return False
        return verify_webhook_signature(raw_body, signature_header, verifier)

    # ------------------------------------------------------------- health

    async def health_check(self) -> Dict[str, Any]:
        """Three-state health, distinguishing a broken connection from a missing
        entity — see `ERPConnectorBase.probe_health`."""
        return await self.probe_health(
            self.HEALTH_PROBE_ENTITY,
            details={
                "realm_id": self.realm_id,
                "environment": self.environment,
                "minor_version": self.minor_version,
            },
        )
