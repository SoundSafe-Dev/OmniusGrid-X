"""A GeoTab location webhook may not rewrite a trip it cannot attribute to a tenant (FS-734).

FOUND BY READING A COMMENT, not by a failure. `_process_location_update_webhook` carried this
beside its query:

    # Scope the lookup to the SAME org as the payload: a webhook caller
    # must never mutate another tenant's trip via a device-id collision.

and then scoped it like this:

    if org_id:
        trip_stmt = trip_stmt.where(GeoTabTrip.organization_id == org_id)

An absent `organization_id` did not narrow the lookup — it REMOVED the narrowing. The query
then matched any tenant's active trip for that device id and overwrote its `end_location` and
`end_time`, which is precisely what the comment says must never happen. The insert on the
other branch stored `organization_id=None`, a trip belonging to nobody.

**Absence read as unrestricted access.** This codebase has a name for that shape and a fix for
it: `core.tenant.get_tenant_org_id` refuses rather than widens — *"we fail closed rather than
fail open"* — and the notification handlers were repaired for the identical pattern, where a
filter applied only `if org is not None` let a caller with no organisation read every
organisation's rows.

WHAT THE TRUST BOUNDARY IS, precisely, because it decides the severity. The route is
`dependencies=[Depends(verify_geotab_webhook)]` — secret-guarded, not open to the internet. But
`organization_id` arrives in the BODY, so with one shared secret across a multi-tenant
deployment the body is the only thing deciding whose trip is rewritten. And a genuine GeoTab
callback carries no `organization_id` at all, because it is our field and not theirs — so the
untenanted path is the ORDINARY one, not the adversarial one.

Dropping the event is the honest outcome. A position that cannot be attributed to a tenant is
not a position that can be stored, and storing it against whoever happened to share the device
id is worse than losing it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def webhook(app):
    """Post to the real ROUTE, not the service.

    The fix binds the session through `core.tenant.tenant_session`, which resolves the
    application's engine — and `conftest` overrides that engine for the APP. Calling the
    service directly bypasses the override and fails with `role "placeholder" does not
    exist`, which says nothing about the code under test. Going through the route also
    exercises `verify_geotab_webhook`, which is the real entry condition.
    """
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async def post(payload):
            return await client.post("/api/v1/geotab/webhook", json=payload)

        yield post


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


#: One device id, deliberately shared. The defect needs a collision to show itself, and a
#: collision is not exotic: GeoTab device ids are the vendor's, not ours, and nothing stops
#: two customers describing the same physical unit or a test fixture reusing a string.
DEVICE = "GEOTAB-FS734-SHARED"


@pytest_asyncio.fixture
async def org_a_trip(admin_sync_url, seeded_orgs):
    """An ACTIVE trip owned by org A, which is what the webhook path extends."""
    trip_id = uuid.uuid4()
    started = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO geotab_trips (id, organization_id, device_id, start_time, end_time, "
            "start_location, end_location, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')",
            (
                str(trip_id),
                str(seeded_orgs["org_a_id"]),
                DEVICE,
                started,
                started,
                '{"address": "org A start"}',
                '{"address": "org A end"}',
            ),
        )
    yield trip_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM geotab_trips WHERE device_id = %s", (DEVICE,))
    conn.close()


def _trip(admin_sync_url, trip_id):
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT end_location, organization_id FROM geotab_trips WHERE id = %s",
            (str(trip_id),),
        )
        row = cur.fetchone()
    conn.close()
    return row


class TestAnUntenantedPositionIsDropped:
    async def test_it_does_not_touch_another_tenants_trip(
        self, webhook, admin_sync_url, org_a_trip
    ):
        """THE REGRESSION. With `if org_id:` scoping, this payload — carrying no
        organisation, which is what a real GeoTab callback looks like — matched org A's
        active trip on the shared device id and overwrote its end point."""
        await webhook({
                "type": "location_update",
                "device_id": DEVICE,
                "location": {"address": "somebody else's yard"},
            },
        )
        end_location, _org = _trip(admin_sync_url, org_a_trip)
        assert end_location == {"address": "org A end"}, (
            f"org A's trip end point is now {end_location!r}. An absent organization_id "
            f"removed the tenant filter instead of refusing the event."
        )

    async def test_the_webhook_reports_that_it_refused(self, webhook):
        """The receiver answers `processed: False` rather than a cheerful 200 over a write
        that never happened — the shape this whole file is about."""
        response = await webhook(
            {"type": "location_update", "device_id": DEVICE, "location": {"address": "x"}}
        )
        assert response.status_code == 200, response.text[:200]
        result = response.json()
        # THE ACK MUST SAY IT REFUSED. This route assigned the service's result and
        # discarded it, answering `status: "processed"` unconditionally — so a webhook that
        # stored nothing was acknowledged as stored, and the sender could never learn
        # otherwise. A mutation that removed the refusal was caught by nothing until this
        # assertion existed: without it, "crashed on a bad UUID" and "deliberately refused"
        # look identical from outside.
        assert result["status"] == "rejected", (
            f"the receiver answered {result['status']!r} for a payload it refused to store"
        )
        assert result["event_type"] == "location_update"

    async def test_it_does_not_write_an_untenanted_trip(self, webhook, admin_sync_url):
        """The other half: with no active trip to match, the old code INSERTED one with
        `organization_id=None` — a row belonging to nobody, which every tenant-scoped read
        then filters out and no one can ever see or clean up."""
        await webhook({
                "type": "location_update",
                "device_id": "GEOTAB-FS734-ORPHAN",
                "location": {"address": "nowhere"},
            },
        )
        conn = _conn(admin_sync_url)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM geotab_trips WHERE device_id = %s",
                ("GEOTAB-FS734-ORPHAN",),
            )
            count = cur.fetchone()[0]
        conn.close()
        assert count == 0, "an untenanted trip row was written"


class TestATenantedPositionStillWorks:
    """Every assertion above is satisfied by a handler that drops everything. This is the
    denominator (rule 165)."""

    async def test_the_owner_position_extends_the_owner_trip(
        self, webhook, admin_sync_url, org_a_trip, seeded_orgs
    ):
        await webhook({
                "type": "location_update",
                "device_id": DEVICE,
                "location": {"address": "org A new position"},
                "organization_id": str(seeded_orgs["org_a_id"]),
            },
        )
        end_location, org = _trip(admin_sync_url, org_a_trip)
        assert end_location == {"address": "org A new position"}, (
            "the owner's own position no longer extends their trip"
        )
        assert str(org) == str(seeded_orgs["org_a_id"])

    async def test_another_tenants_id_does_not_reach_org_a(
        self, webhook, admin_sync_url, org_a_trip, seeded_orgs
    ):
        """A payload naming org B must not extend org A's trip, even on the same device."""
        await webhook({
                "type": "location_update",
                "device_id": DEVICE,
                "location": {"address": "org B position"},
                "organization_id": str(seeded_orgs["org_b_id"]),
            },
        )
        end_location, _org = _trip(admin_sync_url, org_a_trip)
        assert end_location == {"address": "org A end"}, (
            f"org B's position rewrote org A's trip end point to {end_location!r}"
        )
