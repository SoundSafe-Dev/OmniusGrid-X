"""A dispatch that succeeded reported as a failure (FS-657).

`POST /transportation/shipments/{id}/dispatch` built its response with a bare `driver_id`.
There is no such name in that scope — the request body is `request.driver_id` — so the line
raised `NameError` and FastAPI answered **500**.

WHY THAT IS WORSE THAN A 500. `transportation_management_service.dispatch_shipment` sets the
status, assigns the driver and trailer, and **commits** before returning. The NameError is
raised after that, while the route is building its reply. So the shipment really was
dispatched, and the operator was told it was not — which is the one error that makes somebody
do the thing twice.

WHY NOTHING CAUGHT IT. Two guards should have had a claim on this and neither did:

  * `tests/route_walk.py` drives every route against a real Postgres looking for 5xx, but a
    generated `shipment_id` matches no row, so `dispatch_shipment` raises
    `ValueError("Shipment not found")` and the route answers 400. **The defect is reachable
    only by succeeding**, and the smoke test never succeeds.
  * `flake8 --select=E9,F63,F7,F82` reports exactly this as `F821 undefined name`, and it has
    been a blocking step in `ci-cd.yml` for months — a workflow that runs on `main` and
    `pull_request` and not on any branch push. See
    `test_branch_pushes_reach_the_gates.py`; this file is what that hole was hiding.

The test below therefore drives the SUCCESS path with the service faked, which is the only
shape that reaches the broken line without a live shipment, driver and HOS-compliant record.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import transportation as transportation_api


@pytest.fixture
def dispatched(monkeypatch):
    """Make the service report a successful dispatch, as it does for a real shipment."""
    calls: list[dict] = []

    async def _dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="dispatched")

    monkeypatch.setattr(
        transportation_api.transportation_management_service,
        "dispatch_shipment",
        _dispatch,
    )
    return calls


@pytest.fixture
def client():
    """The router on a bare app, not `app.main:app`.

    Mounting the real application starts its lifespan, which opens a database connection —
    and this defect is in response construction, not persistence. The established pattern in
    this suite for a route-shape test is a minimal app; it also keeps the run at
    milliseconds rather than requiring Postgres to be up.
    """
    from app.api.auth import get_current_active_user
    from app.middleware.rbac import require_operator_or_admin
    from app.middleware.tenant_isolation import get_tenant_db

    async def _db():
        yield None

    bare = FastAPI()
    bare.include_router(transportation_api.router, prefix="/api/v1/transportation")
    bare.dependency_overrides[get_tenant_db] = _db
    # The router carries `dependencies=[Depends(get_current_active_user)]`, so overriding the
    # role check alone leaves every request a 401 — a failure that looks like the route being
    # protected and is really the fixture being incomplete.
    bare.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="admin"
    )
    bare.dependency_overrides[require_operator_or_admin] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="admin"
    )
    return TestClient(bare)


class TestASuccessfulDispatch:
    def test_it_does_not_five_hundred(self, client, dispatched):
        """THE DEFECT. Every successful dispatch raised NameError while building the reply."""
        response = client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/dispatch",
            json={"driver_id": str(uuid.uuid4()), "trailer_id": str(uuid.uuid4())},
        )
        assert response.status_code != 500, (
            f"a dispatch the service committed answered {response.status_code}. The shipment "
            f"is dispatched and the operator has been told it is not — which is the error "
            f"that makes somebody do it twice."
        )
        assert response.status_code == 200

    def test_it_names_the_driver_it_dispatched_to(self, client, dispatched):
        """The response field exists to tell the caller WHICH driver took the load. Returning
        the wrong one would be a quieter version of the same defect, so this asserts the value
        rather than only that the route answered."""
        driver_id = str(uuid.uuid4())
        response = client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/dispatch",
            json={"driver_id": driver_id, "trailer_id": str(uuid.uuid4())},
        )
        assert response.json()["driver_id"] == driver_id

    def test_it_reports_the_status_the_service_set(self, client, dispatched):
        response = client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/dispatch",
            json={"driver_id": str(uuid.uuid4()), "trailer_id": str(uuid.uuid4())},
        )
        assert response.json()["status"] == "dispatched"

    def test_the_service_was_asked_for_the_driver_in_the_body(self, client, dispatched):
        """FS-420 moved these into a body because FastAPI read bare parameters as QUERY
        parameters and every dispatch 422'd. This keeps the body wired to the service."""
        driver_id, trailer_id = str(uuid.uuid4()), str(uuid.uuid4())
        client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/dispatch",
            json={"driver_id": driver_id, "trailer_id": trailer_id},
        )
        assert str(dispatched[0]["driver_id"]) == driver_id
        assert str(dispatched[0]["trailer_id"]) == trailer_id


