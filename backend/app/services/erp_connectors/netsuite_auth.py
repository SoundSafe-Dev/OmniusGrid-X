"""NetSuite authentication: Token-Based Auth (OAuth 1.0a) and OAuth 2.0.

WHY THIS IS A SEPARATE MODULE. The old connector's `authenticate()` read a static
`access_token` out of config and sent it as `Authorization: Bearer <token>`.
NetSuite does not work that way:

* **TBA** — NetSuite's standard server-to-server mechanism — is OAuth 1.0a with
  HMAC-SHA256. There is no token endpoint and nothing to cache: EVERY request is
  individually signed over its own method, URL and query string. A `Bearer` header
  is rejected outright.
* **OAuth 2.0 M2M** issues a short-lived bearer token from a token endpoint, so it
  does need caching — and it needs the provider's own `expires_in` honoured.

Signing is isolated here because it is the part most likely to be subtly wrong and
the part that can be tested exactly: a signature is a pure function of its inputs,
so the tests assert known-input/known-output rather than "it returned something".

REFERENCE: RFC 5849 §3.4 for the signature base string, with NetSuite's
HMAC-SHA256 extension and its `realm` requirement.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Dict, Mapping, Optional, Tuple
from urllib.parse import quote, urlparse, urlencode, parse_qsl


def percent_encode(value: str) -> str:
    """RFC 5849 §3.6 percent-encoding.

    Deliberately NOT `urllib.parse.quote` with defaults: RFC 3986 unreserved is
    exactly ALPHA / DIGIT / '-' / '.' / '_' / '~', and everything else — including
    '/' — must be escaped. `quote`'s default `safe='/'` leaves slashes intact, which
    silently produces a different base string and therefore an invalid signature
    that NetSuite rejects with a generic 401.
    """
    return quote(str(value), safe="-._~")


def _normalize_parameters(params: Mapping[str, str]) -> str:
    """RFC 5849 §3.4.1.3.2 — encode, then sort by encoded key, then by encoded value."""
    encoded = [(percent_encode(k), percent_encode(v)) for k, v in params.items()]
    encoded.sort()
    return "&".join(f"{k}={v}" for k, v in encoded)


def _base_string_uri(url: str) -> str:
    """RFC 5849 §3.4.1.2 — scheme and host lowercased, no query, no default port."""
    parts = urlparse(url)
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    return f"{scheme}://{host}{parts.path}"


def signature_base_string(method: str, url: str, params: Mapping[str, str]) -> str:
    """The exact string that gets signed.

    Query parameters from the URL are folded in, because RFC 5849 requires the
    signature to cover them. Omitting them is the classic TBA bug: unfiltered
    requests sign correctly and every filtered or paginated one fails, which reads
    as "the API works but pagination is broken".
    """
    query_params = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
    merged = {**query_params, **dict(params)}
    return "&".join(
        [
            method.upper(),
            percent_encode(_base_string_uri(url)),
            percent_encode(_normalize_parameters(merged)),
        ]
    )


def sign_hmac_sha256(base_string: str, consumer_secret: str, token_secret: str) -> str:
    key = f"{percent_encode(consumer_secret)}&{percent_encode(token_secret)}".encode()
    digest = hmac.new(key, base_string.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def build_tba_header(
    *,
    method: str,
    url: str,
    account_id: str,
    consumer_key: str,
    consumer_secret: str,
    token_id: str,
    token_secret: str,
    extra_params: Optional[Mapping[str, str]] = None,
    timestamp: Optional[int] = None,
    nonce: Optional[str] = None,
) -> str:
    """Build the `Authorization: OAuth ...` header for one NetSuite request.

    ``timestamp`` and ``nonce`` are injectable ONLY so the tests can assert a
    known signature; production always generates them.

    The realm is the NetSuite account id, uppercased. NetSuite rejects a request
    whose realm does not match the account the credentials belong to, and the error
    it returns does not say so.
    """
    oauth_params: Dict[str, str] = {
        "oauth_consumer_key": consumer_key,
        "oauth_token": token_id,
        "oauth_signature_method": "HMAC-SHA256",
        "oauth_timestamp": str(timestamp if timestamp is not None else int(time.time())),
        "oauth_nonce": nonce if nonce is not None else secrets.token_hex(16),
        "oauth_version": "1.0",
    }

    signing_params = {**oauth_params, **(dict(extra_params) if extra_params else {})}
    base = signature_base_string(method, url, signing_params)
    signature = sign_hmac_sha256(base, consumer_secret, token_secret)

    # realm is NOT part of the signature, and must not be added to the params above.
    header_params = {**oauth_params, "oauth_signature": signature}
    rendered = ", ".join(
        f'{percent_encode(k)}="{percent_encode(v)}"' for k, v in sorted(header_params.items())
    )
    return f'OAuth realm="{account_id.upper()}", {rendered}'


def account_host(account_id: str) -> str:
    """Map a NetSuite account id to its API host.

    The old connector built `https://{account}.suitetalk.net/rest/services`, which
    is not a NetSuite host at all — that connector could never have reached
    NetSuite. The real form is
    `https://{account}.suitetalk.api.netsuite.com/services/rest`, and the account id
    in the host is lowercased with underscores turned into hyphens, so a sandbox
    account `1234567_SB1` becomes `1234567-sb1`.
    """
    normalized = account_id.strip().lower().replace("_", "-")
    return f"https://{normalized}.suitetalk.api.netsuite.com"


def rest_base_url(account_id: str) -> str:
    return f"{account_host(account_id)}/services/rest"


def oauth2_token_url(account_id: str) -> str:
    return f"{rest_base_url(account_id)}/auth/oauth2/v1/token"


def parse_oauth2_token_response(payload: Mapping[str, object]) -> Tuple[str, Optional[float]]:
    """Pull (access_token, expires_in) out of a token response.

    `expires_in` is returned rather than discarded so the caller can cache against
    the provider's real lifetime — the base class used to assume one hour for
    everything, which meant serving a dead token for the remainder whenever the
    provider issued something shorter.
    """
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError(f"NetSuite token response has no access_token: {sorted(payload)}")
    raw_expiry = payload.get("expires_in")
    expires_in: Optional[float]
    try:
        expires_in = float(raw_expiry) if raw_expiry is not None else None
    except (TypeError, ValueError):
        expires_in = None
    return token, expires_in
