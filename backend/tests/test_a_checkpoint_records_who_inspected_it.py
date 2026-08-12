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
