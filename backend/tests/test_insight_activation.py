"""A correlation-AI recommendation becomes real, evidenced work (FS-406).

The demonstrated scenario is: an analysis session surfaces an actionable insight, the
operator activates it directly from the session, and it lands as a Kanban task AND as a
dispatch to the ERP and every other system of record it touches — then gets confirmed and
validated.

WHAT THESE ASSERT THAT A NAIVE TEST WOULD NOT. Not "activation returned 201". The old
behaviour already returned successfully while doing nothing observable — an "Auto-integrate"
checkbox firing a background job whose outcome never came back. So every case here checks
the artefacts:

  * a Kanban `Task` row exists, with the activation id in its custom fields
  * one `SystemOfRecordPosting` per target system the insight's domain implies
  * confirmation is REFUSED, with named blockers, until the task is finished and every
    posting carries evidence

THE REFUSAL CASES ARE THE POINT. A confirm that always succeeds is decoration. Three tests
below exist purely to prove it says no: unfinished task, un-acknowledged manual posting, and
an already-rejected activation.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.insight_models import ActivationStatus, InsightActivation
from app.db.models import (
    Asset, AssetType, Base, IntegrationConfiguration, Organization, Task, TaskBoard,
    TaskColumn, User, Workcell,
)
from app.db.shop_floor_models import (
    EventType, PostingStatus, SystemOfRecordPosting, TargetSystem,
)

pytestmark = pytest.mark.asyncio

ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _tables():
    return [
        Organization.__table__, Workcell.__table__, AssetType.__table__,
        Asset.__table__, User.__table__, IntegrationConfiguration.__table__,
        TaskBoard.__table__, TaskColumn.__table__, Task.__table__,
        SystemOfRecordPosting.__table__, InsightActivation.__table__,
    ]


async def _build(serves: dict[str, list[str]] | None = None, *, with_board: bool = True):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_tables())
    maker = async_sessionmaker(engine, expire_on_commit=False)

    asset_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with maker() as session:
        wc, at = str(uuid.uuid4()), str(uuid.uuid4())
        session.add(Organization(id=str(ORG_ID), name="QA Org", slug="qa-org-2"))
        session.add(Workcell(id=wc, organization_id=str(ORG_ID), name="Cell"))
        session.add(AssetType(id=at, name="Mill", category="machine"))
        session.add(Asset(id=asset_id, organization_id=str(ORG_ID), workcell_id=wc,
                          asset_type_id=at, name="CNC Mill #1"))
        session.add(User(id=user_id, organization_id=str(ORG_ID), email="op@test.local",
                         hashed_password="x" * 60, role="admin", is_active=True))
        if with_board:
            board_id = str(uuid.uuid4())
            session.add(TaskBoard(id=board_id, organization_id=str(ORG_ID),
                                  name="Operations", is_active=True))
            session.add(TaskColumn(id=str(uuid.uuid4()), board_id=board_id,
                                   name="Triage", column_type="triage", position=0))
        for name, targets in (serves or {}).items():
            session.add(IntegrationConfiguration(
                id=str(uuid.uuid4()), organization_id=str(ORG_ID),
                integration_type="erp", integration_name=name, is_active=True,
                configuration={"serves_systems": targets},
            ))
        await session.commit()
    return engine, maker, asset_id, user_id


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


@pytest_asyncio.fixture
async def stack():
    """No integrations: every target lands on the analog path."""
    engine, maker, asset_id, user_id = await _build()
    async for client in _client(maker, user_id):
        client.asset_id = asset_id      # type: ignore[attr-defined]
        client.maker = maker            # type: ignore[attr-defined]
        yield client
    await engine.dispose()


@pytest_asyncio.fixture
async def integrated_stack():
    """An ERP serving maintenance, scheduling and production — the MAINTENANCE fan-out."""
    engine, maker, asset_id, user_id = await _build({
        "SAP": [TargetSystem.MAINTENANCE, TargetSystem.SCHEDULING, TargetSystem.PRODUCTION],
    })
    async for client in _client(maker, user_id):
        client.asset_id = asset_id      # type: ignore[attr-defined]
        client.maker = maker            # type: ignore[attr-defined]
        yield client
    await engine.dispose()


@pytest_asyncio.fixture
async def boardless_stack():
    """An organisation with no active Kanban board."""
    engine, maker, asset_id, user_id = await _build(with_board=False)
    async for client in _client(maker, user_id):
        client.maker = maker            # type: ignore[attr-defined]
        yield client
    await engine.dispose()


ACTION = {
    "title": "Schedule preventive maintenance on the spindle bearing",
    "description": "Vibration and thermal trend both cross threshold within 6 days.",
    "domain": "MAINTENANCE",
    "priority": "high",
}


async def _activate(client, **overrides):
    payload = {**ACTION, **overrides}
    response = await client.post("/api/v1/insights/activations", json=payload)
    assert response.status_code == 201, response.text
    return response.json()



def _blockers(response) -> list[dict]:
    """Dig the blockers out of the app's problem+json envelope.

    A structured `HTTPException` detail lands at `error.details.detail` (app/core/errors.py),
    and the top-level `message` becomes the generic "request failed". Read through the
    envelope rather than around it — asserting on a shape the wire does not have is how a
    test passes while the client it stands in for cannot find the data.
    """
    return response.json()["error"]["details"]["detail"]["blockers"]


async def _complete_task(client, task_id):
    async with client.maker() as session:
        task = await session.get(Task, task_id)
        task.status = "completed"
        await session.commit()


# --------------------------------------------------------------------------------- issue
class TestActivatingAnInsight:
    async def test_it_creates_a_kanban_task_carrying_the_activation(self, stack):
        body = await _activate(stack)

        assert body["task"] is not None, (
            "an activated insight with no task is invisible on the board — the exact "
            "failure the old auto-integrate path produced silently"
        )
        async with stack.maker() as session:
            task = await session.get(Task, body["task"]["id"])
        assert task is not None
        assert task.custom_fields["activation_id"] == body["id"]
        # The title is a maintenance verb, so the board shows it as PM work rather than
        # dumping every AI recommendation into `custom`.
        assert task.task_type == "maintenance_pm"
        # A person clicked Activate, so a person is the approver.
        assert task.approval_status == "approved"

    async def test_it_posts_to_every_system_the_domain_implies(self, stack):
        body = await _activate(stack)

        assert {p["target_system"] for p in body["postings"]} == {
            TargetSystem.MAINTENANCE, TargetSystem.SCHEDULING, TargetSystem.PRODUCTION,
        }
        async with stack.maker() as session:
            rows = (await session.execute(
                select(SystemOfRecordPosting).where(
                    SystemOfRecordPosting.event_type == EventType.INSIGHT_ACTIVATION,
                    SystemOfRecordPosting.event_id == body["id"],
                )
            )).scalars().all()
        assert len(rows) == 3

    async def test_it_does_not_claim_the_action_is_done(self, stack):
        body = await _activate(stack)

        assert body["status"] == ActivationStatus.ISSUED
        assert body["ready_to_confirm"] is False
        assert body["validation"] is None
        assert all(p["status"] != PostingStatus.POSTED for p in body["postings"]), (
            "nothing has been sent anywhere at the moment of activation; a posted status "
            "here would be a claim with no evidence behind it"
        )

    async def test_a_shop_with_no_integration_gets_something_to_tell_a_person(self, stack):
        body = await _activate(stack)

        awaiting = body["awaiting_a_person"]
        assert {a["target"] for a in awaiting} == {
            TargetSystem.MAINTENANCE, TargetSystem.SCHEDULING, TargetSystem.PRODUCTION,
        }
        for item in awaiting:
            assert item["instruction"], (
                "the analog path is a feature: a target with no integration must arrive with "
                "the sentence a supervisor reads out, not just a status"
            )
            assert "not yet entered" in item["instruction"].lower() or item["instruction"]

    async def test_an_integrated_target_is_queued_not_handed_to_a_person(
        self, integrated_stack
    ):
        body = await _activate(integrated_stack)

        by_target = {p["target_system"]: p for p in body["postings"]}
        assert by_target[TargetSystem.MAINTENANCE]["status"] == PostingStatus.PENDING
        assert by_target[TargetSystem.MAINTENANCE]["instruction"] is None, (
            "an instruction on an integrated target reads as work a person still has to do "
            "after the machine already did it"
        )
        assert body["awaiting_a_person"] == []

    async def test_an_unmapped_domain_does_not_invent_an_accounting_posting(self, stack):
        body = await _activate(stack, domain="SOMETHING_NOBODY_MAPPED")

        assert {p["target_system"] for p in body["postings"]} == {TargetSystem.PRODUCTION}, (
            "fanning an unclassified recommendation out to accounting would post money "
            "movements nobody asked for"
        )

    async def test_explicit_targets_are_validated(self, stack):
        response = await stack.post("/api/v1/insights/activations", json={
            **ACTION, "targets": ["inventory", "telepathy"],
        })
        assert response.status_code == 422
        assert "telepathy" in response.text

    async def test_a_missing_board_is_reported_not_hidden(self, boardless_stack):
        body = await _activate(boardless_stack)

        assert body["task"] is None
        assert "task board" in (body["task_blocked_reason"] or ""), (
            "the existing correlation integration returns None from three places with no "
            "way to tell them apart; an operator needs to know WHICH thing is missing"
        )
        # The postings still exist — the ERP side is not held hostage by the board.
        assert len(body["postings"]) == 3


class TestActivateIsIdempotent:
    async def test_a_double_click_does_not_dispatch_twice(self, stack):
        first = await _activate(stack)
        response = await stack.post("/api/v1/insights/activations", json=ACTION)
        second = response.json()

        assert second["id"] == first["id"]
        assert second["already_existed"] is True
        async with stack.maker() as session:
            tasks = (await session.execute(select(Task))).scalars().all()
            postings = (await session.execute(select(SystemOfRecordPosting))).scalars().all()
        assert len(tasks) == 1, (
            "on a slow network in a noisy building this button gets pressed twice; two work "
            "orders and two purchasing postings is how operators learn to distrust it"
        )
        assert len(postings) == 3

    async def test_a_different_recommendation_is_a_different_activation(self, stack):
        first = await _activate(stack)
        second = await _activate(stack, title="Replace the coolant filter", action_index=1)
        assert second["id"] != first["id"]


# ------------------------------------------------------------------------------- confirm
class TestConfirmationIsEarned:
    async def test_it_refuses_while_the_task_is_unfinished(self, stack):
        body = await _activate(stack)
        response = await stack.post(f"/api/v1/insights/activations/{body['id']}/confirm")

        assert response.status_code == 409
        blockers = _blockers(response)
        kinds = {b["kind"] for b in blockers}
        assert "task" in kinds
        assert any("not completed" in b["reason"] for b in blockers)

    async def test_it_refuses_while_a_person_has_not_confirmed_the_manual_step(self, stack):
        body = await _activate(stack)
        await _complete_task(stack, body["task"]["id"])

        response = await stack.post(f"/api/v1/insights/activations/{body['id']}/confirm")
        assert response.status_code == 409
        blockers = _blockers(response)
        assert {b["target"] for b in blockers} == {
            TargetSystem.MAINTENANCE, TargetSystem.SCHEDULING, TargetSystem.PRODUCTION,
        }
        for blocker in blockers:
            assert "nobody has confirmed the manual step" in blocker["reason"]

    async def test_it_confirms_once_the_work_and_every_posting_are_evidenced(self, stack):
        body = await _activate(stack)
        await _complete_task(stack, body["task"]["id"])
        for posting in body["postings"]:
            ack = await stack.post(
                f"/api/v1/insights/activations/{body['id']}"
                f"/postings/{posting['id']}/acknowledge",
                json={"external_ref": f"WO-{posting['target_system'][:3].upper()}-991"},
            )
            assert ack.status_code == 200, ack.text

        response = await stack.post(f"/api/v1/insights/activations/{body['id']}/confirm")
        assert response.status_code == 200, response.text
        confirmed = response.json()

        assert confirmed["status"] == ActivationStatus.CONFIRMED
        assert confirmed["validation"] is not None, (
            "a confirmation without its evidence snapshot is just an assertion"
        )
        assert confirmed["validation"]["task"]["status"] == "completed"
        evidence = {p["target"]: p["evidence"] for p in confirmed["validation"]["postings"]}
        assert set(evidence.values()) == {"external_reference"}

    async def test_a_human_acknowledgement_is_weaker_evidence_and_is_recorded_as_such(
        self, stack
    ):
        body = await _activate(stack)
        await _complete_task(stack, body["task"]["id"])
        for posting in body["postings"]:
            # No external_ref: "I told them", not "the system has a record".
            await stack.post(
                f"/api/v1/insights/activations/{body['id']}"
                f"/postings/{posting['id']}/acknowledge",
                json={},
            )

        response = await stack.post(f"/api/v1/insights/activations/{body['id']}/confirm")
        assert response.status_code == 200, response.text
        snapshot = response.json()["validation"]["postings"]

        assert {p["evidence"] for p in snapshot} == {"human_acknowledgement"}
        assert all(p["status"] == PostingStatus.MANUAL_REQUIRED for p in snapshot), (
            "acknowledging that you phoned it through must not silently promote the posting "
            "to `posted` — those are different facts and the snapshot has to keep them apart"
        )

    async def test_a_rejected_activation_cannot_be_confirmed(self, stack):
        body = await _activate(stack)
        await stack.post(
            f"/api/v1/insights/activations/{body['id']}/reject",
            json={"reason": "the bearing was replaced last week"},
        )
        response = await stack.post(f"/api/v1/insights/activations/{body['id']}/confirm")
        assert response.status_code == 409


class TestRejection:
    async def test_a_reason_is_required(self, stack):
        body = await _activate(stack)
        response = await stack.post(
            f"/api/v1/insights/activations/{body['id']}/reject", json={"reason": ""}
        )
        assert response.status_code == 422

    async def test_the_reason_is_kept(self, stack):
        body = await _activate(stack)
        response = await stack.post(
            f"/api/v1/insights/activations/{body['id']}/reject",
            json={"reason": "duplicate of WO-8812"},
        )
        assert response.status_code == 200
        assert response.json()["rejection_reason"] == "duplicate of WO-8812"
        assert response.json()["status"] == ActivationStatus.REJECTED

    async def test_a_confirmed_activation_cannot_be_rejected(self, stack):
        body = await _activate(stack)
        await _complete_task(stack, body["task"]["id"])
        for posting in body["postings"]:
            await stack.post(
                f"/api/v1/insights/activations/{body['id']}"
                f"/postings/{posting['id']}/acknowledge",
                json={"external_ref": "REF-1"},
            )
        await stack.post(f"/api/v1/insights/activations/{body['id']}/confirm")

        response = await stack.post(
            f"/api/v1/insights/activations/{body['id']}/reject", json={"reason": "changed mind"}
        )
        assert response.status_code == 409


class TestTheLedgerIsReadable:
    async def test_listing_carries_a_total_not_a_bare_array(self, stack):
        await _activate(stack)
        page = (await stack.get("/api/v1/insights/activations")).json()
        assert page["total"] == 1
        assert page["truncated"] is False
        assert len(page["items"]) == 1

    async def test_filtering_by_an_unknown_status_is_a_422_not_an_empty_list(self, stack):
        response = await stack.get("/api/v1/insights/activations", params={"status": "done"})
        assert response.status_code == 422, (
            "an empty list for a typo'd filter reads as 'there are none', which is a "
            "different and wrong answer"
        )

    async def test_an_unknown_activation_is_a_404(self, stack):
        response = await stack.get(f"/api/v1/insights/activations/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_the_domain_mapping_is_inspectable(self, stack):
        body = (await stack.get("/api/v1/insights/domain-routing")).json()
        assert body["routing"]["MAINTENANCE"] == ["maintenance", "scheduling", "production"]
        assert body["default_targets"] == ["production"]
        assert "accounting" in body["default_reason"], (
            "a one-target fallback looks like a routing decision unless it says otherwise"
        )
