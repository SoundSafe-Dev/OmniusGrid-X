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
import json
import os
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import ERPIntegrationEvent, IntegrationConfiguration
from app.services.erp_webhook_auth import authenticate_webhook
from app.services.erp_webhook_payloads import normalise as normalise_webhook_payload

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


def _accept_legacy_signature() -> bool:
    """Is the deprecated canonical-JSON signature still accepted?

    Off unless ERP_WEBHOOK_ACCEPT_LEGACY_SIGNATURE is explicitly truthy. Read per
    request rather than cached at import so it can be turned off without a restart --
    the point of a transition switch is being able to close it promptly.
    """
    return os.environ.get("ERP_WEBHOOK_ACCEPT_LEGACY_SIGNATURE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _verify_legacy_canonical(
    secret: Optional[str], raw_body: Optional[bytes], signature: Optional[str]
) -> bool:
    """The pre-fix scheme: HMAC over `json.dumps(parsed, sort_keys=True)`.

    Retained ONLY so an in-flight deployment keeps working during an upgrade. It is
    not a security equivalent: because it hashes a canonical form, a body with
    reordered keys or different whitespace verifies against the same signature, so the
    signature does not bind the bytes received.
    """
    if not secret or not signature or raw_body is None:
        return False
    try:
        canonical = json.dumps(json.loads(raw_body), sort_keys=True).encode()
    except (ValueError, TypeError):
        return False
    expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


class ERPWebhookAck(BaseModel):
    """`accepted` or `duplicate` — the vendor needs to be able to tell a first delivery
    from a redelivery it should stop retrying, and both are 200."""

    status: str
    event_id: str


