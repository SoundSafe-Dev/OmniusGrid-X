"""`pending` must not be a dead end (FS-407).

`fan_out` queues a posting as `pending` whenever an integration claims the target system.
Nothing moved it. So an integrated target could never reach `posted`, an activation over one
could never be confirmed, and the ledger showed a queue that never emptied with no way to
tell "waiting" from "abandoned" — strictly worse than having no integration, because
`manual_required` at least tells somebody to pick up the phone.

WHAT THE DRAIN HONESTLY DOES. No connector in this repository has a verified write path, so
the realistic outcome for a real vendor is `ERPWriteNotSupported` and a conversion to
`manual_required` carrying the reason. These tests assert that conversion as the DESIGNED
behaviour, not as an error case — and separately assert that a connector which does write
produces `posted` with the far system's identifier, so the path is proven for the day one
gains a real write.

TWO OF THESE COME FROM DRIVING THE RUNNING APP. `test_a_broken_integration_does_not_stop_the
_queue` reproduces a 500 that took down an entire drain because the integration row was
missing `erp_type` — the fixtures all build valid configs, so no test could have seen it.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests._sqlite import create_all, sqlite_engine

from app.db.models import Base, IntegrationConfiguration, Organization
from app.db.shop_floor_models import (
    EventType, PostingStatus, SystemOfRecordPosting, TargetSystem,
)
from app.services.erp_connector_base import ERPWriteNotSupported
from app.services.posting_drainer import MAX_ATTEMPTS, drain

pytestmark = pytest.mark.asyncio

ORG_ID = "00000000-0000-0000-0000-000000000003"


@pytest_asyncio.fixture
async def session():
    # FK-enforcing; see tests/_sqlite.py.
    engine = sqlite_engine()
    await create_all(engine, Base.metadata, [
        Organization.__table__,
        IntegrationConfiguration.__table__,
        SystemOfRecordPosting.__table__,
    ])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add(Organization(id=ORG_ID, name="QA", slug="qa-drain"))
        await s.commit()
        yield s
    await engine.dispose()


async def _integration(session, **config) -> str:
    integration_id = str(uuid.uuid4())
    session.add(IntegrationConfiguration(
        id=integration_id, organization_id=ORG_ID, integration_type="erp",
        integration_name="Vendor", is_active=True,
        configuration={"serves_systems": [TargetSystem.INVENTORY], **config},
    ))
    await session.commit()
    return integration_id


async def _pending(session, integration_id: str | None, **kw) -> SystemOfRecordPosting:
    posting = SystemOfRecordPosting(
        id=str(uuid.uuid4()), organization_id=ORG_ID,
        event_type=EventType.PART_ISSUE, event_id=str(uuid.uuid4()),
        target_system=TargetSystem.INVENTORY, status=PostingStatus.PENDING,
        integration_id=integration_id, **{"attempts": 0, **kw},
    )
    session.add(posting)
    await session.commit()
    return posting


class _Connector:
    """Stands in for a vendor connector. `outcome` decides what post_event does."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[tuple] = []

    async def post_event(self, event_type, payload):
        self.calls.append((event_type, payload))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    async def close(self):
        pass


def _patch_connector(monkeypatch, connector):
    async def _fake(session, posting):
        return connector
    monkeypatch.setattr("app.services.posting_drainer._connector_for", _fake)


class TestAConnectorThatCanWrite:
    async def test_the_identifier_it_returns_becomes_the_evidence(self, session, monkeypatch):
        integration = await _integration(session)
        posting = await _pending(session, integration)
        _patch_connector(monkeypatch, _Connector("SAP-MATDOC-4471"))

        result = await drain(session, ORG_ID)
        await session.refresh(posting)

        assert result.posted == 1
        assert posting.status == PostingStatus.POSTED
        assert posting.external_ref == "SAP-MATDOC-4471"
        assert posting.posted_at is not None

    async def test_a_write_that_returns_nothing_is_not_treated_as_success(
        self, session, monkeypatch
    ):
        integration = await _integration(session)
        posting = await _pending(session, integration)
        _patch_connector(monkeypatch, _Connector(""))

        result = await drain(session, ORG_ID)
        await session.refresh(posting)

        assert result.posted == 0, (
            "a connector that wrote but returned no identifier has given us nothing to "
            "verify against — `posted` there is the exact unverifiable claim the ledger "
            "exists to prevent"
        )
        assert posting.status == PostingStatus.MANUAL_REQUIRED


class TestAConnectorThatCannotWrite:
    """The realistic case today, and it is a designed outcome rather than a failure."""

    async def test_it_is_handed_to_a_person_with_a_reason(self, session, monkeypatch):
        integration = await _integration(session)
        posting = await _pending(session, integration)
        _patch_connector(
            monkeypatch,
            _Connector(ERPWriteNotSupported("sap has no verified write path")),
        )

        result = await drain(session, ORG_ID)
        await session.refresh(posting)

        assert result.handed_to_a_person == 1
        assert posting.status == PostingStatus.MANUAL_REQUIRED
        assert "by hand" in posting.instruction
        assert "no verified write path" in posting.instruction, (
            "'the ERP cannot accept writes' and 'the ERP refused this one' send a "
            "supervisor to two different people"
        )

    async def test_it_does_not_stay_pending(self, session, monkeypatch):
        integration = await _integration(session)
        posting = await _pending(session, integration)
        _patch_connector(monkeypatch, _Connector(ERPWriteNotSupported("no write path")))

        await drain(session, ORG_ID)
        await session.refresh(posting)

        assert posting.status != PostingStatus.PENDING, (
            "leaving it pending implies a write is coming; nothing will ever take it"
        )


