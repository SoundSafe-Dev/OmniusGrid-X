"""The fourteen endpoints FS-523 unblocked actually write a row (FS-526).

FS-523 removed a required `organization_id` that fourteen create endpoints demanded and their
handlers discarded. That makes them **callable**. It does not make them **work** — and the
difference matters, because the whole reason this was invisible is that nobody had ever driven
one of these to a 2xx.

`test_write_endpoints_reject_cleanly_realdb.py` is the negative twin: it POSTs an empty body
everywhere and asserts 422 rather than 500. A route can satisfy that and still be broken for
every real payload. This is the positive half — a minimal valid body per endpoint, and three
questions the negative walk cannot ask:

  1. does it answer 2xx,
  2. is a row actually there afterwards, and
  3. **does the row carry the caller's organisation** — the field that was just removed from
     the request, which means the server is now the only thing that can supply it.

(3) is the one that would be silently wrong. Removing a field from a request schema and
forgetting that some path still read it produces a row with a null tenant: invisible to its
own creator through any scoped read, and swept up by anything scanning the table unscoped.
`test_no_handler_takes_its_tenant_from_the_body.py` opens with exactly that description of the
defect it was written for.

WHY NOT ALL FOURTEEN. Five are covered by `test_yard_write_routes_change_state_realdb.py`,
which asserts the transition rather than just the row. This file takes the rest: all six
transportation creates, `POST /assets`, and the load-quality log — plus the negative case for
the 500 that FS-523's fix surfaced, and one proving a body-supplied tenant is still ignored.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


@pytest_asyncio.fixture
async def create_prerequisites(admin_sync_url, seeded_orgs):
    """The rows the eight creates below point at: an asset type, an asset, a carrier."""
    org = str(seeded_orgs["org_a_id"])
    # `assets.workcell_id` is NOT NULL and `AssetCreate` already requires it — correctly.
    # The first version of this fixture omitted it and hit the constraint, which looked
    # briefly like the FS-523 defect and was this file's own bug. Recorded because the
    # distinction is the whole point: a required field over a NOT NULL column is right, and
    # only an OPTIONAL one over a NOT NULL column is the 500.
    ids = {"asset_type": uuid.uuid4(), "asset": uuid.uuid4(), "workcell": uuid.uuid4()}
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'machine') "
            "ON CONFLICT DO NOTHING",
            (str(ids["asset_type"]), f"FS526-{uuid.uuid4().hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO workcells (id, organization_id, name) VALUES (%s, %s, 'FS526 Cell')",
            (str(ids["workcell"]), org),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, asset_type_id, workcell_id, name, "
            "is_active) VALUES (%s, %s, %s, %s, 'FS526 Asset', true)",
            (str(ids["asset"]), org, str(ids["asset_type"]), str(ids["workcell"])),
        )
    yield ids
    with conn.cursor() as cur:
        cur.execute("DELETE FROM load_quality_logs WHERE asset_id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM assets WHERE name = 'FS526 Created Asset'")
        cur.execute("DELETE FROM drivers WHERE last_name = 'FS526'")
        cur.execute("DELETE FROM freight_charges WHERE charge_type = 'FS526'")
        cur.execute(
            "DELETE FROM freight_charges WHERE shipment_id IN "
            "(SELECT id FROM shipments WHERE shipment_number = 'FS526-SHIP')"
        )
        cur.execute(
            "DELETE FROM load_plans WHERE shipment_id IN "
            "(SELECT id FROM shipments WHERE shipment_number = 'FS526-SHIP')"
        )
        cur.execute("DELETE FROM routes WHERE route_name = 'FS526 Route'")
        cur.execute("DELETE FROM shipments WHERE shipment_number = 'FS526-SHIP'")
        cur.execute("DELETE FROM carriers WHERE carrier_name = 'FS526 Carrier'")
        cur.execute("DELETE FROM workcells WHERE id = %s", (str(ids["workcell"]),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(ids["asset_type"]),))
    conn.close()


def _row_org(admin_sync_url, table: str, row_id) -> object:
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(f"SELECT organization_id FROM {table} WHERE id = %s", (str(row_id),))
        row = cur.fetchone()
    conn.close()
    return row[0] if row else None


async def _create(client, path: str, body: dict) -> dict:
    response = await client.post(path, json=body)
    assert response.status_code in (200, 201), (
        f"POST {path} answered {response.status_code} for a minimal valid body that omits "
        f"organization_id — which is exactly what FS-523 made possible and what the frontend "
        f"sends.\n{response.text}"
    )
    return response.json()


@pytest.mark.realdb
class TestTheCreatesSucceedWithoutATenantInTheBody:
    """Each writes a row and each row carries the caller's org, supplied by the server."""

    async def test_an_asset_can_be_created(
        self, client_a, admin_sync_url, seeded_orgs, create_prerequisites
    ):
        """`POST /assets` is the core create path of the product and was answering 422."""
        created = await _create(
            client_a,
            "/api/v1/assets/",
            {
                "name": "FS526 Created Asset",
                "asset_type_id": str(create_prerequisites["asset_type"]),
                "workcell_id": str(create_prerequisites["workcell"]),
            },
        )
        assert str(_row_org(admin_sync_url, "assets", created["id"])) == str(
            seeded_orgs["org_a_id"]
        ), (
            "the asset was created with a different organisation than the caller's. The "
            "request no longer carries one, so the server is the only thing that can supply "
            "it — a null or wrong value here is a row invisible to its own creator."
        )

    async def test_a_carrier_can_be_created(self, client_a, admin_sync_url, seeded_orgs):
        created = await _create(
            client_a,
            "/api/v1/transportation/carriers",
            {"carrier_name": "FS526 Carrier", "scac_code": "FS26"},
        )
        assert str(_row_org(admin_sync_url, "carriers", created["id"])) == str(
            seeded_orgs["org_a_id"]
        )

    async def test_a_driver_can_be_created(self, client_a, admin_sync_url, seeded_orgs):
        created = await _create(
            client_a,
            "/api/v1/transportation/drivers",
            {"first_name": "Pat", "last_name": "FS526"},
        )
        assert str(_row_org(admin_sync_url, "drivers", created["id"])) == str(
            seeded_orgs["org_a_id"]
        )

    async def test_a_shipment_can_be_created(self, client_a, admin_sync_url, seeded_orgs):
        created = await _create(
            client_a,
            "/api/v1/transportation/shipments",
            {
                "shipment_number": "FS526-SHIP",
                "origin_address": {"city": "Detroit"},
                "destination_address": {"city": "Toledo"},
            },
        )
        assert str(_row_org(admin_sync_url, "shipments", created["id"])) == str(
            seeded_orgs["org_a_id"]
        )

    async def test_a_route_can_be_created(self, client_a, admin_sync_url, seeded_orgs):
        created = await _create(
            client_a,
            "/api/v1/transportation/routes",
            {
                "route_name": "FS526 Route",
                "origin": {"city": "Detroit"},
                "destination": {"city": "Toledo"},
            },
        )
        assert str(_row_org(admin_sync_url, "routes", created["id"])) == str(
            seeded_orgs["org_a_id"]
        )

    async def test_a_load_plan_and_a_freight_charge_can_be_created(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """Both hang off a shipment, so they are created against one made through the API —
        which also proves the id a create returns is usable as a foreign key, and not merely
        echoed back."""
        shipment = await _create(
            client_a,
            "/api/v1/transportation/shipments",
            {
                "shipment_number": "FS526-SHIP",
                "origin_address": {"city": "Detroit"},
                "destination_address": {"city": "Toledo"},
            },
        )

        plan = await _create(
            client_a,
            "/api/v1/transportation/load-plans",
            {"shipment_id": shipment["id"], "space_utilization_percent": 82.5},
        )
        assert str(_row_org(admin_sync_url, "load_plans", plan["id"])) == str(
            seeded_orgs["org_a_id"]
        )

        charge = await _create(
            client_a,
            "/api/v1/transportation/freight-charges",
            {"shipment_id": shipment["id"], "charge_type": "FS526", "amount": 1250.00},
        )
        assert str(_row_org(admin_sync_url, "freight_charges", charge["id"])) == str(
            seeded_orgs["org_a_id"]
        )

    async def test_a_load_quality_log_can_be_created(
        self, client_a, admin_sync_url, seeded_orgs, create_prerequisites
    ):
        """Also the endpoint whose 500 FS-523 surfaced: `asset_id` is NOT NULL and was
        declared Optional, so an omitted one reached the INSERT."""
        created = await _create(
            client_a,
            "/api/v1/logistics/load-quality",
            {
                "asset_id": str(create_prerequisites["asset"]),
                "defect_type": "damaged",
                "severity": "major",
                "quantity_affected": 3,
            },
        )
        assert str(_row_org(admin_sync_url, "load_quality_logs", created["id"])) == str(
            seeded_orgs["org_a_id"]
        )

    async def test_a_load_quality_log_without_an_asset_is_a_422(self, client_a):
        """The other half of that fix. It must be a 422 naming the field, not a 500 —
        `nullable=False` with no default means the INSERT is going to fail either way, and
        only one of those answers tells the caller what to do."""
        response = await client_a.post(
            "/api/v1/logistics/load-quality",
            json={"defect_type": "damaged", "severity": "major"},
        )
        assert response.status_code == 422, (
            f"omitting asset_id answered {response.status_code}; the column is NOT NULL with "
            f"no default, so this reaches the INSERT and raises NotNullViolationError — a "
            f"500 the caller cannot act on"
        )
        assert "asset_id" in response.text, (
            "the 422 does not name asset_id, so the caller still has to guess"
        )


@pytest.mark.realdb
class TestATenantCannotBeChosenByTheCaller:
    """The removal must not have left a path that still honours a body value."""

    async def test_a_body_organization_id_is_ignored(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """Pydantic drops the extra key, so this should file under org A regardless. Asserted
        rather than assumed: `model_config` could gain `extra="allow"` and a handler could
        start reading `data.organization_id` again, which is the IDOR shape
        `app/core/tenant.py` exists to forbid."""
        created = await _create(
            client_a,
            "/api/v1/transportation/carriers",
            {
                "carrier_name": "FS526 Carrier",
                "scac_code": "FS27",
                "organization_id": str(seeded_orgs["org_b_id"]),
            },
        )
        assert str(_row_org(admin_sync_url, "carriers", created["id"])) == str(
            seeded_orgs["org_a_id"]
        ), (
            "a caller in org A named org B in the body and the row landed there. The field "
            "is supposed to be discarded entirely — this is the exact defect "
            "test_no_handler_takes_its_tenant_from_the_body.py was written for."
        )
