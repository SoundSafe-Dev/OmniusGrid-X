"""A checkpoint that could not say who passed the trailer (FS-660).

`POST /yard/checkpoints` is the only mutating route in `yard.py` that no test drove — found by
asking rule 139's question of a second file, after it turned up two live defects in the first.

`YardCheckPointCreate` declares `inspector_id` and `metadata`. `YardCheckPointResponse` returns
them. `YardCheckPoint` has an `inspector_id` column and a `meta_data` column. **The route
passed neither to the service**, so both were accepted, discarded, and echoed back as `null`
and `{}` from columns that stayed empty.

WHY IT MATTERS MORE THAN IT LOOKS. `checkpoint_type` is one of gate_in, guard_shack,
weigh_station or gate_out, and `inspection_status` is passed/failed/pending. On a
weigh-station or guard-shack checkpoint the inspector IS the audit trail — the record says an
inspection happened and cannot say who made it. A failed inspection with no inspector is a
finding nobody owns.

Same class as the `note` on `POST /shipments/{id}/status` an hour earlier, and the opposite
resolution: there, the field had nowhere to go and the API now refuses it; here the column
exists and was simply not wired, so the fix is to store it. **The test to apply is whether the
field has somewhere to land**, not whether it looks harmless.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import yard as yard_api


@pytest.fixture
def recorded(monkeypatch):
    """Capture what the route hands the service, which is where the fields were lost."""
    calls: list[dict] = []

    async def _record(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            id=uuid.uuid4(),
            organization_id=kwargs["organization_id"],
            trailer_id=kwargs["trailer_id"],
            checkpoint_type=kwargs["checkpoint_type"],
            checkpoint_name=kwargs.get("checkpoint_name"),
            weight_lbs=kwargs.get("weight_lbs"),
            inspection_status=kwargs.get("inspection_status"),
            inspector_id=kwargs.get("inspector_id"),
            meta_data=kwargs.get("meta_data") or {},
            passed_at="2026-08-11T09:00:00+00:00",
            created_at="2026-08-11T09:00:00+00:00",
        )

    monkeypatch.setattr(yard_api.yard_management_service, "record_checkpoint", _record)
    return calls


@pytest.fixture
def client():
    from app.api.auth import get_current_active_user
    from app.middleware.rbac import require_operator_or_admin
    from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id

    async def _db():
        yield None

    org = uuid.uuid4()
    bare = FastAPI()
    bare.include_router(yard_api.router, prefix="/api/v1/yard")
    bare.dependency_overrides[get_tenant_db] = _db
    bare.dependency_overrides[get_tenant_org_id] = lambda: org
    bare.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="admin"
    )
    bare.dependency_overrides[require_operator_or_admin] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="admin"
    )
    return TestClient(bare), org


def _post(client, **over):
    body = {
        "trailer_id": str(uuid.uuid4()),
        "checkpoint_type": "weigh_station",
        "checkpoint_name": "North scale",
        **over,
    }
    return client.post("/api/v1/yard/checkpoints", json=body)


class TestTheFieldsTheRouteUsedToDrop:
    def test_the_inspector_reaches_the_service(self, client, recorded):
        """THE DEFECT. Accepted by the schema, never passed on, echoed back as null."""
        c, _ = client
        inspector = str(uuid.uuid4())
        response = _post(c, inspector_id=inspector, inspection_status="failed")
        assert response.status_code == 200
        assert str(recorded[0]["inspector_id"]) == inspector, (
            "the inspector was accepted and discarded. On a weigh-station or guard-shack "
            "checkpoint that field is the audit trail — a failed inspection with no "
            "inspector is a finding nobody owns."
        )

    def test_the_inspector_comes_back_on_the_wire(self, client, recorded):
        """Storing it and not returning it would be the same defect one layer along."""
        c, _ = client
        inspector = str(uuid.uuid4())
        assert _post(c, inspector_id=inspector).json()["inspector_id"] == inspector

    def test_the_metadata_reaches_the_service(self, client, recorded):
        c, _ = client
        response = _post(c, metadata={"seal": "A-4471"})
        assert response.status_code == 200
        assert recorded[0]["meta_data"] == {"seal": "A-4471"}

    def test_metadata_comes_back_under_its_serialization_alias(self, client, recorded):
        """The column is `meta_data` and the wire name is `metadata`. A rename that leaked
        through would break every client silently — pydantic would answer the other key
        rather than error."""
        c, _ = client
        assert _post(c, metadata={"seal": "A-4471"}).json()["metadata"] == {"seal": "A-4471"}


class TestWhatTheRouteAlreadyDidRight:
    def test_the_tenant_comes_from_the_token(self, client, recorded):
        """`organization_id` was removed from the create schema by FS-523 precisely because
        the handler derives it from the token — a caller who sent one got a 422 for a value
        the server discards. This keeps the derivation wired."""
        c, org = client
        _post(c, organization_id=str(uuid.uuid4()))
        assert recorded[0]["organization_id"] == org

    def test_the_checkpoint_type_is_carried(self, client, recorded):
        c, _ = client
        _post(c, checkpoint_type="gate_out")
        assert recorded[0]["checkpoint_type"] == "gate_out"

    def test_a_weight_is_carried(self, client, recorded):
        """A weigh-station checkpoint with no weight is the reason the route exists."""
        c, _ = client
        _post(c, weight_lbs=42150.5)
        assert float(recorded[0]["weight_lbs"]) == 42150.5

    def test_a_checkpoint_with_only_its_required_fields_is_accepted(self, client, recorded):
        c, _ = client
        response = c.post(
            "/api/v1/yard/checkpoints",
            json={"trailer_id": str(uuid.uuid4()), "checkpoint_type": "gate_in"},
        )
        assert response.status_code == 200
        assert recorded[0]["inspector_id"] is None


class TestATrailerCheckInKeepsWhatItWasTold:
    """The same class, five fields wide, on the route beside it (FS-661).

    `POST /yard/trailers/checkin` passed eight fields to the service and dropped five that
    `YardTrailerCreate` declares and `yard_trailers` has columns for: `seal_status`,
    `temperature_setpoint`, `temperature_actual`, `yard_location` and `metadata`.

    `seal_number` was passed and `seal_status` was not, which is the pairing worth naming: the
    record said WHICH seal and could not say whether it was intact. On a yard-security
    check-in that is the same defect as the checkpoint with no inspector — the record of the
    check exists and the finding does not.
    """

    @pytest.fixture
    def checked_in(self, monkeypatch):
        calls: list[dict] = []

        async def _check_in(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                id=uuid.uuid4(),
                organization_id=kwargs["organization_id"],
                trailer_number=kwargs["trailer_number"],
                status="checked_in",
                seal_status=kwargs.get("seal_status"),
                yard_location=kwargs.get("yard_location"),
                temperature_setpoint=kwargs.get("temperature_setpoint"),
                temperature_actual=kwargs.get("temperature_actual"),
                meta_data=kwargs.get("meta_data") or {},
                # `YardTrailerResponse` requires these — nullable on the table with no server
                # default, so a row written outside SQLAlchemy hands them an explicit None and
                # the model declares them rather than defaulting. Omitting them here is a
                # ResponseValidationError, not a pass.
                trailer_type=kwargs.get("trailer_type"),
                seal_number=kwargs.get("seal_number"),
                weight_lbs=kwargs.get("weight_lbs"),
                carrier_id=None,
                driver_id=None,
                shipment_id=None,
                dock_door_id=None,
                check_out_at=None,
                # NOT None: `updated_at` is a non-nullable datetime on the response model,
                # so a null here is a ResponseValidationError rather than the assertion under
                # test failing — the fixture has to be at least as complete as a real row.
                updated_at="2026-08-11T09:00:00+00:00",
                check_in_at="2026-08-11T09:00:00+00:00",
                created_at="2026-08-11T09:00:00+00:00",
            )

        monkeypatch.setattr(yard_api.yard_management_service, "check_in_trailer", _check_in)
        return calls

    def _checkin(self, client, **over):
        return client.post(
            "/api/v1/yard/trailers/checkin",
            json={"trailer_number": "T-4471", **over},
        )

    def test_a_broken_seal_is_recorded(self, client, checked_in):
        """THE DEFECT, in the form that matters most. A guard reporting a broken seal was
        told 200 and the row said 'intact'."""
        c, _ = client
        assert self._checkin(c, seal_number="S-99", seal_status="broken").status_code == 200
        assert checked_in[0]["seal_status"] == "broken", (
            "a reported broken seal was discarded. The record names the seal and cannot say "
            "whether it was intact — the same shape as a checkpoint with no inspector."
        )

    def test_the_reefer_temperatures_are_recorded(self, client, checked_in):
        """Cold-chain evidence: what the box was set to and what it actually read."""
        c, _ = client
        self._checkin(c, temperature_setpoint=-18.0, temperature_actual=-11.5)
        assert float(checked_in[0]["temperature_setpoint"]) == -18.0
        assert float(checked_in[0]["temperature_actual"]) == -11.5

    def test_the_yard_location_is_recorded(self, client, checked_in):
        """The field the yard map reads. Dropped, every trailer parks at None."""
        c, _ = client
        self._checkin(c, yard_location="B-14")
        assert checked_in[0]["yard_location"] == "B-14"

    def test_the_metadata_is_recorded(self, client, checked_in):
        c, _ = client
        self._checkin(c, metadata={"bol": "9912"})
        assert checked_in[0]["meta_data"] == {"bol": "9912"}

    def test_a_caller_cannot_check_a_trailer_straight_out(self, client, checked_in):
        """`status` is the one declared field this route SHOULD keep ignoring. The service
        sets 'checked_in'; honouring a caller's status would let somebody move a trailer to
        'checked_out' without it ever entering the yard."""
        c, _ = client
        self._checkin(c, status="checked_out")
        assert "status" not in checked_in[0]

    def test_an_unstated_seal_is_recorded_as_intact_which_is_a_finding(self, client, checked_in):
        """PINS A DEFECT THIS FIX DID NOT CLOSE, deliberately.

        `YardTrailerBase.seal_status` is `str = "intact"` — not Optional. So a check-in that
        says nothing about the seal records **"intact"** as a positive claim: a value invented
        at the moment nothing is known, and the most reassuring possible answer. Rule 133, on
        a security field.

        Not changed here, and the reason is worth stating rather than fixing quietly. The
        column carries the same default, so making the schema `Optional[str] = None` moves the
        fabrication one layer down rather than removing it — the honest fix is a migration to
        a nullable column with no default, plus a decision about what existing rows mean. That
        is a contract change with readers to find, not a wiring fix.

        Recorded as a test rather than a comment so it cannot be lost, and so the day somebody
        makes the column nullable this fails and points at the reason.
        """
        c, _ = client
        self._checkin(c, seal_number="S-99")
        assert checked_in[0].get("seal_status") == "intact"
