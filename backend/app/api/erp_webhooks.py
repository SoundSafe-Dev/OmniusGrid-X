"""ERP inbound webhook receiver route (Phase A, task 4).

Accepts real-time events pushed by ERP systems, authenticates them (HMAC over
the payload using the integration's stored `webhook_secret` — same scheme as
`ERPWebhookReceiver._validate_signature`), deduplicates by (source_system,
event_id), and stores them as `ERPIntegrationEvent` rows for downstream
processing/correlation. Kept in its own router (prefix `/api/v1/erp/webhooks`)
so it doesn't touch the integrations CRUD router.
"""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import ERPIntegrationEvent, IntegrationConfiguration

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/erp/webhooks", tags=["Edge"])


def compute_signature(secret: str, event_data: Dict[str, Any]) -> str:
    """HMAC-SHA256 over the canonical JSON payload (matches ERPWebhookReceiver)."""
    payload = json.dumps(event_data, sort_keys=True)
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_signature(secret: Optional[str], event_data: Dict[str, Any], signature: Optional[str]) -> bool:
    """True only when a secret is configured and the signature matches.

    Fails closed on a missing secret. This used to return True when no secret was
    configured, so any integration row with an absent or empty
    `configuration.webhook_secret` accepted unsigned webhooks and wrote ERP
    events from them. That is also the control test_route_auth_walk.py cites when
    it exempts this route from the authentication walk, so the exemption was
    unearned. Matches the fail-closed posture of edge_enroll.py.
    """
    if not secret or not signature:
        return False
    return hmac.compare_digest(compute_signature(secret, event_data), signature)


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
    # Resolve the active ERP integration for this erp_type.
    integration = (
        await db.execute(
            select(IntegrationConfiguration).where(
                IntegrationConfiguration.integration_type == "erp",
                IntegrationConfiguration.erp_type == erp_type,
                IntegrationConfiguration.is_active == True,  # noqa: E712
            )
        )
    ).scalars().first()
    if integration is None:
        raise HTTPException(status_code=404, detail=f"no active ERP integration for '{erp_type}'")

    secret = (integration.configuration or {}).get("webhook_secret")
    if not verify_signature(secret, event_data, x_webhook_signature):
        # Log why server-side; the response stays generic so an unauthenticated
        # caller can't probe whether an integration has a secret configured.
        logger.warning(
            "erp_webhook_signature_rejected",
            erp_type=erp_type,
            integration_id=str(integration.id),
            has_secret=bool(secret),
            has_signature=bool(x_webhook_signature),
        )
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    event_type = x_event_type or event_data.get("event_type")
    event_id = x_event_id or event_data.get("event_id")
    source_system = x_source_system or event_data.get("source_system") or erp_type
    entity_type = event_data.get("entity_type", "unknown")
    if not event_type or not event_id:
        raise HTTPException(status_code=400, detail="missing event_type or event_id")

    # Dedup by (source_system, event_id).
    dup = (
        await db.execute(
            select(ERPIntegrationEvent).where(
                ERPIntegrationEvent.source_system == source_system,
                ERPIntegrationEvent.event_id == str(event_id),
            )
        )
    ).scalars().first()
    if dup is not None:
        return {"status": "duplicate", "event_id": str(event_id)}

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
    await db.commit()
    logger.info("erp_webhook_received", erp_type=erp_type, event_type=event_type, event_id=event_id)
    return {"status": "accepted", "event_id": str(event_id)}
