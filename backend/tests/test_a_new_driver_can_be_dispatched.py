"""A driver created through the API could never be dispatched (FS-664).

THE CHAIN, and every link already existed:

  1. `POST /transportation/drivers` declared `current_hos_status`, `hos_drive_hours_today`,
     `hos_on_duty_hours_today` and `hos_cycle_hours` — and passed none of them.
  2. `HOSComplianceMonitor.check_compliance` collects **what is missing before what is
     wrong**: any of the three hour figures being `None` produces "cannot be assessed", by
     design, because `float(x or 0)` would turn "never reported" into "has driven zero hours"
     and read as a fresh, legal driver (FS-421).
  3. `dispatch_shipment` raises `ValueError("Driver not compliant: …")` on that verdict.

So a driver created through the API was permanently undispatchable, having been told 200 with
the hours in the request body.

**AND THERE WAS NO OTHER WAY IN.** The GeoTab ELD webhook writes `hos_drive_hours_today` and
`hos_on_duty_hours_today`, only those two and only when that gated integration is live.
`hos_cycle_hours` and `current_hos_status` have no writer anywhere but `seed_demo_data.py` —
which is exactly why the demo fleet dispatches and a real one would not. A defect that the
seed data hides is a defect nobody meets until production.

WHY IT WAS DEFERRED ONCE, and why that was wrong. The register entry said HOS "has a second
writer, the ELD sync, and which one wins on create is a decision". It is not: create sets the
state the operator knows, the webhook overwrites it when the ELD reports. There is no race,
and two of the four fields have no sync at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import transportation as transportation_api
from app.services.transportation_management import HOSComplianceMonitor


@pytest.fixture
def created(monkeypatch):
    calls: list[dict] = []

    async def _create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            id=uuid.uuid4(),
            organization_id=kwargs["organization_id"],
            carrier_id=kwargs.get("carrier_id"),
            first_name=kwargs["first_name"],
            last_name=kwargs["last_name"],
            license_number=kwargs.get("license_number"),
            license_state=kwargs.get("license_state"),
            cdl_class=kwargs.get("cdl_class"),
            hazmat_endorsed=kwargs.get("hazmat_endorsed", False),
            medical_cert_expires=kwargs.get("medical_cert_expires"),
            eld_device_id=kwargs.get("eld_device_id"),
            phone=kwargs.get("phone"),
            email=kwargs.get("email"),
            current_hos_status=kwargs.get("current_hos_status"),
            hos_drive_hours_today=kwargs.get("hos_drive_hours_today"),
            hos_on_duty_hours_today=kwargs.get("hos_on_duty_hours_today"),
            hos_cycle_hours=kwargs.get("hos_cycle_hours"),
            dq_file_complete=kwargs.get("dq_file_complete", False),
            is_active=kwargs.get("is_active", True),
            created_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
            updated_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(
        transportation_api.transportation_management_service, "create_driver", _create
    )
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
    bare.include_router(transportation_api.router, prefix="/api/v1/transportation")
    bare.dependency_overrides[get_tenant_db] = _db
    bare.dependency_overrides[get_tenant_org_id] = lambda: org
    bare.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="admin"
    )
    bare.dependency_overrides[require_operator_or_admin] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="admin"
    )
    return TestClient(bare), org


#: A driver who can actually take a load. The medical certificate is here because
#: `check_compliance` requires it too — and the route ALREADY passes that one, so its presence
#: in this payload is the machinery working as designed rather than another defect. It is a
#: useful control: the missing-data list is not merely empty, it is empty for a driver who has
#: everything, and it still names what is absent when anything is left out.
LEGAL_DRIVER = {
    "current_hos_status": "on_duty",
    "hos_drive_hours_today": 3.5,
    "hos_on_duty_hours_today": 5.0,
    "hos_cycle_hours": 28.0,
    "medical_cert_expires": "2027-01-01T00:00:00Z",
}

#: The four this route dropped, checked field by field.
LEGAL_HOURS = {
    k: v for k, v in LEGAL_DRIVER.items() if k != "medical_cert_expires"
}


def _create(client, **over):
    return client.post(
        "/api/v1/transportation/drivers",
        json={"first_name": "Dale", "last_name": "Ferris", **over},
    )


class TestTheHoursReachTheRecord:
    @pytest.mark.parametrize("field", sorted(LEGAL_HOURS))
    def test_each_hos_field_reaches_the_service(self, client, created, field):
        c, _ = client
        assert _create(c, **LEGAL_HOURS).status_code == 200
        assert created[0][field] == LEGAL_HOURS[field], (
            f"{field} was accepted and discarded. `check_compliance` needs it, and "
            f"`dispatch_shipment` refuses a driver it cannot assess."
        )

    def test_the_dq_file_flag_reaches_the_service(self, client, created):
        c, _ = client
        _create(c, dq_file_complete=True)
        assert created[0]["dq_file_complete"] is True

    def test_the_active_flag_reaches_the_service(self, client, created):
        """Dropped too, so a driver created as inactive was stored active."""
        c, _ = client
        _create(c, is_active=False)
        assert created[0]["is_active"] is False


class TestTheVerdictTheDispatcherWillRead:
    """The round trip through the reader (rule 144), not the hand-off.

    Asserting the fields were passed proves nothing about whether the driver can be
    dispatched — that is `check_compliance`'s answer, so these run it.
    """

    @staticmethod
    def _verdict(stored: dict):
        """`check_compliance` reads more of a driver than `create_driver` is handed — an id
        for its report, a medical certificate for the expiry check. Supplying only the create
        kwargs raises AttributeError, which would look like a failing assertion rather than an
        incomplete stand-in.
        """
        row = {
            "id": uuid.uuid4(),
            "medical_cert_expires": datetime(2027, 1, 1, tzinfo=timezone.utc),
            **stored,
        }
        return HOSComplianceMonitor().check_compliance(SimpleNamespace(**row))

    def test_a_driver_created_with_legal_hours_can_be_assessed(self, client, created):
        """THE DEFECT. With the hours dropped this answered "cannot be assessed" and the
        driver was undispatchable for the life of the record."""
        c, _ = client
        _create(c, **LEGAL_DRIVER)
        verdict = self._verdict(created[0])
        assert not verdict["missing_data"], (
            f"a driver created with full hours still reports {verdict['missing_data']}. "
            f"`dispatch_shipment` refuses on that, so this driver can never take a load."
        )
        assert verdict["is_compliant"]

    def test_a_driver_created_without_hours_is_still_unassessable(self, client, created):
        """The other half, and it must keep working: absence has to stay visible. FS-421 —
        `float(x or 0)` turns "never reported" into "has driven zero hours", which reads as a
        fresh legal driver and is the reason the missing-data list exists."""
        c, _ = client
        _create(c)
        verdict = self._verdict(created[0])
        assert verdict["missing_data"]
        assert not verdict["is_compliant"]

    def test_a_driver_over_the_limit_is_still_refused(self, client, created):
        """And storing the hours must not make everyone dispatchable — a driver at 11 drive
        hours is in violation, and the fix would be worse than the defect if it hid that."""
        c, _ = client
        _create(c, **{**LEGAL_DRIVER, "hos_drive_hours_today": 11.5})
        verdict = self._verdict(created[0])
        assert verdict["violations"]
        assert not verdict["is_compliant"]

    def test_missing_only_the_cycle_hours_is_still_unassessable(self, client, created):
        """`hos_cycle_hours` is the field with NO writer outside the demo seeder, so it is the
        one that decided this in practice: drive and on-duty hours could arrive from the ELD
        webhook, and the cycle figure never could."""
        c, _ = client
        _create(c, **{k: v for k, v in LEGAL_DRIVER.items() if k != "hos_cycle_hours"})
        assert "No cycle hours reported" in self._verdict(created[0])["missing_data"]
