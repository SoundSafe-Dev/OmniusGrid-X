"""Logistics-correlation reads must answer, and scope to the token.

THE DEFECT, two of them stacked. `dock_appointments` is RLS-protected and all 12
handlers ran on `get_db`, so the policy matched nothing and every endpoint returned an
empty result — even though the handlers filtered on `organization_id` themselves. A
correct application-layer filter is no help once RLS has removed the row; the same
lesson as `gdpr.py`.

Nine handlers ALSO took `organization_id` as a **required client-supplied query
parameter** — the IDOR shape `app/core/tenant.py` forbids, and a 422 for any client that
omitted it. Both are fixed: the session is tenant-bound and the org comes from the token.

WHAT IS NOT FIXED, AND IS NOT AN OVERSIGHT. This router declares `prefix="/logistics"`
while `main.py` mounts it at `/api/v1/logistics`, so every route serves at
`/api/v1/logistics/logistics/...`. That is the double-prefix bug already corrected in the
yard and transportation routers, and it is why the paths below look wrong. Correcting it
would collide with `fleet_logistics.logistics_router`, which serves `/delivery-efficiency`
and `/compliance/summary` at the single prefix — the two paths the frontend actually
calls. Since this router registers first, it would silently win and change the payload
the frontend receives. Picking a canonical implementation per path is a product decision,
so the tests below use the real (doubled) paths rather than pretending otherwise.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/logistics/logistics"


@pytest_asyncio.fixture
async def appointment(admin_sync_url, seeded_orgs):
    import psycopg2

    appt_a, door_a = uuid.uuid4(), uuid.uuid4()
    appt_b, door_b = uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        for appt, door, org_key in (
            (appt_a, door_a, "org_a_id"),
            (appt_b, door_b, "org_b_id"),
        ):
            org = str(seeded_orgs[org_key])
            cur.execute(
                "INSERT INTO dock_doors (id, organization_id, door_number, status, "
                "is_active) VALUES (%s, %s, 'D1', 'available', true)", (str(door), org))
            cur.execute(
                "INSERT INTO dock_appointments (id, organization_id, dock_door_id, "
                "scheduled_start, scheduled_end, status) "
                "VALUES (%s, %s, %s, %s, %s, 'scheduled')",
                (str(appt), org, str(door), now + timedelta(hours=1), now + timedelta(hours=2)))
    yield appt_a, appt_b
    with conn.cursor() as cur:
        for appt, door in ((appt_a, door_a), (appt_b, door_b)):
            cur.execute("DELETE FROM dock_appointments WHERE id = %s", (str(appt),))
            cur.execute("DELETE FROM dock_doors WHERE id = %s", (str(door),))
    conn.close()


class TestTheEndpointsAnswerWithoutAClientOrg:
    """They were 422 without the parameter and empty with it."""

    @pytest.mark.parametrize("path", [
        "/correlation-dashboard",
        "/dock-production-sync",
        "/detention-risk/upcoming",
        "/liability/costs",
    ])
    async def test_a_bare_call_succeeds(self, client_a, appointment, path):
        response = await client_a.get(f"{BASE}{path}")
        assert response.status_code == 200, (
            f"{path} -> {response.status_code}: {response.text[:200]}"
        )


class TestTheCallersOwnDataIsVisible:
    async def test_the_seeded_appointment_is_analysed(self, client_a, appointment):
        """THE ASSERTION THIS FILE EXISTS FOR: the row was invisible, so this counted 0."""
        response = await client_a.get(f"{BASE}/detention-risk/upcoming")
        assert response.status_code == 200, response.text
        assert response.json()["appointments_analyzed"] >= 1, (
            "the caller's own appointment was not analysed — the endpoint is still "
            "seeing nothing"
        )


class TestScopingComesFromTheToken:
    async def test_another_orgs_appointment_is_not_analysed(self, client_b, appointment):
        """Org B has exactly one appointment of its own; if scoping were broken it
        would see two."""
        response = await client_b.get(f"{BASE}/detention-risk/upcoming")
        assert response.status_code == 200, response.text
        assert response.json()["appointments_analyzed"] == 1

    async def test_naming_another_org_changes_nothing(
        self, client_a, appointment, seeded_orgs
    ):
        """The parameter is gone, so it is ignored — but a stale client sending it must
        neither reach another tenant nor lose its own data."""
        response = await client_a.get(
            f"{BASE}/detention-risk/upcoming",
            params={"organization_id": str(seeded_orgs["org_b_id"])},
        )
        assert response.status_code == 200, response.text
        assert response.json()["appointments_analyzed"] == 1
