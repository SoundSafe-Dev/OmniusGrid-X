"""Authenticate an inbound ERP webhook the way each vendor actually signs one.

THE PROBLEM THIS SOLVES. The route accepted exactly one header,
`X-Webhook-Signature`, carrying a hex HMAC. **We invented that header.** No ERP vendor
sends it, so no vendor's webhook could authenticate even after the signature was fixed
to hash the raw body:

    Intuit QuickBooks   `intuit-signature`, base64 HMAC-SHA256 over the raw body
    Dataverse/Dynamics  a static header you configure on the serviceendpoint record --
                        NOT an HMAC at all
    NetSuite            whatever a SuiteScript user-event script chooses to send
    SAP Event Mesh      typically OAuth or basic auth on the subscription
    Odoo                base_automation puts a token in the URL

So "which header" and "which scheme" are per-integration configuration with
per-vendor defaults, not constants. An operator wiring up Intuit should need to supply
the verifier token and nothing else.

CONFIGURATION, on `integration.configuration`:

    webhook_secret              the shared secret / verifier token  (required)
    webhook_auth_mode           "hmac_sha256" | "shared_secret"     (vendor default)
    webhook_signature_header    header carrying the credential      (vendor default)
    webhook_signature_encoding  "auto" | "hex" | "base64"           (default "auto")

EVERYTHING FAILS CLOSED. No secret, no header, unknown mode, empty body — all reject.
An unauthenticated write into `erp_integration_events` is an open door into a tenant's
business data, and the route is deliberately exempt from the authentication walk
because it is supposed to be protected by exactly this.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Dict, Mapping, Optional, Tuple

import structlog

logger = structlog.get_logger()

HMAC_SHA256 = "hmac_sha256"
SHARED_SECRET = "shared_secret"
SUPPORTED_MODES = (HMAC_SHA256, SHARED_SECRET)

#: The header we historically accepted. Kept as the default for vendors whose scheme
#: is fully operator-defined (NetSuite's SuiteScript, a middleware, our own smoke
#: test), because there the operator chooses both ends.
DEFAULT_HEADER = "x-webhook-signature"

#: Per-vendor defaults, so configuration is only needed where a vendor differs.
#:
#: Only Intuit's is verified against vendor documentation (its connector implements
#: the same check). The others are the documented mechanism for that vendor's webhook
#: and are marked as such -- an operator can override every field, which is the point.
VENDOR_DEFAULTS: Dict[str, Dict[str, str]] = {
    # Verified: base64 HMAC-SHA256 of the raw body, keyed by the app's verifier token.
    "intuit": {"mode": HMAC_SHA256, "header": "intuit-signature", "encoding": "base64"},
    # Dataverse serviceendpoint webhooks authenticate with an HTTP header whose name
    # and value YOU set when registering the endpoint. There is no HMAC option, so a
    # static shared secret is the honest representation.
    "dynamics": {"mode": SHARED_SECRET, "header": "x-omniusgrid-webhook-token", "encoding": "auto"},
    # Operator-defined at the sending end.
    "netsuite": {"mode": HMAC_SHA256, "header": DEFAULT_HEADER, "encoding": "auto"},
    "sap": {"mode": HMAC_SHA256, "header": DEFAULT_HEADER, "encoding": "auto"},
    "oracle": {"mode": HMAC_SHA256, "header": DEFAULT_HEADER, "encoding": "auto"},
    "infor": {"mode": HMAC_SHA256, "header": DEFAULT_HEADER, "encoding": "auto"},
    "epicor": {"mode": HMAC_SHA256, "header": DEFAULT_HEADER, "encoding": "auto"},
    # Odoo's automated-action webhook sends no signature header; the secret lives in
    # the URL. Represented as a shared-secret header so an operator who fronts it with
    # a proxy that adds one still works, and so the default is not silently "accept".
    "odoo": {"mode": SHARED_SECRET, "header": "x-omniusgrid-webhook-token", "encoding": "auto"},
}


def resolve_scheme(erp_type: Optional[str], configuration: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Merge the vendor default with any per-integration override."""
    defaults = VENDOR_DEFAULTS.get((erp_type or "").strip().lower(), {
        "mode": HMAC_SHA256, "header": DEFAULT_HEADER, "encoding": "auto",
    })
    config = configuration or {}
    return {
        "mode": str(config.get("webhook_auth_mode") or defaults["mode"]).strip().lower(),
        "header": str(config.get("webhook_signature_header") or defaults["header"]).strip().lower(),
        "encoding": str(config.get("webhook_signature_encoding") or defaults["encoding"]).strip().lower(),
    }


