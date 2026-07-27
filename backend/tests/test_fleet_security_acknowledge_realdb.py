"""Acknowledging a fleet security event must persist, and stay inside the tenant.

THE DEFECT. `HealthSecurityPanel` has always offered an "acknowledge" action, wired to
`fleetHealthApi.acknowledgeSecurityEvent` → `PATCH /api/v1/fleet/security/events/{id}`.
The backend never served that route. The component awaited it with no `catch`, so the
404 rejected the promise, the optimistic state update never ran, and the operator saw
nothing happen and no error.

Everything else was already there: `geotab_exceptions` carries `acknowledged`,
`acknowledged_by` and `acknowledged_at`, and `GET /security/events` already returns and
filters on the flag. Only the write was missing.

Found by sweeping every real-mode frontend call against the backend's route table
(`test_frontend_calls_real_endpoints.py`), which exists because `VITE_USE_MOCK='true'` is
forced in the frontend test setup — so the mock branch is the only one any test runs, and
a wrong path survives indefinitely.

Worth noting that this router's own docstring says it was created (FS-15) precisely to
serve "/api/v1/fleet/* routes that never existed (dead real branch)". That fix missed the
two PATCH routes. A sweep catches what a fix-by-hand leaves behind.

The route-existence guard cannot tell whether the handler works. This does.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def security_event(admin_sync_url, seeded_orgs):
    """One unacknowledged GeoTab exception in org A, seeded past RLS."""
    import psycopg2

    event_id = uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO geotab_exceptions "
            "(id, device_id, organization_id, exception_type, severity, timestamp, "
            " acknowledged) VALUES (%s, %s, %s, %s, %s, %s, false)",
            (
                str(event_id),
                "device-1",
                str(seeded_orgs["org_a_id"]),
                "speeding",
                "high",
                datetime.now(timezone.utc),
            ),
        )
    yield event_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM geotab_exceptions WHERE id = %s", (str(event_id),))
    conn.close()


async def _fetch(client, event_id):
    response = await client.get("/api/v1/fleet/security/events")
    assert response.status_code == 200, response.text
    return next((e for e in response.json() if e["id"] == str(event_id)), None)


class TestItPersists:
    async def test_acknowledging_sticks(self, client_a, security_event):
        """THE ASSERTION THIS FILE EXISTS FOR — the route used to 404."""
        response = await client_a.patch(
            f"/api/v1/fleet/security/events/{security_event}",
            json={"acknowledged": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["acknowledged"] is True

    async def test_the_change_is_visible_on_the_next_read(self, client_a, security_event):
        """A response body that says `acknowledged: true` proves nothing on its own if
        the row did not change — the panel re-reads this list."""
        assert (await _fetch(client_a, security_event))["acknowledged"] is False

        await client_a.patch(
            f"/api/v1/fleet/security/events/{security_event}",
            json={"acknowledged": True},
        )

        assert (await _fetch(client_a, security_event))["acknowledged"] is True

    async def test_it_can_be_un_acknowledged(self, client_a, security_event):
        await client_a.patch(
            f"/api/v1/fleet/security/events/{security_event}", json={"acknowledged": True}
        )
        response = await client_a.patch(
            f"/api/v1/fleet/security/events/{security_event}", json={"acknowledged": False}
        )
        assert response.status_code == 200
        assert (await _fetch(client_a, security_event))["acknowledged"] is False

    async def test_the_acknowledged_filter_reflects_it(self, client_a, security_event):
        """`GET /security/events?acknowledged=` already filtered on this column; the
        write has to move an event between those two result sets."""
        await client_a.patch(
            f"/api/v1/fleet/security/events/{security_event}", json={"acknowledged": True}
        )
        unacked = await client_a.get("/api/v1/fleet/security/events?acknowledged=false")
        assert str(security_event) not in [e["id"] for e in unacked.json()]

        acked = await client_a.get("/api/v1/fleet/security/events?acknowledged=true")
        assert str(security_event) in [e["id"] for e in acked.json()]


class TestAttributionComesFromTheToken:
    async def test_the_acknowledging_user_is_recorded(
        self, client_a, security_event, admin_sync_url, seeded_orgs
    ):
        """`acknowledged_by` must come from the JWT, not the body — attribution a
        caller can set is not attribution. Same rule as `alarms.acknowledge_alarm`,
        where it was once a query parameter."""
        import psycopg2

        await client_a.patch(
            f"/api/v1/fleet/security/events/{security_event}", json={"acknowledged": True}
        )
        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT acknowledged_by, acknowledged_at FROM geotab_exceptions "
                    "WHERE id = %s",
                    (str(security_event),),
                )
                acknowledged_by, acknowledged_at = cur.fetchone()
        finally:
            conn.close()

        # str() both sides: this column comes back as text on some driver/type
        # combinations and as a UUID on others.
        assert str(acknowledged_by) == str(seeded_orgs["user_a_id"]), (
            "acknowledged_by was not taken from the authenticated user"
        )
        assert acknowledged_at is not None

    async def test_un_acknowledging_clears_the_attribution(
        self, client_a, security_event, admin_sync_url
    ):
        """Leaving a stale acknowledger on an unacknowledged event would read as
        'someone acknowledged this' to anything querying the column."""
        import psycopg2

        await client_a.patch(
            f"/api/v1/fleet/security/events/{security_event}", json={"acknowledged": True}
        )
        await client_a.patch(
            f"/api/v1/fleet/security/events/{security_event}", json={"acknowledged": False}
        )
        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT acknowledged_by, acknowledged_at FROM geotab_exceptions "
                    "WHERE id = %s",
                    (str(security_event),),
                )
                assert cur.fetchone() == (None, None)
        finally:
            conn.close()


class TestItStaysInsideTheTenant:
    async def test_another_org_cannot_acknowledge_it(self, client_b, security_event):
        """404 rather than 403 on purpose: confirming an id exists but belongs to
        someone else is itself a disclosure."""
        response = await client_b.patch(
            f"/api/v1/fleet/security/events/{security_event}",
            json={"acknowledged": True},
        )
        assert response.status_code == 404, response.text

    async def test_a_foreign_acknowledge_does_not_change_the_row(
        self, client_a, client_b, security_event
    ):
        """The status code alone would pass even if the write had happened first."""
        await client_b.patch(
            f"/api/v1/fleet/security/events/{security_event}", json={"acknowledged": True}
        )
        assert (await _fetch(client_a, security_event))["acknowledged"] is False

    async def test_an_unknown_id_is_404_not_500(self, client_a):
        response = await client_a.patch(
            f"/api/v1/fleet/security/events/{uuid.uuid4()}", json={"acknowledged": True}
        )
        assert response.status_code == 404