class TestARefusedDispatch:
    def test_a_missing_shipment_is_still_a_400(self, client, monkeypatch):
        """The path `route_walk` DOES reach, kept working. It is also the reason the defect
        survived: everything the smoke test could drive returned 400 before the broken line."""

        async def _refuse(**_kwargs):
            raise ValueError("Shipment not found")

        monkeypatch.setattr(
            transportation_api.transportation_management_service,
            "dispatch_shipment",
            _refuse,
        )
        response = client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/dispatch",
            json={"driver_id": str(uuid.uuid4()), "trailer_id": str(uuid.uuid4())},
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()

    def test_an_hos_refusal_names_its_reason(self, client, monkeypatch):
        """FS-421: a driver blocked for missing data produced "Driver not compliant: " with
        nothing after the colon. The reason has to survive to the caller."""

        async def _refuse(**_kwargs):
            raise ValueError("Driver not compliant: cannot be assessed — no recent logs")

        monkeypatch.setattr(
            transportation_api.transportation_management_service,
            "dispatch_shipment",
            _refuse,
        )
        response = client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/dispatch",
            json={"driver_id": str(uuid.uuid4()), "trailer_id": str(uuid.uuid4())},
        )
        assert response.status_code == 400
        assert response.json()["detail"].rstrip().endswith("no recent logs")


class TestAStatusUpdateTakesABody:
    """`POST /shipments/{id}/dispatch`'s immediate neighbour, with the defect FS-420 fixed
    here and left twenty lines away (FS-658).

    `update_shipment_status` declared `status: str` as a bare scalar. FastAPI reads a
    non-Pydantic scalar with no `Body(...)` marker as a QUERY parameter, and the client posts
    `{ status }` as JSON — so the required `?status=` was never present and **every status
    update answered 422**. The two buttons that call it, "Mark Delivered" and "Cancel" on the
    Transportation page, have never worked once.

    Third instance of this class: FS-379 on Strategic approve/reject, FS-420 on dispatch, and
    now the route immediately below the one FS-420 fixed. Fixing an instance is not fixing a
    class.
    """

    @pytest.fixture
    def updated(self, monkeypatch):
        calls: list[dict] = []

        async def _update(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status=kwargs["status"])

        monkeypatch.setattr(
            transportation_api.transportation_management_service,
            "update_shipment_status",
            _update,
        )
        return calls

    def test_a_json_body_is_accepted(self, client, updated):
        """THE DEFECT. This is exactly what the client sends, and it used to 422."""
        response = client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/status",
            json={"status": "delivered"},
        )
        assert response.status_code == 200, (
            f"a status update posting a JSON body answered {response.status_code}. Declared "
            f"as a bare scalar, `status` is a QUERY parameter and every call from the UI "
            f"fails validation."
        )
        assert response.json()["status"] == "delivered"

    def test_the_status_reaches_the_service(self, client, updated):
        client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/status",
            json={"status": "cancelled"},
        )
        assert updated[0]["status"] == "cancelled"

    def test_the_optional_timestamps_are_carried_through(self, client, updated):
        """They were bare parameters too, so they were query parameters too — and a delivery
        time that cannot be recorded is the reason to have this route at all."""
        client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/status",
            json={"status": "delivered", "actual_delivery": "2026-08-11T09:00:00Z"},
        )
        assert updated[0]["actual_delivery"] is not None

    def test_a_field_the_server_cannot_store_is_refused(self, client, updated):
        """`note` was in the client's signature and posted on every call. `Shipment` has no
        note column and the service never read it, so accepting the field would make the API
        claim to record something it discards. Pydantic drops unknown fields silently by
        default; `extra: "forbid"` is what turns that into an answer."""
        response = client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/status",
            json={"status": "delivered", "note": "left at the dock"},
        )
        assert response.status_code == 422

    def test_a_missing_shipment_is_a_404(self, client, monkeypatch):
        async def _refuse(**_kwargs):
            raise ValueError("Shipment not found")

        monkeypatch.setattr(
            transportation_api.transportation_management_service,
            "update_shipment_status",
            _refuse,
        )
        response = client.post(
            f"/api/v1/transportation/shipments/{uuid.uuid4()}/status",
            json={"status": "delivered"},
        )
        assert response.status_code == 404
