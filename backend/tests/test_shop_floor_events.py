"""The four floor events reach the systems that need them — and say so honestly (FS-405).

    a part is issued        -> inventory, purchasing, accounting
    time is clocked         -> production, accounting
    a problem is found      -> quality, inventory, production, accounting
    a machine goes down     -> scheduling, production, quality, accounting

WHAT THESE ASSERT THAT A NAIVE TEST WOULD NOT. Not "the endpoint returned 201" — that is
satisfied by a handler which records the event and tells nobody. Each case checks the
LEDGER: one row per target, with the status that target actually earned.

THE MANUAL PATH IS TESTED AS A FEATURE, not an error case. An organisation with no
purchasing integration must get a `manual_required` posting carrying a sentence a
supervisor can read to a stores clerk — the analog step this platform is expected to
support. A test suite that only covered the integrated path would let "silently dropped"
and "handed to a human" look identical, which is the whole thing the ledger exists to
separate.
"""

from __future__ import annotations

import uuid
from datetime import timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests._sqlite import create_all, sqlite_engine

from app.db.models import (
    Asset, AssetType, Base, IntegrationConfiguration, Organization, User, Workcell,
)
from app.db.shop_floor_models import (
    EventType, PostingStatus, SystemOfRecordPosting, TargetSystem,
)

pytestmark = pytest.mark.asyncio

ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _tables():
    from app.db.shop_floor_models import (
        DowntimeEvent, LaborEntry, PartIssue, QualityEvent,
    )
    return [
        Organization.__table__, Workcell.__table__, AssetType.__table__,
        Asset.__table__, User.__table__, IntegrationConfiguration.__table__,
        PartIssue.__table__, LaborEntry.__table__, QualityEvent.__table__,
        DowntimeEvent.__table__, SystemOfRecordPosting.__table__,
    ]


async def _build(serves: dict[str, list[str]] | None = None):
    """A stack with `serves` describing which integrations claim which target systems."""
    # FK-enforcing; see tests/_sqlite.py.
    engine = sqlite_engine()
    await create_all(engine, Base.metadata, _tables())
    maker = async_sessionmaker(engine, expire_on_commit=False)

    asset_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    async with maker() as session:
        wc, at = str(uuid.uuid4()), str(uuid.uuid4())
        session.add(Organization(id=str(ORG_ID), name="QA Org", slug="qa-org"))
        session.add(Workcell(id=wc, organization_id=str(ORG_ID), name="Cell"))
        session.add(AssetType(id=at, name="Mill", category="machine"))
        session.add(Asset(id=asset_id, organization_id=str(ORG_ID), workcell_id=wc,
                          asset_type_id=at, name="CNC Mill #1"))
        session.add(User(id=user_id, organization_id=str(ORG_ID), email="op@test.local",
                         hashed_password="x" * 60, role="admin", is_active=True))
        for name, targets in (serves or {}).items():
            session.add(IntegrationConfiguration(
                id=str(uuid.uuid4()), organization_id=str(ORG_ID),
                integration_type="erp", integration_name=name, is_active=True,
                configuration={"serves_systems": targets},
            ))
        await session.commit()
    return engine, maker, asset_id, user_id


@pytest_asyncio.fixture
async def stack():
    """No integrations at all — the shop whose purchasing runs on a phone call."""
    engine, maker, asset_id, user_id = await _build()
    async for client in _client(maker, user_id):
        client.asset_id = asset_id      # type: ignore[attr-defined]
        client.maker = maker            # type: ignore[attr-defined]
        yield client
    await engine.dispose()


@pytest_asyncio.fixture
async def integrated_stack():
    """An ERP that claims inventory, accounting and production — but not purchasing."""
    engine, maker, asset_id, user_id = await _build(
        {"SAP": [TargetSystem.INVENTORY, TargetSystem.ACCOUNTING, TargetSystem.PRODUCTION]}
    )
    async for client in _client(maker, user_id):
        client.asset_id = asset_id      # type: ignore[attr-defined]
        client.maker = maker            # type: ignore[attr-defined]
        yield client
    await engine.dispose()


