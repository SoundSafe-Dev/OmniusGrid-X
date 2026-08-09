"""Idempotency guards for the ERP webhook receiver.

The DB has a UNIQUE(source_system, event_id) constraint (migration 020), but the
ORM model never declared it, so:
  * create_all (SQLite tests) built the table WITHOUT the constraint, and
  * the receiver relied on a check-then-insert (SELECT dup, then INSERT) — a
    TOCTOU race: two concurrent deliveries of the same event (webhook providers
    retry aggressively) both pass the SELECT, both INSERT, and against real
    Postgres the second hits the constraint -> 500 -> the provider retries
    harder.

The fix declares the constraint on the model (making it the real idempotency
guarantee, and letting SQLite enforce it in tests) and makes the receiver do an
idempotent insert that treats a conflict as a duplicate.
"""

import asyncio
from uuid import uuid4

import json
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests._sqlite import create_all, minimal_organization, sqlite_engine
from sqlalchemy.orm import sessionmaker

from app.api import erp_webhooks
from app.db.models import Base, ERPIntegrationEvent, IntegrationConfiguration


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


ORG = uuid4()
#: The integration events are attributed to. A module constant rather than an inline
#: `uuid4()` per row, because with foreign keys enforced an event must point at an
#: integration that exists — and the dedup guarantee under test is about the event's own
#: unique constraint, not about inventing a parent.
INTEGRATION = uuid4()
SECRET = "sek"


async def _factory():
    engine = sqlite_engine()
    # FK-enforcing engine, and a `create_all` that closes over the tables these
    # reference (FS-410). `create_all(tables=[X])` builds X's foreign keys pointing at
    # tables it does not create, so with enforcement on every insert into X is refused.
    await create_all(engine, Base.metadata, [IntegrationConfiguration.__table__, ERPIntegrationEvent.__table__])
    return engine, sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_integration(session):
    # See FS-410: the integration references an organisation, so the organisation has to
    # exist. It did not, and SQLite simply let the row through.
    session.add(minimal_organization(ORG))
    await session.flush()
    session.add(IntegrationConfiguration(
        id=INTEGRATION, organization_id=ORG, integration_type="erp", erp_type="sap",
        integration_name="SAP-test", configuration={"webhook_secret": SECRET},
        is_active=True,
    ))
    await session.commit()


def test_model_declares_unique_event_constraint():
    """The constraint must be on the model, or create_all omits it and the
    dedup guarantee silently evaporates in any SQLite-backed environment."""
    async def scenario():
        engine, Session = await _factory()
        async with Session() as s:
            # This test never seeded the organisation or the integration its events point
            # at. It passed because SQLite does not enforce foreign keys — the rows were
            # orphans, and the constraint under test is on the event, so the assertion held
            # anyway. On Postgres the first insert would have been refused (FS-410).
            await _seed_integration(s)
            row = dict(organization_id=ORG, integration_id=INTEGRATION,
                       event_type="po.created", source_system="sap",
                       entity_type="PurchaseOrder", event_data={})
            s.add(ERPIntegrationEvent(event_id="E1", **row))
            await s.commit()
            s.add(ERPIntegrationEvent(event_id="E1", **row))  # same (source, event_id)
            with pytest.raises(IntegrityError):
                await s.commit()
        await engine.dispose()

    run(scenario())


class _FakeRequest:
    """Minimal stand-in for Starlette's Request.

    The route now verifies the signature over `await request.body()` — the RAW bytes
    the vendor signed — rather than over a re-serialisation of the parsed payload, so
    a test must supply those bytes. `request=None` used to be enough precisely
    because the raw body was never consulted.
    """

    def __init__(self, raw: bytes, headers: dict | None = None):
        self._raw = raw
        # The route reads the credential out of the full header map now, because
        # which header carries it is per-vendor: Intuit uses `intuit-signature`,
        # Dataverse a static header of the operator's choosing.
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._raw

    @property
    def client(self):
        return None


def _call(session, event_id, event_data):
    # Bytes first, then the parsed form — the direction a real delivery travels.
    raw = json.dumps(event_data).encode()
    sig = erp_webhooks.compute_signature(SECRET, raw)
    return erp_webhooks.receive_erp_webhook(
        erp_type="sap", event_data=event_data,
        request=_FakeRequest(raw, {"x-webhook-signature": sig}),
        x_webhook_signature=sig, x_event_type="po.created",
        x_event_id=event_id, x_source_system="sap", db=session,
    )


def test_webhook_is_idempotent_and_never_500s_on_duplicate():
    async def scenario():
        engine, Session = await _factory()
        async with Session() as s:
            await _seed_integration(s)
        async with Session() as s:
            first = await _call(s, "E1", {"entity_type": "PurchaseOrder", "entity_id": "1"})
        async with Session() as s:
            second = await _call(s, "E1", {"entity_type": "PurchaseOrder", "entity_id": "1"})
        async with Session() as s:
            from sqlalchemy import func, select
            count = (await s.execute(
                select(func.count()).select_from(ERPIntegrationEvent)
            )).scalar()
        await engine.dispose()
        return first, second, count

    first, second, count = run(scenario())
    assert first["status"] == "accepted", first
    assert second["status"] == "duplicate", second
    assert count == 1, f"duplicate delivery must not create a second row, got {count}"
