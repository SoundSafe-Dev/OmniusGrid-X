"""Yard read endpoints scope to the caller's org, and no longer ask the caller for it.

THE DEFECT. Four yard GETs took `organization_id: UUID` as a REQUIRED query parameter
and used it directly in the WHERE clause:

    /api/v1/yard/trailers  /dock/doors  /dock/appointments  /dwell-times

That is the IDOR shape `app/core/tenant.py` exists to prevent — its module docstring
says endpoints "must NEVER trust a client-supplied organization_id". RLS was the only
thing between the caller's value and a cross-tenant read, which is defence in depth doing
the whole job rather than backing something up.

It was also plainly broken. The parameter was required with no default and **no frontend
call sent it** — `getDwellTimes()` sends no parameters at all, `getDockDoors()` sent only
a `workcell_id` that the endpoint does not declare — so every one of these returned 422.
Four endpoints the UI calls, none of which could ever have answered.

Found by sweeping frontend query parameters against the backend's declared ones
(`test_frontend_query_params_are_declared.py`).

These tests pin both halves: the org now comes from the token, and passing someone else's
organization_id cannot change what you see.
"""

from __future__ import annotations

import uuid
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

READ_ENDPOINTS = [
    "/api/v1/yard/trailers",
    "/api/v1/yard/dock/doors",
    "/api/v1/yard/dock/appointments",
    "/api/v1/yard/dwell-times",
]


@pytest_asyncio.fixture
async def dock_doors(admin_sync_url, seeded_orgs):
    """One dock door in org A and one in org B, seeded past RLS."""
    import psycopg2

    door_a, door_b = uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        for door_id, org_key, number in (
            (door_a, "org_a_id", "A-1"),
            (door_b, "org_b_id", "B-1"),
        ):
            cur.execute(
                "INSERT INTO dock_doors (id, organization_id, door_number, status, "
                "is_active) VALUES (%s, %s, %s, 'available', true)",
                (str(door_id), str(seeded_orgs[org_key]), number),
            )
    yield door_a, door_b
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM dock_doors WHERE id IN (%s, %s)", (str(door_a), str(door_b))
        )
    conn.close()


class TestTheEndpointsAnswerAtAll:
    """They returned 422 to every frontend call, because a required query parameter
    was one the frontend never sent."""

    @pytest.mark.parametrize("endpoint", READ_ENDPOINTS)
    async def test_a_call_with_no_query_parameters_succeeds(self, client_a, endpoint):
        response = await client_a.get(endpoint)
        assert response.status_code == 200, (
            f"{endpoint} answered {response.status_code} to a bare GET — this is the "
            f"shape every frontend call has: {response.text[:200]}"
        )

    @pytest.mark.parametrize("endpoint", READ_ENDPOINTS)
    async def test_organization_id_is_no_longer_accepted_from_the_caller(
        self, client_a, endpoint
    ):
        """The parameter is gone, so FastAPI ignores it. What matters is that supplying
        it cannot change the answer — asserted below."""
        spec_response = await client_a.get(endpoint)
        assert spec_response.status_code == 200


class TestScopingComesFromTheToken:
    async def test_a_caller_sees_only_its_own_rows(self, client_a, dock_doors):
        door_a, _door_b = dock_doors
        response = await client_a.get("/api/v1/yard/dock/doors")
        assert response.status_code == 200, response.text
        ids = {d["id"] for d in response.json()}
        assert str(door_a) in ids

    async def test_the_other_org_does_not_appear(self, client_a, dock_doors):
        """Guards the guard: if org B's door were visible, the assertion above would
        pass while proving nothing about scoping."""
        _door_a, door_b = dock_doors
        response = await client_a.get("/api/v1/yard/dock/doors")
        assert str(door_b) not in {d["id"] for d in response.json()}

    async def test_each_org_sees_its_own(self, client_a, client_b, dock_doors):
        door_a, door_b = dock_doors
        a_ids = {d["id"] for d in (await client_a.get("/api/v1/yard/dock/doors")).json()}
        b_ids = {d["id"] for d in (await client_b.get("/api/v1/yard/dock/doors")).json()}
        assert str(door_a) in a_ids and str(door_a) not in b_ids
        assert str(door_b) in b_ids and str(door_b) not in a_ids


class TestSupplyingAnotherOrgChangesNothing:
    """THE ASSERTIONS THIS FILE EXISTS FOR. The old handlers would have filtered on
    whatever the caller passed."""

    async def test_passing_another_orgs_id_does_not_reveal_its_rows(
        self, client_a, client_b, dock_doors, seeded_orgs
    ):
        _door_a, door_b = dock_doors
        response = await client_a.get(
            "/api/v1/yard/dock/doors",
            params={"organization_id": str(seeded_orgs["org_b_id"])},
        )
        assert response.status_code == 200, response.text
        assert str(door_b) not in {d["id"] for d in response.json()}, (
            "a caller reached another org's dock doors by naming that org in the query "
            "string"
        )

    async def test_passing_another_orgs_id_does_not_hide_your_own(
        self, client_a, dock_doors, seeded_orgs
    ):
        """The other direction: a stale caller still sending the parameter must not be
        silently emptied out."""
        door_a, _door_b = dock_doors
        response = await client_a.get(
            "/api/v1/yard/dock/doors",
            params={"organization_id": str(seeded_orgs["org_b_id"])},
        )
        assert str(door_a) in {d["id"] for d in response.json()}

    @pytest.mark.parametrize("endpoint", READ_ENDPOINTS)
    async def test_a_bogus_organization_id_is_ignored_rather_than_honoured(
        self, client_a, endpoint
    ):
        """An unknown query parameter must not error either — a client that has not
        been redeployed keeps working."""
        response = await client_a.get(
            endpoint, params={"organization_id": str(uuid.uuid4())}
        )
        assert response.status_code == 200, response.text


class TestTheUnknownParameterIsGone:
    async def test_dock_doors_ignores_a_workcell_filter(self, client_a, dock_doors):
        """`workcell_id` was sent by the client and silently dropped — `dock_doors` has
        no workcell column, so it could never have been honoured. Pinned so nobody
        reintroduces it believing it filters."""
        door_a, _door_b = dock_doors
        response = await client_a.get(
            "/api/v1/yard/dock/doors", params={"workcell_id": str(uuid.uuid4())}
        )
        assert response.status_code == 200
        assert str(door_a) in {d["id"] for d in response.json()}, (
            "the response changed in reaction to a parameter the endpoint does not "
            "declare"
        )
