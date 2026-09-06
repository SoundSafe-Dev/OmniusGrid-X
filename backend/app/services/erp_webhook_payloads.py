"""Normalise a vendor's webhook body into the fields the receiver stores (FS-996).

THE RECEIVER COULD AUTHENTICATE INTUIT AND THEN COULD NOT READ IT. `erp_webhook_auth.py`
does careful, vendor-specific work to verify an Intuit delivery -- base64 HMAC-SHA256 over
the raw body in `intuit-signature`, marked "Verified" -- and an operator wiring up
QuickBooks is told they "should need to supply the verifier token and nothing else". Then
the route asked the parsed body for `event_type` and `event_id`, which Intuit has never
sent, and returned::

    HTTP 400 -- missing event_type or event_id

Reproduced end to end against a correctly-signed real-shaped delivery: the signature
verifies, and the request is rejected anyway. So QuickBooks webhooks have never once been
accepted, and the failure looked like a client error rather than a missing adapter.

The generic shape the route wants (`event_type`, `event_id`, `entity_type`, `entity_id`)
is a fine internal contract. What was missing is that no vendor speaks it: it is
OmniusGrid's own envelope, and every real sender needs translating into it. SAP-style
senders happen to satisfy it because the operator configures the sending side; Intuit is a
SaaS product that sends what it sends.

TWO INTUIT FORMATS, ON PURPOSE. Intuit is migrating webhook payloads to **CloudEvents by
2026-05-15**, so a receiver written today against only the current shape acquires a second
deadline the moment it works. Both are handled, the new one first, so the migration is
absorbed rather than scheduled.

IDEMPOTENCY IS THE POINT OF `event_id`. Intuit retries aggressively and sends no event
identifier of its own, so one is derived deterministically from the realm, the entity and
the vendor's own `lastUpdated` stamp. Two deliveries of the same change therefore collide
on the receiver's `UNIQUE(source_system, event_id)` constraint and the second is recorded
as a duplicate -- which is the behaviour the constraint already exists to provide, and
which a random id would have silently defeated.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional, Tuple

import structlog

logger = structlog.get_logger()


def _stable_event_id(*parts: Any) -> str:
    """A deterministic id for a vendor that sends none.

    Hashed rather than concatenated so the value is a bounded, uniform token regardless of
    how long an entity name or timestamp is, and so a delimiter appearing inside a part
    cannot make two different events collide.
    """
    joined = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()[:48]


def _intuit_cloudevent(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Intuit's CloudEvents shape, mandatory from 2026-05-15.

    A CloudEvent carries `specversion`, `type`, `id` and `source` at the top level, so it
    is distinguishable from the legacy envelope without guessing.
    """
    if not body.get("specversion") or not body.get("type"):
        return None
    data = body.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    return {
        # The vendor supplies a real event id here, so no derivation is needed.
        "event_id": body.get("id") or _stable_event_id(body.get("type"), body.get("time")),
        "event_type": body.get("type"),
        "entity_type": data.get("name") or data.get("entityName") or "unknown",
        "entity_id": data.get("id") or data.get("entityId"),
    }


def _intuit_legacy(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Intuit's current `eventNotifications` envelope.

    ONE DELIVERY CAN CARRY MANY ENTITIES, and the receiver stores one row per call. The
    first entity identifies the event; the whole body is stored alongside it, so nothing
    is lost and a consumer that needs the rest reads `event_data`. Splitting one delivery
    into N rows would need the receiver to return N ids and would break its own
    accepted/duplicate contract -- a larger change than this defect warrants, and recorded
    here rather than done silently.
    """
    notifications = body.get("eventNotifications")
    if not isinstance(notifications, list) or not notifications:
        return None
    first = notifications[0] or {}
    realm = first.get("realmId")
    entities = ((first.get("dataChangeEvent") or {}).get("entities")) or []
    entity = entities[0] if entities else {}

    name = entity.get("name") or "unknown"
    operation = entity.get("operation") or "Change"
    return {
        # Intuit sends no event id. Derived from the realm, entity and the vendor's own
        # lastUpdated so a retry of the SAME change dedups and a genuinely new change
        # does not.
        "event_id": _stable_event_id(
            realm, name, entity.get("id"), operation, entity.get("lastUpdated")
        ),
        "event_type": f"{name}.{operation}".lower(),
        "entity_type": name,
        "entity_id": entity.get("id"),
    }


#: Vendors whose webhook body needs translating into the receiver's envelope. A vendor
#: absent from here is one whose sending side the operator configures (SAP Event Mesh, a
#: NetSuite user-event script), where emitting the envelope directly is reasonable.
_ADAPTERS = {
    "intuit": (_intuit_cloudevent, _intuit_legacy),
}


def normalise(erp_type: str, body: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return (fields, format_name) for a vendor body, or ({}, None) if none applies.

    Never raises: a body that does not match any known shape falls through to the
    receiver's existing generic handling, which fails with its own clear message. An
    adapter that threw here would turn "this vendor sends a shape we do not know" into a
    500, which is a worse answer to the same question.
    """
    adapters = _ADAPTERS.get((erp_type or "").lower())
    if not adapters or not isinstance(body, dict):
        return {}, None
    for adapter in adapters:
        try:
            fields = adapter(body)
        except Exception as exc:  # noqa: BLE001 - a malformed body is the sender's, not ours
            logger.warning(
                "erp_webhook_payload_adapter_failed",
                erp_type=erp_type,
                adapter=adapter.__name__,
                error=str(exc),
            )
            continue
        if fields:
            return fields, adapter.__name__
    return {}, None
