"""Dispatching a shipment (FS-420, FS-421).

TWO DEFECTS, EITHER OF WHICH ALONE MADE THE FEATURE UNUSABLE.

1. **It returned 422 on every call and had never worked.** The endpoint declared
   `driver_id: UUID, trailer_id: UUID` as bare parameters, which FastAPI reads as QUERY
   parameters for a POST. The client sent them in the body. Same shape as FS-379, where
   Strategic approve/reject sent `operator_id` in a body the server declared as a query
   parameter — and found the same way, by a guard comparing what the client sends against
   what the endpoint declares.

2. **The picker offered the wrong kind of thing.** The client sent `vehicle_id`, and
   `Shipment.trailer_id` is a foreign key to `yard_trailers`; a shipment has no vehicle
   column at all. So even a well-formed call would have written a vehicle id into a trailer
   FK — accepted silently by SQLite, refused by Postgres now that foreign keys are enforced.

AND ONE MORE, FOUND BY FIXING THOSE. With the transport working, the call reached the HOS
check and was refused with `Driver not compliant: ` — nothing after the colon.
`check_compliance` is careful to separate a VIOLATION (the driver has driven too long) from
MISSING DATA (nobody can tell), and the dispatch path read only `violations`. A driver
blocked for missing data produced a refusal that named no reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.transportation_management import HOSComplianceMonitor

pytestmark = pytest.mark.asyncio


class _Driver:
    """The fields `check_compliance` reads. A stand-in rather than a DB row: the subject is
    the verdict's wording, and a real Driver would drag in three parent tables."""

    def __init__(self, **kw):
        self.id = uuid.uuid4()
        self.hos_drive_hours_today = kw.get("drive", 2.0)
        self.hos_on_duty_hours_today = kw.get("on_duty", 4.0)
        self.hos_cycle_hours = kw.get("cycle", 20.0)
        self.medical_cert_expires = kw.get(
            "cert", datetime.now(timezone.utc) + timedelta(days=200)
        )


class TestTheRequestModel:
    """The transport, pinned so it cannot slip back to query parameters."""

    def test_dispatch_declares_a_json_body(self):
        from app.main import app

        spec = app.openapi()
        operation = spec["paths"]["/api/v1/transportation/shipments/{shipment_id}/dispatch"]["post"]
        body = (operation.get("requestBody") or {}).get("content", {})
        assert "application/json" in body, (
            "dispatch takes its ids as query parameters again. The client sends a body, so "
            "every call returns 422 — which is exactly how this feature spent its whole life"
        )

    def test_the_body_names_a_trailer_not_a_vehicle(self):
        from app.api.transportation import ShipmentDispatchRequest

        fields = set(ShipmentDispatchRequest.model_fields)
        assert fields == {"driver_id", "trailer_id"}, (
            f"dispatch declares {sorted(fields)}. `Shipment.trailer_id` is a foreign key to "
            f"yard_trailers and a shipment has no vehicle column, so a `vehicle_id` here "
            f"cannot be stored — Postgres refuses it once foreign keys are enforced"
        )

    def test_the_frontend_sends_what_the_body_declares(self):
        """The two sides, compared directly. This is the pairing the generic guard makes
        across the whole surface; here it is spelled out for the one that was broken."""
        import pathlib
        import re

        from app.api.transportation import ShipmentDispatchRequest

        client = (pathlib.Path(__file__).resolve().parents[2]
                  / "frontend" / "src" / "api" / "transportation.ts").read_text()
        call = re.search(r"shipments/\$\{id\}/dispatch`,\s*\{([^}]*)\}", client)
        assert call, "the dispatch call in transportation.ts no longer matches"
        sent = set(re.findall(r"([a-z_]+)\s*:", call.group(1)))
        assert sent == set(ShipmentDispatchRequest.model_fields), (
            f"the client sends {sorted(sent)} and the endpoint declares "
            f"{sorted(ShipmentDispatchRequest.model_fields)}"
        )


class TestARefusalNamesItsReason:
    """`is_compliant` is false for two different things and they need different actions."""

    def test_a_violation_is_reported(self):
        monitor = HOSComplianceMonitor()
        verdict = monitor.check_compliance(_Driver(drive=99.0))
        assert verdict["is_compliant"] is False
        assert verdict["violations"], "an over-hours driver must produce a violation"

    def test_missing_data_is_not_reported_as_a_violation(self):
        """The distinction the dispatch path used to discard."""
        monitor = HOSComplianceMonitor()
        verdict = monitor.check_compliance(_Driver(cert=None))

        assert verdict["is_compliant"] is False
        assert verdict["violations"] == [], (
            "a missing certificate is not a violation — nobody has driven too long; it is "
            "an absence of evidence, and collapsing the two is what produced a refusal "
            "with no reason after the colon"
        )
        assert verdict["missing_data"] == ["No medical certificate on file"]
        assert verdict["assessable"] is False

    async def test_dispatch_names_missing_data_in_its_error(self):
        """THE REAL CODE PATH, not a copy of it.

        A first version of this test rebuilt the message from the verdict and asserted on
        its own arithmetic — which would have passed with the service still discarding
        `missing_data`. It now calls `dispatch_shipment` and reads the error it raises.
        """
        import uuid as _uuid

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import Base, Carrier, Driver, Organization, Shipment
        from app.services.transportation_management import TransportationManagementService
        from tests._sqlite import create_all, minimal_organization, sqlite_engine

        org_id = str(_uuid.uuid4())
        driver_id, shipment_id, trailer_id = (str(_uuid.uuid4()) for _ in range(3))

        engine = sqlite_engine()
        await create_all(engine, Base.metadata, [
            Organization.__table__, Carrier.__table__, Driver.__table__, Shipment.__table__,
        ])
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            session.add(minimal_organization(org_id))
            await session.flush()
            # A driver with NO medical certificate on file: unassessable, not in violation.
            session.add(Driver(id=driver_id, organization_id=org_id,
                               first_name="A", last_name="B", license_number="L1"))
            session.add(Shipment(id=shipment_id, organization_id=org_id,
                                 shipment_number="S1", status="planned"))
            await session.commit()

        async with maker() as session:
            service = TransportationManagementService()
            with pytest.raises(ValueError) as raised:
                await service.dispatch_shipment(
                    shipment_id=shipment_id, driver_id=driver_id,
                    trailer_id=trailer_id, db=session,
                )

        message = str(raised.value)
        assert "medical certificate" in message.lower(), (
            f"the refusal does not name why: {message!r}. `missing_data` is being discarded "
            f"again, and a dispatcher is told 'not compliant' with nothing after the colon"
        )
        assert not message.rstrip().endswith(":")
        await engine.dispose()
