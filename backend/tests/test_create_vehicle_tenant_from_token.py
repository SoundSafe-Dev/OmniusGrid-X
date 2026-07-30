"""`POST /transportation/vehicles` took the tenant from the request body.

    organization_id=payload.get("organization_id")

That is the IDOR shape this codebase forbids. It has already been removed from the yard
trailer, dock door, dock schedule, maintenance schedule and geofence handlers — each carries a
comment saying "From the TOKEN, never the payload" — and every other handler in
`transportation.py` already depends on `get_tenant_org_id`. Only the vehicle create missed it,
which is why nothing noticed: the file reads as though it had been done.

TWO WAYS IT WAS WRONG.

**A caller could file a vehicle under any organisation they named, and here it WORKED.**
This is the sharp part, and it took measuring to find: of the fourteen handlers with this
shape, thirteen write to tables with row-level security enabled, where a FOR ALL policy's
USING clause acts as the INSERT's WITH CHECK — so the database refused the cross-tenant write
and the caller got a 500. Bad error handling, not a breach.

`vehicles` is the exception. `pg_class.relrowsecurity` is **false** for it: migration 051's
loop does not cover it, so nothing stood between the request body and the row. A create naming
another organisation succeeded, and the mutation test below confirms it — reverting the fix
makes the row land in org B.

Which is the argument against leaning on RLS at all. Thirteen handlers were wrong and survived
because a policy caught them; the fourteenth was wrong in exactly the same way and shipped the
defect, and nothing about the handler said which was which.

**And it broke on an absent field.** `payload.get` returns None, and a vehicle with no
organisation belongs to no tenant at all — invisible to its own creator through any scoped
read, and collected by anything that scans the table unscoped. No error, no row anyone can
find; the endpoint returns 200 with an id.

FOUND BY COUNTING UNVALIDATED BODIES. Twelve route handlers take `payload: dict` or
`Dict[str, Any]` with no schema, so nothing checks what they accept or ignore — the surface
where the maintenance-schedule `priority` was silently discarded. The request-model sweep next
door cannot see any of them, which is worth remembering when that sweep comes back clean.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio

VEHICLES = "/api/v1/transportation/vehicles"


async def _created_org(admin_sync_url, vehicle_id):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT organization_id FROM vehicles WHERE id = %s", (str(vehicle_id),)
            )
            row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _cleanup(admin_sync_url, number):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vehicles WHERE vehicle_number = %s", (number,))
    conn.close()


class TestTheTenantComesFromTheToken:
    async def test_a_vehicle_lands_in_the_callers_organisation(
        self, client_a, seeded_orgs, admin_sync_url
    ):
        """The positive control, and the property: the row must be the caller's."""
        number = f"TRK-{uuid4().hex[:6]}"
        try:
            response = await client_a.post(VEHICLES, json={"vehicleNumber": number})
            assert response.status_code == 200, response.text
            owner = await _created_org(admin_sync_url, response.json()["id"])
            assert str(owner) == str(seeded_orgs["org_a_id"])
        finally:
            _cleanup(admin_sync_url, number)

    async def test_a_body_naming_another_organisation_is_ignored(
        self, client_a, seeded_orgs, admin_sync_url
    ):
        """THE ASSERTION THIS FILE EXISTS FOR. Org A files a vehicle while asking for it to
        belong to org B. The request must succeed and the row must be org A's — refusing
        would be defensible too, but silently honouring the body is what it used to do."""
        number = f"TRK-{uuid4().hex[:6]}"
        try:
            response = await client_a.post(
                VEHICLES,
                json={
                    "vehicleNumber": number,
                    "organization_id": str(seeded_orgs["org_b_id"]),
                },
            )
            assert response.status_code == 200, response.text
            owner = await _created_org(admin_sync_url, response.json()["id"])
            assert str(owner) == str(seeded_orgs["org_a_id"]), (
                "the caller chose its own tenant from the request body"
            )
            assert str(owner) != str(seeded_orgs["org_b_id"])
        finally:
            _cleanup(admin_sync_url, number)

    async def test_an_absent_organisation_does_not_orphan_the_row(
        self, client_a, seeded_orgs, admin_sync_url
    ):
        """`payload.get` returned None for a body that simply omitted the field, and a
        vehicle with no organisation belongs to nobody — invisible to its creator through any
        scoped read, and swept up by anything that scans the table unscoped."""
        number = f"TRK-{uuid4().hex[:6]}"
        try:
            response = await client_a.post(VEHICLES, json={"vehicleNumber": number})
            assert response.status_code == 200, response.text
            owner = await _created_org(admin_sync_url, response.json()["id"])
            assert owner is not None, "the vehicle was created with no organisation at all"
        finally:
            _cleanup(admin_sync_url, number)


class TestTheRowIsReachableAfterwards:
    async def test_the_caller_can_read_back_what_it_created(
        self, client_a, admin_sync_url
    ):
        """The check that makes the others mean something. A row written under the wrong
        tenant — or none — is one the creator cannot find, and 'created successfully' plus an
        id is indistinguishable from a working endpoint until somebody looks for the row."""
        number = f"TRK-{uuid4().hex[:6]}"
        try:
            created = await client_a.post(VEHICLES, json={"vehicleNumber": number})
            assert created.status_code == 200, created.text
            listed = await client_a.get(VEHICLES, params={"limit": 500})
            assert listed.status_code == 200, listed.text
            body = listed.json()
            rows = body["items"] if isinstance(body, dict) else body
            assert any(v["id"] == created.json()["id"] for v in rows), (
                "the vehicle was created and the creator cannot see it"
            )
        finally:
            _cleanup(admin_sync_url, number)

    async def test_another_tenant_cannot_see_it(self, client_a, client_b, admin_sync_url):
        """The other half: org A's vehicle must not appear in org B's list. Without this,
        'the row is the caller's' is satisfied by a table nobody scopes at all."""
        number = f"TRK-{uuid4().hex[:6]}"
        try:
            created = await client_a.post(VEHICLES, json={"vehicleNumber": number})
            assert created.status_code == 200, created.text
            listed = await client_b.get(VEHICLES, params={"limit": 500})
            body = listed.json()
            rows = body["items"] if isinstance(body, dict) else body
            assert not any(v["id"] == created.json()["id"] for v in rows)
        finally:
            _cleanup(admin_sync_url, number)


class TestTheRequiredFieldIsStillRequired:
    async def test_a_vehicle_with_no_number_is_refused(self, client_a):
        """The negative control. Accepting anything would satisfy every test above and lose
        the endpoint's only validation."""
        response = await client_a.post(VEHICLES, json={})
        assert response.status_code == 400, response.text
