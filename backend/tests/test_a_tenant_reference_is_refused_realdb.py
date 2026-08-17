"""No write may name a row another tenant owns — across every wired router (FS-737).

THE BEHAVIOURAL HALF. `test_every_tenant_reference_is_registered.py` proves the registry
accounts for every id-shaped field on a request schema; it cannot prove a handler CALLS
`verify_refs`. The accounting can be perfect while a route ignores it, so this file drives
the routes over HTTP against a real database and asserts the refusal.

HOW THE POPULATION WAS FOUND, because the method matters more than the list. FS-736 closed
six task links on one router. Rather than move to the next report, the question became "how
many fields are there" — 89 id-shaped fields across 35 request models on 31 live routes. A
static triage marked 33 of them suspect, and **the triage was wrong in both directions**: it
cleared `yard:POST /trailers/checkin`, which was exploitable, because the word
`organization_id` appeared near the field, and it flagged `operations:POST /`, which is
safe, because its asset lookup runs under RLS and returns nothing for another tenant. A
proximity heuristic finds candidates and clears nothing — rule 206, written after a guard
that passed its own mutation test for the wrong reason.

So every row below was reproduced over HTTP before it was fixed. Nine cross-tenant writes
in the first sitting, all answering 200:

    yard:PUT  /trailers/{id}           carrier_id, driver_id, shipment_id, dock_door_id
    yard:PUT  /dock/doors/{id}         current_trailer_id
    yard:POST /trailers/checkin        carrier_id, driver_id, shipment_id
    transportation:PUT /shipments/{id} carrier_id, driver_id, trailer_id
    transportation:PUT /drivers/{id}   carrier_id

WHAT THE DAMAGE WAS. Not a read: RLS still hides the other tenant's rows, so the joined
name never renders. It is a row in YOUR tenant that points into somebody else's — a trailer
billed to a carrier you cannot see, a shipment assigned to a driver who is not yours, a
dock door holding a trailer that belongs to another company. Every report that groups by
one of those keys is then counting across a tenant boundary, and the id is a durable
reference to a row whose existence you have just confirmed.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

YARD = "/api/v1/yard"
TRANSPORT = "/api/v1/transportation"


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


def _seed(admin_sync_url, org) -> dict:
    """One row of each tenanted kind, owned by `org`."""
    ids = {k: uuid.uuid4() for k in ("carrier", "shipment", "door", "trailer", "driver")}
    tag = uuid.uuid4().hex[:6]
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO carriers (id, organization_id, carrier_name) VALUES (%s,%s,%s)",
            (str(ids["carrier"]), org, f"FS737-{tag}"),
        )
        cur.execute(
            "INSERT INTO shipments (id, organization_id, shipment_number, status) "
            "VALUES (%s,%s,%s,'planned')",
            (str(ids["shipment"]), org, f"FS737-{tag}"),
        )
        cur.execute(
            "INSERT INTO dock_doors (id, organization_id, door_number, status) "
            "VALUES (%s,%s,%s,'available')",
            (str(ids["door"]), org, f"FS737-{tag}"),
        )
        cur.execute(
            "INSERT INTO drivers (id, organization_id, carrier_id, first_name, last_name) "
            "VALUES (%s,%s,%s,%s,'FS737')",
            (str(ids["driver"]), org, str(ids["carrier"]), f"FS737-{tag}"),
        )
        cur.execute(
            "INSERT INTO yard_trailers (id, organization_id, trailer_number, status) "
            "VALUES (%s,%s,%s,'checked_in')",
            (str(ids["trailer"]), org, f"FS737-{tag}"),
        )
    conn.close()
    return ids


def _cleanup(admin_sync_url, ids):
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        # DETACH BEFORE DELETING. These rows point at each other by design — a shipment
        # names a trailer, a trailer names a carrier — and the tests deliberately create
        # more of them (a check-in makes a second trailer against the same carrier). Delete
        # in dependency order alone and teardown fails on a foreign key that the test
        # itself just made valid.
        cur.execute(
            "UPDATE shipments SET trailer_id = NULL, driver_id = NULL, carrier_id = NULL "
            "WHERE id = %(ship)s OR trailer_id = %(trailer)s OR driver_id = %(driver)s "
            "OR carrier_id = %(carrier)s",
            {"ship": str(ids["shipment"]), "trailer": str(ids["trailer"]),
             "driver": str(ids["driver"]), "carrier": str(ids["carrier"])},
        )
        cur.execute(
            "UPDATE yard_trailers SET carrier_id = NULL, driver_id = NULL, "
            "shipment_id = NULL, dock_door_id = NULL WHERE carrier_id = %(carrier)s "
            "OR driver_id = %(driver)s OR shipment_id = %(ship)s OR id = %(trailer)s",
            {"carrier": str(ids["carrier"]), "driver": str(ids["driver"]),
             "ship": str(ids["shipment"]), "trailer": str(ids["trailer"])},
        )
        cur.execute("UPDATE dock_doors SET current_trailer_id = NULL WHERE id = %s",
                    (str(ids["door"]),))
        cur.execute("DELETE FROM driver_wait_times WHERE driver_id = %s", (str(ids["driver"]),))
        cur.execute("DELETE FROM yard_moves WHERE trailer_id = %s", (str(ids["trailer"]),))
        cur.execute("DELETE FROM yard_checkpoints WHERE trailer_id = %s", (str(ids["trailer"]),))
        cur.execute("DELETE FROM dock_appointments WHERE dock_door_id = %s", (str(ids["door"]),))
        cur.execute("DELETE FROM freight_charges WHERE shipment_id = %s", (str(ids["shipment"]),))
        cur.execute("DELETE FROM load_plans WHERE shipment_id = %s", (str(ids["shipment"]),))
        # By tag as well as by id: the check-in tests create trailers this fixture never
        # saw, and one left behind holds a carrier row hostage.
        cur.execute("DELETE FROM yard_trailers WHERE id = %s OR trailer_number LIKE 'FS737-%%'",
                    (str(ids["trailer"]),))
        cur.execute("DELETE FROM shipments WHERE id = %s", (str(ids["shipment"]),))
        cur.execute("DELETE FROM dock_doors WHERE id = %s", (str(ids["door"]),))
        cur.execute("DELETE FROM drivers WHERE id = %s", (str(ids["driver"]),))
        cur.execute("DELETE FROM carriers WHERE id = %s", (str(ids["carrier"]),))
    conn.close()


@pytest_asyncio.fixture
async def theirs(admin_sync_url, seeded_orgs):
    ids = _seed(admin_sync_url, str(seeded_orgs["org_a_id"]))
    yield ids
    _cleanup(admin_sync_url, ids)


@pytest_asyncio.fixture
async def mine(admin_sync_url, seeded_orgs):
    ids = _seed(admin_sync_url, str(seeded_orgs["org_b_id"]))
    yield ids
    _cleanup(admin_sync_url, ids)


#: (label, method, path template, field, which seeded row the field names)
CROSS_TENANT_WRITES = [
    ("yard trailer -> carrier", "put", f"{YARD}/trailers/{{trailer}}", "carrier_id", "carrier"),
    ("yard trailer -> driver", "put", f"{YARD}/trailers/{{trailer}}", "driver_id", "driver"),
    ("yard trailer -> shipment", "put", f"{YARD}/trailers/{{trailer}}", "shipment_id", "shipment"),
    ("yard trailer -> dock door", "put", f"{YARD}/trailers/{{trailer}}", "dock_door_id", "door"),
    ("dock door -> trailer", "put", f"{YARD}/dock/doors/{{door}}", "current_trailer_id", "trailer"),
    ("shipment -> carrier", "put", f"{TRANSPORT}/shipments/{{shipment}}", "carrier_id", "carrier"),
    ("shipment -> driver", "put", f"{TRANSPORT}/shipments/{{shipment}}", "driver_id", "driver"),
    ("shipment -> trailer", "put", f"{TRANSPORT}/shipments/{{shipment}}", "trailer_id", "trailer"),
    ("driver -> carrier", "put", f"{TRANSPORT}/drivers/{{driver}}", "carrier_id", "carrier"),
]


class TestAnUpdateCannotReachAcrossTenants:
    @pytest.mark.parametrize(
        "label,method,path,field,target",
        CROSS_TENANT_WRITES,
        ids=[row[0] for row in CROSS_TENANT_WRITES],
    )
    async def test_it_is_refused(
        self, client_b, mine, theirs, label, method, path, field, target
    ):
        url = path.format(**{k: str(v) for k, v in mine.items()})
        response = await getattr(client_b, method)(url, json={field: str(theirs[target])})
        assert response.status_code == 404, (
            f"{label}: org B pointed its own row at org A's {field} and got "
            f"{response.status_code}. The row updated is org B's — RLS protects that much "
            f"— but the REFERENCE it now carries is another tenant's, and a foreign key is "
            f"checked below RLS."
        )


class TestACreateCannotReachAcrossTenants:
    async def test_a_trailer_cannot_check_in_against_a_foreign_carrier(
        self, client_b, theirs
    ):
        """The static triage cleared this route because `organization_id` appears in the
        handler — it is taken from the token, correctly, three lines from the ids that
        were not checked at all."""
        response = await client_b.post(
            f"{YARD}/trailers/checkin",
            json={
                "trailer_number": f"FS737-{uuid.uuid4().hex[:6]}",
                "carrier_id": str(theirs["carrier"]),
            },
        )
        assert response.status_code == 404, response.text[:200]

    async def test_a_shipment_cannot_be_created_against_a_foreign_driver(
        self, client_b, theirs
    ):
        response = await client_b.post(
            f"{TRANSPORT}/shipments",
            json={
                "shipment_number": f"FS737-{uuid.uuid4().hex[:6]}",
                "driver_id": str(theirs["driver"]),
            },
        )
        assert response.status_code == 404, response.text[:200]

    async def test_a_yard_move_cannot_name_a_foreign_trailer(self, client_b, theirs):
        response = await client_b.post(
            f"{YARD}/moves",
            json={
                "trailer_id": str(theirs["trailer"]),
                "from_location": "A1",
                "to_location": "B2",
                "move_type": "relocation",
            },
        )
        assert response.status_code == 404, response.text[:200]


class TestTheOwnersOwnRowsStillWork:
    """Every assertion above is satisfied by routes that refuse everything. This is the
    denominator (rule 165), and on a change this wide it is the half that can actually
    break a deployment."""

    @pytest.mark.parametrize(
        "label,method,path,field,target",
        CROSS_TENANT_WRITES,
        ids=[row[0] for row in CROSS_TENANT_WRITES],
    )
    async def test_your_own_reference_is_accepted(
        self, client_b, mine, label, method, path, field, target
    ):
        url = path.format(**{k: str(v) for k, v in mine.items()})
        response = await getattr(client_b, method)(url, json={field: str(mine[target])})
        assert response.status_code == 200, (
            f"{label}: org B's own {field} was refused — {response.status_code} "
            f"{response.text[:200]}"
        )

    async def test_a_trailer_checks_in_against_its_own_carrier(self, client_b, mine):
        response = await client_b.post(
            f"{YARD}/trailers/checkin",
            json={
                "trailer_number": f"FS737-{uuid.uuid4().hex[:6]}",
                "carrier_id": str(mine["carrier"]),
            },
        )
        assert response.status_code == 200, response.text[:300]

    async def test_a_write_with_no_references_still_works(self, client_b, mine):
        """`verify_refs` iterates only the fields the caller sent, so a body carrying none
        must be untouched by it."""
        response = await client_b.put(
            f"{YARD}/trailers/{mine['trailer']}", json={"yard_location": "C7"}
        )
        assert response.status_code == 200, response.text[:300]
        assert response.json()["yard_location"] == "C7"

    async def test_an_explicit_null_still_unlinks(self, client_b, mine):
        """`exclude_unset` distinguishes "not sent" from "sent as null"; only the first is
        skipped. A caller must still be able to detach a trailer from a carrier."""
        await client_b.put(
            f"{YARD}/trailers/{mine['trailer']}", json={"carrier_id": str(mine["carrier"])}
        )
        response = await client_b.put(
            f"{YARD}/trailers/{mine['trailer']}", json={"carrier_id": None}
        )
        assert response.status_code == 200, response.text[:300]
        assert response.json()["carrier_id"] is None


class TestTheRefusalDoesNotLeak:
    async def test_a_nonexistent_id_answers_the_same_as_a_foreign_one(
        self, client_b, mine, theirs
    ):
        """404 for both, deliberately. If a foreign id answered 403 and an invented one
        404, the pair would be a membership oracle: a caller could enumerate which ids
        exist in other tenants by the status code alone."""
        foreign = await client_b.put(
            f"{YARD}/trailers/{mine['trailer']}", json={"carrier_id": str(theirs["carrier"])}
        )
        invented = await client_b.put(
            f"{YARD}/trailers/{mine['trailer']}", json={"carrier_id": str(uuid.uuid4())}
        )
        assert foreign.status_code == invented.status_code == 404