class TestFailuresAndBadConfiguration:
    async def test_a_transient_failure_is_retried_before_a_person_is_bothered(
        self, session, monkeypatch
    ):
        integration = await _integration(session)
        posting = await _pending(session, integration)
        _patch_connector(monkeypatch, _Connector(RuntimeError("connection reset")))

        result = await drain(session, ORG_ID)
        await session.refresh(posting)

        assert result.failed == 1
        assert posting.status == PostingStatus.FAILED
        assert "connection reset" in posting.last_error

    async def test_it_stops_retrying_and_hands_over_after_the_cap(self, session, monkeypatch):
        integration = await _integration(session)
        posting = await _pending(session, integration, attempts=MAX_ATTEMPTS - 1)
        _patch_connector(monkeypatch, _Connector(RuntimeError("still down")))

        result = await drain(session, ORG_ID)
        await session.refresh(posting)

        assert result.handed_to_a_person == 1
        assert posting.status == PostingStatus.MANUAL_REQUIRED, (
            "a queue that retries forever is indistinguishable from one that is stuck"
        )

    async def test_a_broken_integration_does_not_stop_the_queue(self, session):
        """REPRODUCES A 500 FOUND BY DRAINING A REAL LEDGER.

        An integration row without `erp_type` makes the connector factory raise KeyError
        while the connector is being BUILT — outside the try that wraps `post_event`. The
        exception escaped `drain`, returned a 500, and no posting in the batch was touched.
        """
        integration = await _integration(session)  # no erp_type in the configuration
        first = await _pending(session, integration)
        second = await _pending(session, integration)

        result = await drain(session, ORG_ID)
        await session.refresh(first)
        await session.refresh(second)

        assert result.considered == 2
        assert result.orphaned == 2
        for posting in (first, second):
            assert posting.status == PostingStatus.MANUAL_REQUIRED
            assert "not usable" in posting.instruction
            assert posting.last_error, "the operator needs to know WHY it could not be built"

    async def test_a_posting_whose_integration_was_deleted_is_handed_over(self, session):
        """The integration is DELETED, not faked with a dangling id.

        The first version of this test wrote a random uuid into `integration_id` and asserted
        the drainer coped. Switching foreign keys on for this file rejected the insert — and
        rightly: migration 060 declares `integration_id ... ON DELETE SET NULL`, so Postgres
        can never hold a dangling reference. The test was asserting an unreachable state, and
        passing only because SQLite does not enforce FKs by default.

        The reachable state is the one below: the integration goes away, the cascade nulls
        the column, and the posting is left queued for nobody.
        """
        integration = await _integration(session, erp_type="sap")
        posting = await _pending(session, integration)

        await session.execute(
            delete(IntegrationConfiguration).where(
                IntegrationConfiguration.id == integration
            )
        )
        await session.commit()
        await session.refresh(posting)
        assert posting.integration_id is None, (
            "ON DELETE SET NULL should have cleared the reference; if it did not, this test "
            "is no longer exercising what it claims to"
        )

        result = await drain(session, ORG_ID)
        await session.refresh(posting)

        assert result.orphaned == 1
        assert posting.status == PostingStatus.MANUAL_REQUIRED
        assert "gone or switched off" in posting.instruction

    async def test_a_deactivated_integration_is_handed_over(self, session):
        integration = await _integration(session, erp_type="sap")
        posting = await _pending(session, integration)
        row = (await session.execute(
            select(IntegrationConfiguration).where(
                IntegrationConfiguration.id == integration
            )
        )).scalars().first()
        row.is_active = False
        await session.commit()

        result = await drain(session, ORG_ID)
        await session.refresh(posting)

        assert result.orphaned == 1
        assert posting.status == PostingStatus.MANUAL_REQUIRED


class TestScope:
    async def test_it_only_touches_pending(self, session, monkeypatch):
        integration = await _integration(session)
        already = await _pending(session, integration)
        already.status = PostingStatus.MANUAL_REQUIRED
        already.instruction = "tell the stores clerk"
        await session.commit()
        _patch_connector(monkeypatch, _Connector("REF-1"))

        result = await drain(session, ORG_ID)
        await session.refresh(already)

        assert result.considered == 0
        assert already.instruction == "tell the stores clerk", (
            "re-draining must not overwrite an instruction a person is already working from"
        )

    async def test_it_does_not_reach_another_tenants_postings(self, session, monkeypatch):
        integration = await _integration(session)
        await _pending(session, integration)
        _patch_connector(monkeypatch, _Connector("REF-1"))

        result = await drain(session, "00000000-0000-0000-0000-0000000000ff")
        assert result.considered == 0
