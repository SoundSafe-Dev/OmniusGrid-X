"""Fourteen create endpoints let the caller name the tenant they wrote to.

Every one had the same line:

    organization_id=data.organization_id

`data` is the request body. So a caller could file a carrier, driver, shipment, route, load
plan, freight charge, vehicle, trailer, dock appointment, yard move, wait-time record,
checkpoint or load-quality issue under **any organisation they named**.

The shape had already been removed by hand six times — the yard list, dock doors, dock
schedule, maintenance schedule, geofence zones and the dashboard overview each carry a comment
saying *"From the TOKEN, never the payload"* — and fourteen more instances were still there.
Six fixes and no guard is the definition of a class that comes back;
`test_no_handler_takes_its_tenant_from_the_body.py` is now that guard, and it walks the AST so
it can tell `organization_id=organization_id` from `organization_id=data.organization_id`,
which differ only in the value expression.

THIS FILE IS THE BEHAVIOURAL HALF. The guard proves no handler has the shape; these prove that
two representative endpoints — one per router — actually write the caller's own tenant when a
body asks for someone else's. A structural check and a behavioural one fail for different
reasons, and this session has been repeatedly reminded that passing the first says nothing
about the second.

WHY THE SCHEMA STILL REQUIRES THE FIELD. `CarrierCreate` and friends still declare
`organization_id`, so an existing client keeps sending one and it is now ignored. Making it
optional is a separate change with every reader of those models to check first — and an ignored
field is a far smaller problem than an honoured one.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio

CARRIERS = "/api/v1/transportation/carriers"
TRAILERS = "/api/v1/yard/trailers/checkin"


def _owner(admin_sync_url, table, row_id):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT organization_id FROM {table} WHERE id = %s", (str(row_id),)
            )
            row = cur.fetchone()
        return str(row[0]) if row and row[0] else None
    finally:
        conn.close()


def _drop(admin_sync_url, table, row_id):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {table} WHERE id = %s", (str(row_id),))
    conn.close()


class TestCarrierCreate:
    async def test_the_row_belongs_to_the_caller(
        self, client_a, seeded_orgs, admin_sync_url
    ):
        """The positive control: a create with the caller's own org must still work."""
        body = {
            "carrier_name": f"Carrier {uuid4().hex[:6]}",
            "organization_id": str(seeded_orgs["org_a_id"]),
        }
        response = await client_a.post(CARRIERS, json=body)
        assert response.status_code in (200, 201), response.text
        row_id = response.json()["id"]
        try:
            assert _owner(admin_sync_url, "carriers", row_id) == str(seeded_orgs["org_a_id"])
        finally:
            _drop(admin_sync_url, "carriers", row_id)

    async def test_a_body_naming_another_tenant_is_ignored(
        self, client_a, seeded_orgs, admin_sync_url
    ):
        """THE ASSERTION THIS FILE EXISTS FOR. Org A creates a carrier while asking for it to
        belong to org B."""
        body = {
            "carrier_name": f"Carrier {uuid4().hex[:6]}",
            "organization_id": str(seeded_orgs["org_b_id"]),
        }
        response = await client_a.post(CARRIERS, json=body)
        assert response.status_code in (200, 201), response.text
        row_id = response.json()["id"]
        try:
            owner = _owner(admin_sync_url, "carriers", row_id)
            assert owner == str(seeded_orgs["org_a_id"]), (
                "the caller chose its tenant from the request body"
            )
            assert owner != str(seeded_orgs["org_b_id"])
        finally:
            _drop(admin_sync_url, "carriers", row_id)

    async def test_the_other_tenant_cannot_see_it(
        self, client_a, client_b, seeded_orgs, admin_sync_url
    ):
        """The half that makes the above mean something: if the row had landed in org B, org B
        would be able to read it. Asserting only the column would miss a table nobody
        scopes."""
        body = {
            "carrier_name": f"Carrier {uuid4().hex[:6]}",
            "organization_id": str(seeded_orgs["org_b_id"]),
        }
        row_id = (await client_a.post(CARRIERS, json=body)).json()["id"]
        try:
            listed = await client_b.get(CARRIERS, params={"limit": 500})
            assert listed.status_code == 200, listed.text
            body_b = listed.json()
            rows = body_b["items"] if isinstance(body_b, dict) else body_b
            assert not any(str(c.get("id")) == row_id for c in rows)
        finally:
            _drop(admin_sync_url, "carriers", row_id)


class TestYardTrailerCheckIn:
    """A second router, because the fix was applied file by file and one green endpoint says
    nothing about the other thirteen."""

    async def test_a_body_naming_another_tenant_is_ignored(
        self, client_a, seeded_orgs, admin_sync_url
    ):
        body = {
            "trailer_number": f"TR-{uuid4().hex[:6]}",
            "organization_id": str(seeded_orgs["org_b_id"]),
        }
        response = await client_a.post(TRAILERS, json=body)
        assert response.status_code in (200, 201), response.text
        row_id = response.json()["id"]
        try:
            owner = _owner(admin_sync_url, "yard_trailers", row_id)
            assert owner == str(seeded_orgs["org_a_id"])
        finally:
            _drop(admin_sync_url, "yard_trailers", row_id)

    async def test_the_caller_can_read_it_back(
        self, client_a, seeded_orgs, admin_sync_url
    ):
        """A row written under the wrong tenant is one the creator cannot find, and a 200 with
        an id is indistinguishable from success until somebody looks for it."""
        body = {
            "trailer_number": f"TR-{uuid4().hex[:6]}",
            "organization_id": str(seeded_orgs["org_b_id"]),
        }
        row_id = (await client_a.post(TRAILERS, json=body)).json()["id"]
        try:
            listed = await client_a.get("/api/v1/yard/trailers", params={"limit": 500})
            assert listed.status_code == 200, listed.text
            body_a = listed.json()
            rows = body_a["items"] if isinstance(body_a, dict) else body_a
            assert any(str(t.get("id")) == row_id for t in rows), (
                "the trailer was created and its creator cannot see it — it landed in "
                "another tenant, or in none"
            )
        finally:
            _drop(admin_sync_url, "yard_trailers", row_id)