async def _client(maker, user_id):
    from app.api.auth import get_current_active_user
    from app.core.tenant import get_tenant_db, get_tenant_org_id
    from app.db.database import get_db
    from app.main import app as fastapi_app

    async def _session():
        async with maker() as session:
            yield session

    class _User:
        id = user_id
        organization_id = ORG_ID
        role = "admin"
        email = "op@test.local"
        is_active = True

    overrides = dict(fastapi_app.dependency_overrides)
    fastapi_app.dependency_overrides[get_db] = _session
    fastapi_app.dependency_overrides[get_tenant_db] = _session
    fastapi_app.dependency_overrides[get_tenant_org_id] = lambda: ORG_ID
    fastapi_app.dependency_overrides[get_current_active_user] = lambda: _User()
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as client:
        yield client
    fastapi_app.dependency_overrides = overrides


async def _postings(client, event_type, event_id):
    async with client.maker() as session:
        rows = (await session.execute(
            select(SystemOfRecordPosting).where(
                SystemOfRecordPosting.event_type == event_type,
                SystemOfRecordPosting.event_id == event_id,
            )
        )).scalars().all()
    return {p.target_system: p for p in rows}


class TestIssuingAPartReachesThreeSystems:
    async def test_it_creates_one_posting_per_target(self, stack):
        response = await stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "BRG-6204", "quantity": 4, "unit_cost": 12.50, "currency": "USD",
            "work_order_ref": "WO-1001",
        })
        assert response.status_code == 201, response.text
        body = response.json()

        postings = await _postings(stack, EventType.PART_ISSUE, body["id"])
        assert set(postings) == {
            TargetSystem.INVENTORY, TargetSystem.PURCHASING, TargetSystem.ACCOUNTING
        }, sorted(postings)

    async def test_the_extended_cost_is_computed(self, stack):
        body = (await stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "BRG-6204", "quantity": 4, "unit_cost": 12.50,
        })).json()
        assert body["extended_cost"] == 50.0

    async def test_an_unpriced_issue_reports_null_not_zero(self, stack):
        """A zero in an accounting feed is a claim that the issue cost nothing. Absence of
        a price is a different statement and has to survive to the response."""
        body = (await stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "CONSUMABLE-1", "quantity": 2,
        })).json()
        assert body["unit_cost"] is None
        assert body["extended_cost"] is None


class TestTheResponseDoesNotOverclaim:
    async def test_with_no_integrations_nothing_is_posted(self, stack):
        """THE CENTRAL ASSERTION. A 201 must not read as "it reached inventory"."""
        body = (await stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "BRG-6204", "quantity": 1,
        })).json()

        assert body["fanout"]["fully_posted"] is False
        assert body["fanout"]["by_status"] == {PostingStatus.MANUAL_REQUIRED: 3}
        assert len(body["fanout"]["awaiting_a_person"]) == 3

    async def test_each_manual_posting_carries_an_instruction(self, stack):
        """The analog path: a sentence a supervisor can read to a stores clerk. Without it
        `manual_required` would be a status with no way to act on it."""
        body = (await stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "BRG-6204", "quantity": 4, "work_order_ref": "WO-1001",
        })).json()

        for entry in body["fanout"]["awaiting_a_person"]:
            assert entry["instruction"], entry
            assert "BRG-6204" in entry["instruction"]
            assert "WO-1001" in entry["instruction"]

    async def test_an_integrated_target_is_pending_not_manual(self, integrated_stack):
        """With an ERP claiming inventory and accounting, only purchasing needs a human —
        and the response says exactly which."""
        body = (await integrated_stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "BRG-6204", "quantity": 1,
        })).json()

        assert body["fanout"]["by_status"] == {
            PostingStatus.PENDING: 2, PostingStatus.MANUAL_REQUIRED: 1
        }
        awaiting = body["fanout"]["awaiting_a_person"]
        assert [a["target"] for a in awaiting] == [TargetSystem.PURCHASING]

    async def test_pending_is_never_reported_as_posted(self, integrated_stack):
        """`pending` means an integration exists and has not taken it yet. Rendering that
        as success is the exact failure this ledger was built to prevent."""
        body = (await integrated_stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "X", "quantity": 1,
        })).json()
        assert body["fanout"]["fully_posted"] is False
        assert PostingStatus.POSTED not in body["fanout"]["by_status"]


