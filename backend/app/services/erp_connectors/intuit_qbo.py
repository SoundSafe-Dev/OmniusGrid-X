"""Pure helpers for the Intuit QuickBooks Online (QBO) Accounting API.

Kept separate from the connector so every rule below is testable by
known-input/known-output, with no network and no mock that could encode the same
assumption as the code.

WHAT IS ESTABLISHED FROM INTUIT'S OWN DISCOVERY DOCUMENT (fetched, not assumed —
https://developer.api.intuit.com/.well-known/openid_configuration):

    issuer                  https://oauth.platform.intuit.com/op/v1
    token_endpoint          https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer
    authorization_endpoint  https://appcenter.intuit.com/connect/oauth2
    revocation_endpoint     https://developer.api.intuit.com/v2/oauth2/tokens/revoke
    response_types          ["code"]                       <- ONLY the code flow
    token auth methods      client_secret_post, client_secret_basic

THE CONSEQUENCE, AND IT SHAPES THE WHOLE CONNECTOR. Intuit advertises only the
authorization-code response type; there is no client-credentials grant. So a
QuickBooks integration CANNOT be provisioned from a client id and secret the way
SAP or Dynamics can. It requires a one-time interactive user authorization, after
which the connector lives on a stored refresh token.

And refresh tokens ROTATE: each refresh returns a NEW refresh token and the old one
stops working. A connector that does not persist the new value works exactly once
and then fails forever with `invalid_grant` — which reads like a revoked
authorization rather than a bug in us. That is why `parse_token_response` surfaces
the rotated token as a first-class field instead of letting it be ignored.

QBO also differs from the OData connectors in ways worth stating:

  - Every path is scoped by a `realmId` (the company id). It is not optional and it
    is not derivable from the credential.
  - Reads go through a SQL-ish query language, not OData query options.
  - An EMPTY result is `{"QueryResponse": {}}` — the entity key is ABSENT rather
    than an empty list. Treating a missing key as an error, or an error as a missing
    key, is the silent-empty-result failure this codebase keeps finding.
"""

from __future__ import annotations

import hashlib
import hmac
import base64
from typing import Any, Dict, List, Optional, Tuple

# From the discovery document, not from documentation prose.
TOKEN_ENDPOINT = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
AUTHORIZATION_ENDPOINT = "https://appcenter.intuit.com/connect/oauth2"
REVOCATION_ENDPOINT = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"

PRODUCTION_HOST = "https://quickbooks.api.intuit.com"
SANDBOX_HOST = "https://sandbox-quickbooks.api.intuit.com"

#: QBO caps a page at 1000 rows and defaults to 100.
MAX_PAGE_SIZE = 1000
DEFAULT_PAGE_SIZE = 100

#: Pinning a minor version is how QBO field-level changes are kept from silently
#: altering responses. Unpinned requests get the oldest supported behaviour.
DEFAULT_MINOR_VERSION = "75"


class QBOError(Exception):
    """A fault reported by QuickBooks, carrying its own error codes."""

    def __init__(self, message: str, *, codes: Optional[List[str]] = None, status: Optional[int] = None):
        super().__init__(message)
        self.codes = codes or []
        self.status = status


def api_host(environment: str) -> str:
    """Resolve the API host for an environment name.

    Sandbox and production are DIFFERENT hosts, not a path or a header. Pointing a
    sandbox credential at the production host returns 401, which looks like a bad
    credential rather than a wrong host — the same confusion that made the NetSuite
    `suitetalk.net` defect hard to read.
    """
    normalized = (environment or "production").strip().lower()
    if normalized in ("sandbox", "sbx", "dev", "development"):
        return SANDBOX_HOST
    if normalized in ("production", "prod", "live"):
        return PRODUCTION_HOST
    raise ValueError(
        f"unknown Intuit environment {environment!r}; expected 'sandbox' or 'production'"
    )


def company_url(host: str, realm_id: str, resource: str = "") -> str:
    """Build a company-scoped URL: `{host}/v3/company/{realmId}/{resource}`.

    Segments are joined rather than interpolated so a configured host with a
    trailing slash cannot produce an empty path segment — the exact defect found in
    the SAP connector when a Prism mock received `//A_PurchaseOrder`.
    """
    if not realm_id:
        raise ValueError(
            "realm_id (the QuickBooks company id) is required; every QBO path is "
            "company-scoped and it cannot be derived from the credential"
        )
    parts = [host.rstrip("/"), "v3", "company", str(realm_id).strip("/")]
    if resource:
        parts.append(resource.strip("/"))
    return "/".join(parts)


