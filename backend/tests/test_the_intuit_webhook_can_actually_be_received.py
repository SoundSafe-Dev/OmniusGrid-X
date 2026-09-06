"""A correctly-signed QuickBooks webhook was authenticated and then rejected (FS-996).

`erp_webhook_auth.py` does careful vendor-specific work for Intuit — base64 HMAC-SHA256
over the raw body in `intuit-signature`, marked "Verified", with a docstring telling an
operator they "should need to supply the verifier token and nothing else". The route then
asked the parsed body for `event_type` and `event_id`, which Intuit has never sent, and
answered:

    HTTP 400 — missing event_type or event_id

So the signature verified and the delivery was refused anyway. **QuickBooks webhooks had
never once been accepted**, and the failure presented as a client error rather than as the
missing adapter it was — the same shape as the Grafana datasource in FS-978 and the
Alertmanager config in FS-787: configured with real care at one layer, non-functional at
the next, and nothing comparing the two.

WHAT THIS FILE PINS. Not the adapter's internals — the end-to-end property: a delivery
shaped the way Intuit actually shapes one, signed the way Intuit actually signs one, is
accepted; a retry of it dedups; a different change does not.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from tests._sqlite import sqlite_engine, create_all, minimal_organization
from app.db.models import Base, IntegrationConfiguration, ERPIntegrationEvent
from app.api import erp_webhooks

ORG = uuid4()
INTEGRATION = uuid4()
SECRET = "verifier-token"

#: The shape Intuit's Accounting API posts today.
INTUIT_LEGACY = {
    "eventNotifications": [{
        "realmId": "1234567890",
        "dataChangeEvent": {"entities": [{
            "name": "Invoice", "id": "42", "operation": "Create",
            "lastUpdated": "2026-09-05T12:00:00-0700",
        }]},
    }]
}

#: The CloudEvents shape Intuit requires from 2026-05-15. Handled now so the migration is
#: absorbed rather than becoming a second deadline the moment the first fix works.
INTUIT_CLOUDEVENT = {
    "specversion": "1.0",
    "type": "com.intuit.quickbooks.accounting.Invoice.Create",
    "id": "evt-abc-123",
    "source": "/quickbooks/company/1234567890",
    "time": "2026-09-05T19:00:00Z",
    "data": {"name": "Invoice", "id": "42"},
}


class _Req:
    def __init__(self, raw: bytes, headers: dict):
        self._raw, self.headers = raw, headers

    async def body(self) -> bytes:
        return self._raw

    @property
    def client(self):
        return None


def _sign(raw: bytes) -> str:
    """Intuit's real scheme: base64 HMAC-SHA256 over the raw body."""
    return base64.b64encode(hmac.new(SECRET.encode(), raw, hashlib.sha256).digest()).decode()


async def _session_factory():
    engine = sqlite_engine()
    await create_all(
        engine, Base.metadata,
        [IntegrationConfiguration.__table__, ERPIntegrationEvent.__table__],
    )
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        s.add(minimal_organization(ORG))
        await s.flush()
        s.add(IntegrationConfiguration(
            id=INTEGRATION, organization_id=ORG, integration_type="erp",
            erp_type="intuit", integration_name="QBO", is_active=True,
            configuration={"webhook_secret": SECRET},
        ))
        await s.commit()
    return Session


async def _deliver(Session, body: dict):
    raw = json.dumps(body).encode()
    async with Session() as s:
        return await erp_webhooks.receive_erp_webhook(
            erp_type="intuit", event_data=body,
            request=_Req(raw, {"intuit-signature": _sign(raw)}),
            x_webhook_signature=None, x_event_type=None,
            x_event_id=None, x_source_system=None, db=s,
        )


class TestTheCurrentIntuitFormat:
    async def test_a_real_signed_delivery_is_accepted(self):
        Session = await _session_factory()
        result = await _deliver(Session, INTUIT_LEGACY)
        assert result["status"] == "accepted", (
            f"a correctly-signed Intuit delivery was not accepted: {result}. Before "
            "FS-996 this raised HTTP 400 'missing event_type or event_id' — the "
            "signature verified and the payload was refused for lacking fields Intuit "
            "does not send."
        )

    async def test_the_entity_is_recorded_not_just_the_envelope(self):
        """Accepting the delivery is not enough if everything identifying it is dropped."""
        Session = await _session_factory()
        await _deliver(Session, INTUIT_LEGACY)
        async with Session() as s:
            from sqlalchemy import select
            row = (await s.execute(select(ERPIntegrationEvent))).scalars().one()
        assert row.entity_type == "Invoice"
        assert row.entity_id == "42"
        assert row.event_type == "invoice.create"

    async def test_a_retry_of_the_same_change_dedups(self):
        """Intuit sends no event id and retries aggressively, so the id is derived from
        the realm, entity and the vendor's own lastUpdated. A random id would have
        defeated the receiver's UNIQUE(source_system, event_id) constraint silently."""
        Session = await _session_factory()
        first = await _deliver(Session, INTUIT_LEGACY)
        second = await _deliver(Session, INTUIT_LEGACY)
        assert first["status"] == "accepted"
        assert second["status"] == "duplicate"
        assert first["event_id"] == second["event_id"]

    async def test_a_different_change_is_not_treated_as_a_duplicate(self):
        """The other direction — dedup that swallows real events is worse than none."""
        Session = await _session_factory()
        other = json.loads(json.dumps(INTUIT_LEGACY))
        other["eventNotifications"][0]["dataChangeEvent"]["entities"][0]["id"] = "99"
        first = await _deliver(Session, INTUIT_LEGACY)
        second = await _deliver(Session, other)
        assert second["status"] == "accepted"
        assert first["event_id"] != second["event_id"]


class TestTheCloudEventsFormatIntuitRequiresFrom2026:
    async def test_a_cloudevents_delivery_is_accepted(self):
        Session = await _session_factory()
        result = await _deliver(Session, INTUIT_CLOUDEVENT)
        assert result["status"] == "accepted"

    async def test_it_uses_the_vendors_own_event_id(self):
        """CloudEvents carries a real `id`, so nothing needs deriving — and using it means
        Intuit's own retry semantics drive the dedup rather than our reconstruction."""
        Session = await _session_factory()
        result = await _deliver(Session, INTUIT_CLOUDEVENT)
        assert result["event_id"] == "evt-abc-123"


class TestNothingElseChanged:
    async def test_an_unrecognised_body_still_fails_with_the_original_message(self):
        """The adapter must not turn 'this vendor sends a shape we do not know' into a
        500, or a misconfiguration becomes indistinguishable from an outage."""
        Session = await _session_factory()
        with pytest.raises(HTTPException) as exc:
            await _deliver(Session, {"something": "unrecognised"})
        assert exc.value.status_code == 400
        assert "event_type" in str(exc.value.detail)