class TestTheLabourClock:
    async def test_clock_in_produces_no_postings(self, stack):
        """An open shift has produced no hours. Posting it would put a running clock into
        payroll."""
        response = await stack.post("/api/v1/shop-floor/labor/clock-in", json={
            "work_order_ref": "WO-1001",
        })
        assert response.status_code == 201, response.text
        assert response.json()["fanout"] is None

    async def test_a_second_clock_in_is_refused(self, stack):
        """Two open clocks make overlapping hours that payroll cannot reconcile."""
        await stack.post("/api/v1/shop-floor/labor/clock-in", json={})
        second = await stack.post("/api/v1/shop-floor/labor/clock-in", json={})
        assert second.status_code == 409, second.text
        assert "already clocked in" in second.text

    async def test_clock_out_routes_to_production_and_accounting(self, stack):
        await stack.post("/api/v1/shop-floor/labor/clock-in", json={"work_order_ref": "WO-9"})
        response = await stack.post("/api/v1/shop-floor/labor/clock-out", json={})
        assert response.status_code == 200, response.text
        body = response.json()

        postings = await _postings(stack, EventType.LABOR_ENTRY, body["id"])
        assert set(postings) == {TargetSystem.PRODUCTION, TargetSystem.ACCOUNTING}
        assert body["duration_minutes"] is not None

    async def test_clock_out_with_nothing_open_is_a_404(self, stack):
        response = await stack.post("/api/v1/shop-floor/labor/clock-out", json={})
        assert response.status_code == 404

    async def test_the_open_entry_is_reported_as_null_when_absent(self, stack):
        """Null is the real answer. An empty object would read as "clocked in with no
        details"."""
        assert (await stack.get("/api/v1/shop-floor/labor/open")).json() is None


class TestReportingAProblem:
    async def test_it_reaches_four_systems(self, stack):
        body = (await stack.post("/api/v1/shop-floor/quality-events", json={
            "description": "Bore out of tolerance", "severity": "major",
            "part_number": "SHFT-77", "quantity_affected": 10, "scrap_quantity": 3,
        })).json()

        postings = await _postings(stack, EventType.QUALITY_EVENT, body["id"])
        assert set(postings) == {
            TargetSystem.QUALITY, TargetSystem.INVENTORY,
            TargetSystem.PRODUCTION, TargetSystem.ACCOUNTING,
        }

    async def test_scrap_cannot_exceed_the_affected_quantity(self, stack):
        """Arithmetic nobody can act on. Three scrapped from two affected would put a
        negative into the inventory posting."""
        response = await stack.post("/api/v1/shop-floor/quality-events", json={
            "description": "x", "quantity_affected": 2, "scrap_quantity": 3,
        })
        assert response.status_code == 422, response.text


class TestMachineDowntime:
    async def test_starting_downtime_produces_no_postings(self, stack):
        response = await stack.post("/api/v1/shop-floor/downtime/start", json={
            "asset_id": stack.asset_id, "downtime_type": "unplanned", "reason_code": "TOOL_BREAK",
        })
        assert response.status_code == 201, response.text
        assert response.json()["fanout"] is None

    async def test_a_second_open_downtime_is_refused(self, stack):
        """Overlapping downtime spans make the OEE denominator meaningless."""
        await stack.post("/api/v1/shop-floor/downtime/start", json={"asset_id": stack.asset_id})
        second = await stack.post("/api/v1/shop-floor/downtime/start", json={"asset_id": stack.asset_id})
        assert second.status_code == 409, second.text

    async def test_ending_it_reaches_four_systems(self, stack):
        started = (await stack.post("/api/v1/shop-floor/downtime/start", json={
            "asset_id": stack.asset_id, "downtime_type": "maintenance",
        })).json()
        response = await stack.post(f"/api/v1/shop-floor/downtime/{started['id']}/end", json={})
        assert response.status_code == 200, response.text
        body = response.json()

        postings = await _postings(stack, EventType.DOWNTIME_EVENT, body["id"])
        assert set(postings) == {
            TargetSystem.SCHEDULING, TargetSystem.PRODUCTION,
            TargetSystem.QUALITY, TargetSystem.ACCOUNTING,
        }
        assert body["duration_minutes"] is not None

    async def test_ending_it_twice_is_refused(self, stack):
        started = (await stack.post("/api/v1/shop-floor/downtime/start", json={
            "asset_id": stack.asset_id,
        })).json()
        await stack.post(f"/api/v1/shop-floor/downtime/{started['id']}/end", json={})
        again = await stack.post(f"/api/v1/shop-floor/downtime/{started['id']}/end", json={})
        assert again.status_code == 400