def _expected_digests(secret: str, raw_body: bytes) -> Tuple[str, str]:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256)
    return digest.hexdigest(), base64.b64encode(digest.digest()).decode("ascii")


def _verify_hmac(secret: str, raw_body: bytes, presented: str, encoding: str) -> bool:
    candidate = presented.strip()
    # `sha256=<hex>` — GitHub's convention, adopted by several middlewares.
    if candidate.lower().startswith("sha256="):
        candidate = candidate[len("sha256="):]

    expected_hex, expected_b64 = _expected_digests(secret, raw_body)

    # Both compared even when an encoding is pinned, so timing does not reveal which
    # form was presented. `compare_digest` handles unequal lengths safely.
    hex_ok = hmac.compare_digest(expected_hex, candidate)
    b64_ok = hmac.compare_digest(expected_b64, candidate)

    if encoding == "hex":
        return hex_ok
    if encoding == "base64":
        return b64_ok
    return hex_ok or b64_ok


def authenticate_webhook(
    *,
    erp_type: Optional[str],
    configuration: Optional[Mapping[str, Any]],
    raw_body: Optional[bytes],
    headers: Mapping[str, str],
) -> Tuple[bool, str]:
    """Return `(authenticated, reason)`.

    `reason` is for the server-side log only. The route must not return it: telling an
    unauthenticated caller *why* it failed lets them discover whether an integration
    exists, which mode it uses and whether a secret is set.
    """
    config = configuration or {}
    secret = config.get("webhook_secret")
    if not secret:
        return False, "no webhook_secret configured on the integration"

    scheme = resolve_scheme(erp_type, config)
    mode, header_name, encoding = scheme["mode"], scheme["header"], scheme["encoding"]

    if mode not in SUPPORTED_MODES:
        # Fail closed on a typo. Falling back to a default here would mean a
        # misspelled mode silently downgraded the check.
        return False, f"unsupported webhook_auth_mode {mode!r}"

    # Header lookup is case-insensitive: HTTP header names are, and vendors are
    # inconsistent (`intuit-signature` lowercase, `X-Webhook-Signature` mixed).
    lowered = {str(k).lower(): v for k, v in dict(headers).items()}
    presented = lowered.get(header_name)
    if not presented or not str(presented).strip():
        return False, f"missing or empty {header_name!r} header"

    if mode == SHARED_SECRET:
        # A static credential. Constant-time even though there is no digest, because
        # a plain `==` on a secret leaks its prefix.
        ok = hmac.compare_digest(str(secret), str(presented).strip())
        return ok, "shared secret matched" if ok else "shared secret mismatch"

    if raw_body is None:
        return False, "no raw body to verify"

    ok = _verify_hmac(str(secret), raw_body, str(presented), encoding)
    return ok, "hmac matched" if ok else "hmac mismatch over the raw body"


def describe_scheme(erp_type: Optional[str], configuration: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """What this integration expects, for operator-facing diagnostics.

    Never includes the secret. Used by the webhook self-check so someone can confirm
    the configuration before pointing a vendor at the endpoint, rather than debugging
    a 401 that deliberately says nothing.
    """
    scheme = resolve_scheme(erp_type, configuration)
    return {
        "erp_type": erp_type,
        "auth_mode": scheme["mode"],
        "signature_header": scheme["header"],
        "signature_encoding": scheme["encoding"],
        "secret_configured": bool((configuration or {}).get("webhook_secret")),
        "signs": "the raw request body" if scheme["mode"] == HMAC_SHA256 else "n/a (static header value)",
    }