def escape_query_literal(value: str) -> str:
    r"""Escape a string for a single-quoted QBO query literal.

    QBO's query language is SQL-shaped, so an unescaped apostrophe in a value ends
    the literal and the remainder is parsed as query syntax. That is an injection
    vector, not merely a parse error: `filters` reach here from tenant-supplied
    integration configuration.

    Intuit's rule is backslash-escaping, so the BACKSLASH MUST BE ESCAPED FIRST —
    doing it second would double-escape the backslashes this function just added
    and change the value's meaning.
    """
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def build_query(
    entity: str,
    *,
    filters: Optional[Dict[str, Any]] = None,
    start_position: int = 1,
    max_results: int = DEFAULT_PAGE_SIZE,
) -> str:
    """Compose a QBO query.

    STARTPOSITION is 1-BASED. Passing 0 is not "the beginning" — off-by-one here
    silently skips or repeats a row at every page boundary, which is invisible until
    someone reconciles totals.
    """
    if not entity:
        raise ValueError("entity is required")
    if start_position < 1:
        raise ValueError(f"STARTPOSITION is 1-based; got {start_position}")
    if max_results < 1 or max_results > MAX_PAGE_SIZE:
        raise ValueError(f"MAXRESULTS must be 1..{MAX_PAGE_SIZE}; got {max_results}")

    query = f"select * from {entity}"

    if filters:
        clauses = []
        for field, value in filters.items():
            if isinstance(value, bool):
                clauses.append(f"{field} = {str(value).lower()}")
            elif isinstance(value, (int, float)):
                clauses.append(f"{field} = {value}")
            elif value is None:
                clauses.append(f"{field} is null")
            else:
                clauses.append(f"{field} = '{escape_query_literal(value)}'")
        query += " where " + " and ".join(clauses)

    return f"{query} startposition {start_position} maxresults {max_results}"


def parse_query_response(payload: Dict[str, Any], entity: str) -> List[Dict[str, Any]]:
    """Extract rows from a QBO query response.

    THE IMPORTANT CASE. A query that matches nothing returns

        {"QueryResponse": {}, "time": "..."}

    with the entity key ABSENT — not an empty list. So "no rows" and "we asked for
    the wrong entity" and "the response shape changed" all look alike unless the
    envelope itself is checked. Here a missing `QueryResponse` raises, while a
    present-but-empty one is an honest zero.
    """
    if "Fault" in payload:
        raise fault_to_error(payload)

    if "QueryResponse" not in payload:
        raise QBOError(
            "QBO response has no QueryResponse envelope; refusing to report zero "
            f"rows for a response we do not understand: {sorted(payload)[:6]}"
        )

    query_response = payload["QueryResponse"] or {}
    rows = query_response.get(entity, [])
    if isinstance(rows, dict):  # a single object rather than a list
        return [rows]
    return list(rows)


def fault_to_error(payload: Dict[str, Any], status: Optional[int] = None) -> QBOError:
    """Turn a QBO `Fault` envelope into an exception that names the actual problem.

    QBO reports errors as a Fault with per-error codes. Collapsing that to the HTTP
    status loses the one detail that distinguishes "your query is malformed" from
    "that entity does not exist here" — and the second is a DEGRADED health state,
    not an outage.
    """
    fault = payload.get("Fault") or {}
    errors = fault.get("Error") or []
    codes = [str(e.get("code")) for e in errors if e.get("code") is not None]
    messages = []
    for error in errors:
        message = error.get("Message") or ""
        detail = error.get("Detail") or ""
        messages.append(f"{message}: {detail}".strip(": ") if detail else message)
    summary = "; ".join(m for m in messages if m) or "unspecified QuickBooks fault"
    fault_type = fault.get("type")
    if fault_type:
        summary = f"{fault_type}: {summary}"
    return QBOError(summary, codes=codes, status=status)


def parse_token_response(payload: Dict[str, Any]) -> Tuple[str, Optional[float], Optional[str]]:
    """Return `(access_token, expires_in, rotated_refresh_token)`.

    The third element is why this function exists. Intuit returns a NEW refresh
    token on every refresh and retires the old one. Dropping it means the
    integration authenticates successfully today and fails permanently at the next
    refresh with `invalid_grant` — a failure that reads as "the user revoked our
    access" and sends everyone looking in the wrong place.
    """
    if "error" in payload:
        description = payload.get("error_description") or ""
        raise QBOError(f"{payload['error']}: {description}".strip(": "))

    token = payload.get("access_token")
    if not token:
        raise QBOError(f"token response has no access_token (keys: {sorted(payload)})")

    expires_in = payload.get("expires_in")
    try:
        expires_in = float(expires_in) if expires_in is not None else None
    except (TypeError, ValueError):
        expires_in = None

    return token, expires_in, payload.get("refresh_token")


def verify_webhook_signature(raw_body: bytes, signature_header: str, verifier_token: str) -> bool:
    """Verify Intuit's `intuit-signature` header.

    Base64-encoded HMAC-SHA256 over the RAW request body, keyed by the webhook
    verifier token from the Intuit developer portal.

    Two things must be right or the check is theatre:

      - It runs over the RAW BYTES. Re-serializing the parsed JSON reorders keys and
        changes whitespace, so the digest will never match and every genuine
        notification is rejected.
      - The comparison is CONSTANT TIME. `==` on a digest leaks how many leading
        bytes were correct, which is enough to forge a signature byte by byte.

    Returns False rather than raising on a malformed header: an unverified webhook
    is a rejection, not a server error.
    """
    if not signature_header or not verifier_token or raw_body is None:
        return False

    digest = hmac.new(verifier_token.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")

    return hmac.compare_digest(expected, signature_header.strip())
