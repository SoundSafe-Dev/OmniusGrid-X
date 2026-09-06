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
from typing import Any, Dict, List, Optional, Tuple

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


def _intuit_cloudevent(body: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Intuit's CloudEvents shape, mandatory from 2026-05-15.

    A CloudEvent carries `specversion`, `type`, `id` and `source` at the top level, so it
    is distinguishable from the legacy envelope without guessing. One CloudEvent describes
    one change, so this returns a single-element list -- the same contract as the legacy
    adapter, so the receiver has one code path rather than two.
    """
    if not body.get("specversion") or not body.get("type"):
        return None
    data = body.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    return [{
        # The vendor supplies a real event id here, so no derivation is needed.
        "event_id": body.get("id") or _stable_event_id(body.get("type"), body.get("time")),
        "event_type": body.get("type"),
        "entity_type": data.get("name") or data.get("entityName") or "unknown",
        "entity_id": data.get("id") or data.get("entityId"),
        "realm_id": data.get("realmId"),
    }]


def _intuit_legacy(body: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Intuit's current `eventNotifications` envelope — EVERY entity, not just the first.

    ONE DELIVERY CARRIES MANY CHANGES. QuickBooks batches: a single POST can hold several
    notifications (one per realm) and each holds a list of entities. The first version of
    this adapter returned only `entities[0]` of `eventNotifications[0]`, which accepted the
    delivery, answered 200, and silently dropped every other change in it. That is a worse
    failure than the 400 it replaced -- a rejection is at least visible to the sender,
    while a partial accept tells Intuit the whole batch was handled.

    Each entity becomes its own event, so the receiver's per-event dedup applies per
    change rather than per delivery.
    """
    notifications = body.get("eventNotifications")
    if not isinstance(notifications, list) or not notifications:
        return None

    events: List[Dict[str, Any]] = []
    for notification in notifications:
        if not isinstance(notification, dict):
            continue
        realm = notification.get("realmId")
        entities = ((notification.get("dataChangeEvent") or {}).get("entities")) or []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = entity.get("name") or "unknown"
            operation = entity.get("operation") or "Change"
            events.append({
                # Intuit sends no event id. Derived from realm, entity and the vendor's
                # own lastUpdated so a retry of the SAME change dedups while a genuinely
                # new change does not.
                "event_id": _stable_event_id(
                    realm, name, entity.get("id"), operation, entity.get("lastUpdated")
                ),
                "event_type": f"{name}.{operation}".lower(),
                "entity_type": name,
                "entity_id": entity.get("id"),
                "realm_id": realm,
            })
    return events or None


#: Vendors whose webhook body needs translating into the receiver's envelope. A vendor
#: absent from here is one whose sending side the operator configures (SAP Event Mesh, a
#: NetSuite user-event script), where emitting the envelope directly is reasonable.
_ADAPTERS = {
    "intuit": (_intuit_cloudevent, _intuit_legacy),
}


def normalise(erp_type: str, body: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Return (events, format_name) for a vendor body, or ([], None) if none applies.

    A LIST because one delivery is not one event. QuickBooks batches several changes into
    a single POST; returning the first and discarding the rest would answer 200 for work
    that was never recorded.

    Never raises: a body matching no known shape falls through to the receiver's existing
    generic handling, which fails with its own clear message. An adapter that threw here
    would turn "this vendor sends a shape we do not know" into a 500.
    """
    adapters = _ADAPTERS.get((erp_type or "").lower())
    if not adapters or not isinstance(body, dict):
        return [], None
    for adapter in adapters:
        try:
            events = adapter(body)
        except Exception as exc:  # noqa: BLE001 - a malformed body is the sender's, not ours
            logger.warning(
                "erp_webhook_payload_adapter_failed",
                erp_type=erp_type,
                adapter=adapter.__name__,
                error=str(exc),
            )
            continue
        if events:
            return events, adapter.__name__
    return [], None