class TestTheAnalogHandover:
    async def test_acknowledging_without_a_reference_is_not_a_posting(self, stack):
        """Telling the stores clerk and the stores system having a record are DIFFERENT
        FACTS. Collapsing them would rebuild the ambiguity the ledger removes."""
        body = (await stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "BRG-6204", "quantity": 1,
        })).json()
        postings = await _postings(stack, EventType.PART_ISSUE, body["id"])
        target = postings[TargetSystem.PURCHASING]

        response = await stack.post(
            f"/api/v1/shop-floor/postings/{target.id}/acknowledge", json={}
        )
        assert response.status_code == 200, response.text
        acknowledged = response.json()
        assert acknowledged["status"] == PostingStatus.MANUAL_REQUIRED
        assert acknowledged["acknowledged_at"] is not None

    async def test_acknowledging_with_a_reference_posts_it(self, stack):
        body = (await stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "BRG-6204", "quantity": 1,
        })).json()
        postings = await _postings(stack, EventType.PART_ISSUE, body["id"])
        target = postings[TargetSystem.INVENTORY]

        response = await stack.post(
            f"/api/v1/shop-floor/postings/{target.id}/acknowledge",
            json={"external_ref": "REQ-4471"},
        )
        assert response.status_code == 200, response.text
        acknowledged = response.json()
        assert acknowledged["status"] == PostingStatus.POSTED
        assert acknowledged["external_ref"] == "REQ-4471"
        assert acknowledged["posted_at"] is not None

    async def test_outstanding_is_the_operator_view(self, stack):
        await stack.post("/api/v1/shop-floor/part-issues", json={
            "part_number": "BRG-6204", "quantity": 1,
        })
        page = (await stack.get(
            "/api/v1/shop-floor/postings", params={"outstanding_only": True}
        )).json()
        rows = page["items"]
        assert len(rows) == 3
        assert {r["status"] for r in rows} == {PostingStatus.MANUAL_REQUIRED}
        # The envelope, not a bare array: an operator working a backlog has to be able to
        # tell "these are all of them" from "these are the first hundred".
        assert page["total"] == 3
        assert page["truncated"] is False


class TestTheMandateIsInspectable:
    async def test_routing_states_all_four_workflows(self, stack):
        routing = (await stack.get("/api/v1/shop-floor/routing")).json()["routing"]
        assert set(routing[EventType.PART_ISSUE]) == {"inventory", "purchasing", "accounting"}
        assert set(routing[EventType.LABOR_ENTRY]) == {"production", "accounting"}
        assert set(routing[EventType.QUALITY_EVENT]) == {
            "quality", "inventory", "production", "accounting"
        }
        assert set(routing[EventType.DOWNTIME_EVENT]) == {
            "scheduling", "production", "quality", "accounting"
        }


class TestTheInstructionIsCorrectAtTheEdges:
    """A zero-length event still gets a truthful sentence.

    FOUND BY DRIVING THE RUNNING APP, not by these tests — every case above used a duration
    that happened to be non-zero, so `if event.duration_minutes` looked right. It is not:
    a stop that lasts under a minute rounds to 0.0, which is falsy, and the person being
    told was sent the word "ongoing" for a machine that was already back up.
    """

    async def test_a_zero_minute_stop_is_not_described_as_ongoing(self, stack):
        started = (await stack.post("/api/v1/shop-floor/downtime/start", json={
            "asset_id": stack.asset_id, "downtime_type": "unplanned",
        })).json()
        ended = (await stack.post(
            f"/api/v1/shop-floor/downtime/{started['id']}/end", json={}
        )).json()

        assert ended["duration_minutes"] == 0.0
        instructions = [a["instruction"] for a in ended["fanout"]["awaiting_a_person"]]
        assert instructions, "this fixture has no integrations, so every target is manual"
        for instruction in instructions:
            assert "ongoing" not in instruction, (
                "the machine is back up; telling a scheduler it is still down sends them to "
                "look at a running machine"
            )
            assert "0.0 min" in instruction

    async def test_a_zero_minute_shift_is_not_described_as_open(self, stack):
        await stack.post("/api/v1/shop-floor/labor/clock-in", json={})
        ended = (await stack.post("/api/v1/shop-floor/labor/clock-out", json={})).json()

        assert ended["duration_minutes"] == 0.0
        for item in ended["fanout"]["awaiting_a_person"]:
            assert "an open shift" not in item["instruction"], (
                "a closed entry reported to payroll as an open shift is a different and "
                "wrong instruction"
            )
