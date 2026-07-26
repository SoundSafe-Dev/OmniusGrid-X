"""ERP inbound webhook receiver route (Phase A, task 4).

Accepts real-time events pushed by ERP systems, authenticates them (HMAC-SHA256 over
the RAW REQUEST BODY using the integration's stored `webhook_secret`), deduplicates by
(source_system, event_id), and stores them as `ERPIntegrationEvent` rows for
downstream processing/correlation.

`verify_signature` here is the single implementation;
`ERPWebhookReceiver._validate_signature` delegates to it so the two cannot drift.
Both previously hashed a re-serialised, key-sorted rendering of the parsed payload,
which no vendor produces — see that function's docstring. Kept in its own router (prefix `/api/v1/erp/webhooks`)
so it doesn't touch the integrations CRUD router.
"""

import base64
import hashlib
import hmac
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import ERPIntegrationEvent, IntegrationConfiguration

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/erp/webhooks", tags=["Edge"])


def compute_signature(secret: str, raw_body: bytes) -> str:
    """HMAC-SHA256 over the RAW REQUEST BODY, hex-encoded.

    THE DEFECT THIS REPLACES. This used to hash
    `json.dumps(event_data, sort_keys=True)` -- the parsed payload, re-serialised
    with sorted keys. No ERP vendor signs a canonicalised re-serialisation of its
    own payload; they all sign the exact bytes they transmit. Key order, whitespace,
    unicode escaping and float formatting all differ, so the digest could never
    match and **every genuine vendor webhook was rejected with 401**.

    The old tests passed because they called this same function to produce the
    signature they then verified -- a fixture encoding the same assumption as the
    code, so it could not disconfirm it. One of them asserted the property that made
    it wrong:

        def test_signature_order_independent():
            assert compute_signature(secret, a) == compute_signature(secret, b)

    Order independence is exactly what makes a signature unable to authenticate a
    real request.
    """
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify_signature(
    secret: Optional[str], raw_body: bytes, signature: Optional[str]
) -> bool:
    """True only when a secret is configured and the signature matches the raw body.

    Fails closed on a missing secret or a missing signature: an integration with no
    secret configured must not accept unauthenticated events.

    Accepts the three encodings vendors actually use, because there is no single
    convention and guessing wrong looks identical to a forged request:

      - hex          (SAP, Dynamics and most OData-era webhooks)
      - base64       (Intuit's `intuit-signature`)
      - `sha256=<hex>`  (GitHub-style prefix, used by several middlewares)

    Every comparison is constant time. `hmac.compare_digest` also handles
    differing lengths safely, so an attacker learns nothing from a short guess.
    """
    if not secret or not signature or raw_body is None:
        return False

    candidate = signature.strip()
    if candidate.lower().startswith("sha256="):
        candidate = candidate[len("sha256="):]

    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256)
    expected_hex = digest.hexdigest()
    expected_b64 = base64.b64encode(digest.digest()).decode("ascii")

    # Both compared, not short-circuited on the first, so timing does not reveal
    # which encoding the caller used.
    hex_ok = hmac.compare_digest(expected_hex, candidate)
    b64_ok = hmac.compare_digest(expected_b64, candidate)
    return hex_ok or b64_ok


@router.post("/{erp_type}")
async def receive_erp_webhook(
    erp_type: str,
    event_data: Dict[str, Any],
    request: Request,
    x_webhook_signature: Optional[str] = Header(default=None),
    x_event_type: Optional[str] = Header(default=None),
    x_event_id: Optional[str] = Header(default=None),
    x_source_system: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Authenticate, dedupe, and store an inbound ERP webhook event."""
    # The RAW bytes, which is what the vendor signed. Starlette caches the body, so
    # reading it here after FastAPI has already parsed `event_data` is free and safe.
    raw_body = await request.body()

    # THE SIGNATURE SELECTS THE TENANT.
    #
    # This route is a single shared path per erp_type -- `/api/v1/erp/webhooks/sap`
    # -- with nothing in the URL or headers identifying the organisation. It used to
    # take `.first()` of the active integrations for that erp_type, ACROSS ALL
    # ORGANISATIONS, and verify against that one's secret.
    #
    # With two tenants both running SAP, whichever row the database happened to
    # return first was the only one whose webhooks could ever authenticate; every
    # other tenant's genuine events were rejected as forged. And had the secrets
    # collided, one tenant's events would have been filed against another's
    # integration.
    #
    # Resolving BY SIGNATURE is the correct answer for a shared path: the tenant is
    # whoever holds the secret that verifies these exact bytes. That is the same
    # evidence the signature already provides, so it grants nothing extra.
    candidates = (
        await db.execute(
            select(IntegrationConfiguration).where(
                IntegrationConfiguration.integration_type == "erp",
                IntegrationConfiguration.erp_type == erp_type,
                IntegrationConfiguration.is_active == True,  # noqa: E712
            )
        )
    ).scalars().all()

    if not candidates:
        raise HTTPException(status_code=404, detail=f"no active ERP integration for '{erp_type}'")

    integration = None
    for candidate in candidates:
        secret = (candidate.configuration or {}).get("webhook_secret")
        if verify_signature(secret, raw_body, x_webhook_signature):
            integration = candidate
            break

    if integration is None:
        # Logged server-side; the response stays generic so an unauthenticated caller
        # cannot probe how many integrations exist or whether any has a secret.
        logger.warning(
            "erp_webhook_signature_rejected",
            erp_type=erp_type,
            candidates=len(candidates),
            has_signature=bool(x_webhook_signature),
        )
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    # THE TENANT GUC. erp_integration_events is RLS-protected with a FOR ALL USING
    # policy, which Postgres also applies as the INSERT check -- so with no GUC the
    # insert below is rejected. This route uses `get_db` rather than `get_tenant_db`
    # because a webhook has no authenticated user to derive a tenant from; the tenant
    # comes from the integration the signature just proved. Same defect, and same
    # fix, as the background sync in erp_integrations.run_erp_sync.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(integration.organization_id)},
        )

    event_type = x_event_type or event_data.get("event_type")
    event_id = x_event_id or event_data.get("event_id")
    source_system = x_source_system or event_data.get("source_system") or erp_type
    entity_type = event_data.get("entity_type", "unknown")
    if not event_type or not event_id:
        raise HTTPException(status_code=400, detail="missing event_type or event_id")

    # Idempotent insert. Dedup is enforced by the UNIQUE(source_system,
    # event_id) constraint, not a check-then-insert: two concurrent deliveries
    # of the same event (providers retry aggressively) would both pass a
    # pre-check SELECT and then collide at INSERT. Let the constraint decide and
    # treat the conflict as the duplicate — race-safe, and one fewer query on the
    # common first-delivery path.
    db.add(ERPIntegrationEvent(
        organization_id=integration.organization_id,
        integration_id=integration.id,
        event_type=str(event_type),
        event_id=str(event_id),
        source_system=str(source_system),
        entity_type=str(entity_type),
        entity_id=event_data.get("entity_id"),
        event_data=event_data,
        processing_status="pending",
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.info("erp_webhook_duplicate", erp_type=erp_type, event_id=str(event_id))
        return {"status": "duplicate", "event_id": str(event_id)}
    logger.info("erp_webhook_received", erp_type=erp_type, event_type=event_type, event_id=event_id)
    return {"status": "accepted", "event_id": str(event_id)}