@router.post("/{erp_type}", response_model=ERPWebhookAck)
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
    # THE LOOKUP NEEDS ITS OWN PERMISSION, and this is where it comes from.
    #
    # integration_configurations is FORCE ROW LEVEL SECURITY keyed on
    # app.current_org_id, and at this point no tenant is known -- that is the whole
    # problem this query exists to solve. With no GUC the policy matched nothing, so
    # `candidates` was always empty and EVERY inbound webhook was rejected 404 with
    # "no active ERP integration". Verified against a real database.
    #
    # Migration 052 adds a second, deliberately narrow policy:
    # `webhook_tenant_resolution` permits SELECT of active ERP rows only while
    # app.erp_webhook_lookup = 'on'. It is set transaction-locally here and cleared
    # immediately after the query, so it is already off for the event INSERT below
    # and for every other path in the process.
    _is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"
    if _is_postgres:
        await db.execute(
            text("SELECT set_config('app.erp_webhook_lookup', 'on', true)")
        )
    try:
        candidates = (
            await db.execute(
                select(IntegrationConfiguration).where(
                    IntegrationConfiguration.integration_type == "erp",
                    IntegrationConfiguration.erp_type == erp_type,
                    IntegrationConfiguration.is_active == True,  # noqa: E712
                )
            )
        ).scalars().all()
    finally:
        # Cleared in a finally so an exception mid-lookup cannot leave the widened
        # policy live for the rest of the transaction.
        if _is_postgres:
            await db.execute(
                text("SELECT set_config('app.erp_webhook_lookup', '', true)")
            )

    if not candidates:
        raise HTTPException(status_code=404, detail=f"no active ERP integration for '{erp_type}'")

    integration = None
    rejection_reasons = []
    for candidate in candidates:
        # Vendor-aware: which header carries the credential, and which scheme it uses,
        # are per-integration configuration with per-vendor defaults. Intuit signs
        # base64 into `intuit-signature`; Dataverse sends a static header and no HMAC
        # at all. See app/services/erp_webhook_auth.py.
        ok, reason = authenticate_webhook(
            erp_type=candidate.erp_type,
            configuration=candidate.configuration,
            raw_body=raw_body,
            headers=request.headers,
        )
        if ok:
            integration = candidate
            break
        rejection_reasons.append(reason)

        if _accept_legacy_signature():
            # TRANSITION ONLY, off by default, and loud every single time.
            #
            # The pre-fix scheme hashed a key-sorted re-serialisation of the parsed
            # payload. It cannot authenticate any real vendor, so the only senders it
            # ever had were internal. This exists purely so an already-running
            # deployment is not bricked by the upgrade, and it is deliberately noisy
            # rather than silent: a quiet compatibility shim becomes permanent.
            if _verify_legacy_canonical(
                (candidate.configuration or {}).get("webhook_secret"),
                raw_body,
                request.headers.get("x-webhook-signature"),
            ):
                logger.warning(
                    "erp_webhook_accepted_via_legacy_signature",
                    erp_type=erp_type,
                    integration_id=str(candidate.id),
                    detail=(
                        "authenticated with the DEPRECATED canonical-JSON signature. "
                        "The sender must switch to HMAC over the raw request body; no "
                        "real ERP vendor can produce the legacy form. Unset "
                        "ERP_WEBHOOK_ACCEPT_LEGACY_SIGNATURE once senders are updated."
                    ),
                )
                integration = candidate
                break

    if integration is None:
        # Logged server-side; the response stays generic so an unauthenticated caller
        # cannot probe how many integrations exist or whether any has a secret.
        # Reasons are logged server-side only. Returning them would let an
        # unauthenticated caller discover whether an integration exists, which auth
        # mode it uses and whether a secret is configured.
        logger.warning(
            "erp_webhook_signature_rejected",
            erp_type=erp_type,
            candidates=len(candidates),
            reasons=rejection_reasons,
        )
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    # THE TENANT GUC. erp_integration_events is RLS-protected with a FOR ALL USING
    # policy, which Postgres also applies as the INSERT check -- so with no GUC the
    # insert below is rejected. This route uses `get_db` rather than `get_tenant_db`
    # because a webhook has no authenticated user to derive a tenant from; the tenant
    # comes from the integration the signature just proved. Same defect, and same
    # fix, as the background sync in erp_integrations.run_erp_sync.
    if _is_postgres:
        await db.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(integration.organization_id)},
        )

    # VENDOR SHAPE FIRST, THEN THE GENERIC ENVELOPE (FS-996). `event_type`/`event_id` is
    # OmniusGrid's own envelope; no SaaS vendor sends it. Intuit authenticated fine here
    # and was then rejected 400 for lacking fields it has never sent, so QuickBooks
    # webhooks had never once been accepted. Explicit headers still win over everything —
    # an operator who configures the sending side keeps full control.
    #
    # A LIST, because one delivery is not one event: QuickBooks batches several changes
    # (across several realms) into a single POST. Recording only the first would answer
    # 200 for work never stored, which is worse than the 400 it replaced — a rejection is
    # at least visible to the sender.
    vendor_events, vendor_format = normalise_webhook_payload(erp_type, event_data)
    if vendor_events:
        logger.info(
            "erp_webhook_payload_normalised",
            erp_type=erp_type,
            payload_format=vendor_format,
            event_count=len(vendor_events),
        )

    # The generic envelope is one event; a vendor body may be many. Both become a list so
    # there is a single insertion path rather than two that can drift.
    if vendor_events and not (x_event_id or event_data.get("event_id")):
        candidates = vendor_events
    else:
        candidates = [{
            "event_type": x_event_type or event_data.get("event_type"),
            "event_id": x_event_id or event_data.get("event_id"),
            "entity_type": event_data.get("entity_type"),
            "entity_id": event_data.get("entity_id"),
        }]

    source_system = x_source_system or event_data.get("source_system") or erp_type

    resolved = []
    for candidate in candidates:
        event_type = x_event_type or candidate.get("event_type")
        event_id = x_event_id or candidate.get("event_id")
        if not event_type or not event_id:
            raise HTTPException(status_code=400, detail="missing event_type or event_id")
        resolved.append((
            str(event_type),
            str(event_id),
            str(candidate.get("entity_type") or "unknown"),
            candidate.get("entity_id"),
        ))

    # PER-EVENT DEDUP, VIA SAVEPOINTS. Dedup is enforced by the UNIQUE(source_system,
    # event_id) constraint rather than a check-then-insert: two concurrent deliveries of
    # the same event (providers retry aggressively) would both pass a pre-check SELECT and
    # then collide at INSERT. With several events in one delivery that has to be per row —
    # a single IntegrityError on the shared transaction would roll back the entities that
    # were new, so a batch containing one already-seen change would discard all the others.
    accepted, duplicates = [], []
    for event_type, event_id, entity_type, entity_id in resolved:
        try:
            async with db.begin_nested():
                db.add(ERPIntegrationEvent(
                    organization_id=integration.organization_id,
                    integration_id=integration.id,
                    event_type=event_type,
                    event_id=event_id,
                    source_system=str(source_system),
                    entity_type=entity_type,
                    entity_id=entity_id,
                    event_data=event_data,
                    processing_status="pending",
                ))
        except IntegrityError:
            duplicates.append(event_id)
            continue
        accepted.append(event_id)

    await db.commit()

    if not accepted:
        logger.info("erp_webhook_duplicate", erp_type=erp_type, event_id=duplicates[0])
        return {"status": "duplicate", "event_id": duplicates[0]}

    # SINGLE-EVENT SHAPE IS UNCHANGED, deliberately: every existing caller and test sees
    # exactly the response it saw before. The batch fields appear only when there is
    # genuinely a batch, so a vendor that sends one event at a time is unaffected.
    response = {"status": "accepted", "event_id": accepted[0]}
    if len(resolved) > 1:
        response.update(
            accepted=len(accepted), duplicate=len(duplicates), event_ids=accepted
        )
    event_type, event_id = resolved[0][0], accepted[0]
    logger.info(
        "erp_webhook_received",
        erp_type=erp_type,
        event_type=event_type,
        event_id=event_id,
        accepted=len(accepted),
        duplicates=len(duplicates),
    )
    return response
