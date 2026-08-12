"""The writer dropped a field the reader depends on (FS-662).

`get_carrier_compliance` decides whether a carrier's C-TPAT certification and insurance are
valid like this:

    'is_valid': carrier.ctpat_certified and carrier.ctpat_expires_at
                and _as_utc(carrier.ctpat_expires_at) > now

`POST /transportation/carriers` passed `ctpat_certified` and `insurance_on_file` and **dropped
both expiry dates**. So every carrier created through the API had NULL expiries, and the
compliance endpoint reported the certification and the insurance **invalid** — whatever the
caller sent, and with a 200 on the way in.

THE THIRD INSTANCE OF ONE SHAPE TODAY, and the sharpest:

  * `POST /yard/checkpoints` stored that an inspection happened and dropped **who inspected**;
  * `POST /yard/trailers/checkin` stored **which seal** and dropped **whether it was intact**;
  * this stored **certified** and **insured** and dropped **until when**.

Each time a boolean was kept and the field bounding its validity was discarded. Here the
reader already existed and already depended on the dropped field, which is why this one is not
merely incomplete data — it is a wrong answer computed from it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import transportation as transportation_api
from app.services.transportation_management import _as_utc


@pytest.fixture
def created(monkeypatch):
    calls: list[dict] = []

    async def _create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            id=uuid.uuid4(),
            organization_id=kwargs["organization_id"],
            carrier_name=kwargs["carrier_name"],
            dot_number=kwargs.get("dot_number"),
            mc_number=kwargs.get("mc_number"),
            ctpat_certified=kwargs.get("ctpat_certified", False),
            ctpat_expires_at=kwargs.get("ctpat_expires_at"),
            insurance_on_file=kwargs.get("insurance_on_file", False),
            insurance_expires_at=kwargs.get("insurance_expires_at"),
            safety_rating=kwargs.get("safety_rating"),
            csa_score=kwargs.get("csa_score"),
            contract_rate=kwargs.get("contract_rate"),
            contact_info=kwargs.get("contact_info"),
            is_active=kwargs.get("is_active", True),
            created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
            updated_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(
        transportation_api.transportation_management_service, "create_carrier", _create
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


NEXT_YEAR = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()


def _create(client, **over):
    return client.post(
        "/api/v1/transportation/carriers",
        json={"carrier_name": "Blue Line Freight", **over},
    )


class TestTheDatesTheComplianceCheckReads:
    def test_the_ctpat_expiry_reaches_the_service(self, client, created):
        """THE DEFECT. Sent, accepted, discarded — and the compliance endpoint then reports
        the certification invalid because the date it needs is NULL."""
        c, _ = client
        assert _create(c, ctpat_certified=True, ctpat_expires_at=NEXT_YEAR).status_code == 200
        assert created[0]["ctpat_expires_at"] is not None, (
            "the C-TPAT expiry was discarded. `get_carrier_compliance` computes is_valid as "
            "`certified AND expires_at AND expires_at > now`, so the carrier reports "
            "uncertified with a 200 on the way in."
        )

    def test_the_insurance_expiry_reaches_the_service(self, client, created):
        c, _ = client
        _create(c, insurance_on_file=True, insurance_expires_at=NEXT_YEAR)
        assert created[0]["insurance_expires_at"] is not None

    def test_a_certified_carrier_now_computes_as_valid(self, client, created):
        """The round trip that makes the fix worth anything: run the SERVICE'S OWN validity
        expression over what the create path stored. Asserting only that the field was passed
        would pass for a value the reader still cannot use."""
        c, _ = client
        _create(c, ctpat_certified=True, ctpat_expires_at=NEXT_YEAR)
        stored = created[0]
        is_valid = (
            stored["ctpat_certified"]
            and stored["ctpat_expires_at"]
            and _as_utc(stored["ctpat_expires_at"]) > datetime.now(timezone.utc)
        )
        assert is_valid, "stored, and still not valid by the reader's own definition"

    def test_an_expired_certificate_still_computes_as_invalid(self, client, created):
        """The other half. Storing the date must not make everything valid — a certificate
        that expired last year has to keep reading as expired, or the fix would trade one
        wrong answer for a more dangerous one."""
        c, _ = client
        last_year = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        _create(c, ctpat_certified=True, ctpat_expires_at=last_year)
        stored = created[0]
        is_valid = (
            stored["ctpat_certified"]
            and stored["ctpat_expires_at"]
            and _as_utc(stored["ctpat_expires_at"]) > datetime.now(timezone.utc)
        )
        assert not is_valid

    def test_an_uncertified_carrier_is_not_made_valid_by_a_date(self, client, created):
        """`certified` is the first term. A date on an uncertified carrier proves nothing."""
        c, _ = client
        _create(c, ctpat_certified=False, ctpat_expires_at=NEXT_YEAR)
        stored = created[0]
        assert not (stored["ctpat_certified"] and stored["ctpat_expires_at"])

    def test_the_active_flag_reaches_the_service(self, client, created):
        """Also dropped. A carrier created as inactive was stored active."""
        c, _ = client
        _create(c, is_active=False)
        assert created[0]["is_active"] is False

    def test_a_carrier_with_no_dates_still_creates(self, client, created):
        c, _ = client
        assert _create(c).status_code == 200
        assert created[0]["ctpat_expires_at"] is None

    def test_the_tenant_still_comes_from_the_token(self, client, created):
        c, org = client
        _create(c, organization_id=str(uuid.uuid4()))
        assert created[0]["organization_id"] == org
