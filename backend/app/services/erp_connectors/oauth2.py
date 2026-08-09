"""Async OAuth 2.0 token acquisition shared by the ERP connectors.

WHY THIS EXISTS. Three connectors depended on SYNCHRONOUS OAuth libraries that were
never declared as dependencies:

    sap_connector.py      from requests_oauthlib import OAuth2Session
    oracle_connector.py   from requests_oauthlib import OAuth2Session
    dynamics_connector.py import msal

Neither `requests-oauthlib` nor `msal` is in requirements.txt, so all three modules
raised ImportError on import. `erp_connector_factory` maps ERPType.SAP,
ERPType.ORACLE and ERPType.DYNAMICS straight at them, which means constructing any
of those three connectors failed before a single line of their logic ran — three of
the seven ERP integrations were unreachable.

Installing the missing packages would have been the smaller change and the wrong
one. Both are blocking, `requests`-based libraries: calling them from inside an
async connector stalls the event loop for the duration of a network round trip,
which on a shared worker means every other in-flight request waits on an ERP
handshake. This does the same job with aiohttp.

SAP's usage was also the wrong GRANT. It called `fetch_token(...,
authorization_response=...)`, which is the authorization-code flow — it expects a
browser redirect carrying a code. A scheduled server-to-server sync has no user and
no browser, so it could never have completed. Server-to-server is
`client_credentials`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional, Tuple

import aiohttp
import structlog

logger = structlog.get_logger()


class OAuth2Error(RuntimeError):
    """Token acquisition failed. Carries the provider's own message."""


def parse_token_payload(payload: Mapping[str, Any]) -> Tuple[str, Optional[float]]:
    """Extract (access_token, expires_in) from a token response.

    ``expires_in`` is returned rather than dropped so the caller can cache against
    the provider's real lifetime. The connector base used to assume one hour for
    every provider, so anything shorter was served from cache long after it died —
    producing 401s that look like a permissions problem rather than an expiry one.
    """
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise OAuth2Error(
            f"token response contained no access_token (keys: {sorted(payload)})"
        )
    raw = payload.get("expires_in")
    try:
        expires_in = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        expires_in = None
    return token, expires_in


async def fetch_client_credentials_token(
    *,
    token_url: str,
    client_id: str,
    client_secret: str,
    scope: Optional[str] = None,
    resource: Optional[str] = None,
    extra_form: Optional[Mapping[str, str]] = None,
    timeout_seconds: int = 30,
    session: Optional[aiohttp.ClientSession] = None,
) -> Tuple[str, Optional[float]]:
    """Run the client-credentials grant and return (access_token, expires_in).

    ``session`` is injectable so tests can assert the exact form body — which is
    the part that differs per vendor and the part most likely to be wrong.
    """
    if not token_url:
        raise OAuth2Error("no token_url configured")
    if not (client_id and client_secret):
        raise OAuth2Error("client_credentials needs both client_id and client_secret")

    form: Dict[str, str] = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if scope:
        form["scope"] = scope
    if resource:
        # Azure AD v1.0 and some Oracle Fusion tenants use `resource` rather than
        # `scope`; sending both is harmless and saves a per-vendor branch here.
        form["resource"] = resource
    if extra_form:
        form.update(extra_form)

    owns_session = session is None
    http = session or aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout_seconds)
    )
    try:
        async with http.post(
            token_url,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            body = await response.text()
            if response.status != 200:
                # Include the provider's body: OAuth errors are specific
                # (invalid_client, invalid_scope, unauthorized_client) and a bare
                # status code sends whoever is debugging to the wrong place.
                raise OAuth2Error(
                    f"token request to {token_url} failed: {response.status} - {body}"
                )
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise OAuth2Error(
                    f"token endpoint {token_url} returned non-JSON: {body[:200]}"
                ) from exc
    finally:
        if owns_session:
            await http.close()

    token, expires_in = parse_token_payload(payload)
    logger.info(
        "erp_oauth2_token_acquired",
        token_url=token_url,
        expires_in=expires_in,
        scope=scope,
    )
    return token, expires_in
