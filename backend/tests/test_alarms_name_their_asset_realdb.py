"""An alarm says which machine it came from (FS-436).

The dashboard's Active Alarms panel renders

    {alarm.assetName} • {new Date(alarm.occurredAt).toLocaleString()}

and `assetName` was never sent by anything. `AlarmResponse` carries `asset_id`; the name
lives on `assets`. So every row displayed a bullet with an empty space in front of it, and
**an alarm you cannot attribute to a machine is not actionable** — the asset is the first
thing an operator needs and the only one that tells them where to walk.

WHY NOBODY SAW IT. `mockApi.ts` supplies `assetName`, and the default development mode is
`VITE_USE_MOCK=true`. The panel looked finished in development and was blank against the
real API — the same pairing already recorded for the yard's `trailerLicensePlate`, whose
resolver `_resolve_asset_names` copies.

AND THE GUARD THAT SHOULD HAVE CAUGHT IT SAID THE OPPOSITE. `ActiveAlarmsResponse`'s own
docstring reads *"every field the client's `Alarm` type reads is in `AlarmResponse`
already"* — written when the response model was introduced, accurate about the fields it
was comparing, and wrong about this one. It took a per-type sweep
(`test_frontend_types_match_their_own_payload`) to find it, because the global wire
vocabulary contains `assetName` from the OEE endpoints and credited it here.

TWO ENDPOINTS, because two screens read it: `/alarms/active` behind the dashboard panel and
`/alarms/` behind the Alarms page. The single-alarm paths deliberately leave it null — see
the note on `AlarmResponse.asset_name`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

pytest.importorskip("testcontainers")

ASSET_NAME = "Press Line 3"


@pytest_asyncio.fixture
async def alarming_asset(admin_sync_url, seeded_orgs):
    """One asset with a recognisable name and one active alarm on it, for org A."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    asset_id, type_id, alarm_id = uuid4(), uuid4(), uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'test')",
            (str(type_id), f"ALM-{type_id.hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, name, "
            "is_active) VALUES (%s, %s, %s, %s, %s, true)",
            (
                str(asset_id),
                str(seeded_orgs["org_a_id"]),
                str(seeded_orgs["workcell_a_id"]),
                str(type_id),
                ASSET_NAME,
            ),
        )
        cur.execute(
            "INSERT INTO alarms (id, organization_id, asset_id, alarm_code, severity, "
            "message, is_active, is_acknowledged, occurred_at) VALUES "
            "(%s, %s, %s, 'E-42', 'critical', 'Spindle overtemperature', true, false, %s)",
            (
                str(alarm_id),
                str(seeded_orgs['org_a_id']),
                str(asset_id),
                datetime.now(timezone.utc),
            ),
        )
    yield {"asset_id": asset_id, "alarm_id": alarm_id,
           "organization_id": seeded_orgs["org_a_id"]}
    with conn.cursor() as cur:
        cur.execute("DELETE FROM alarms WHERE id = %s", (str(alarm_id),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(asset_id),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


class TestTheAlarmNamesItsAsset:
    async def test_the_active_list_carries_the_asset_name(self, client_a, alarming_asset):
        """The dashboard panel. This is the assertion the blank line was."""
        body = (await client_a.get("/api/v1/alarms/active")).json()
        rows = [a for a in body["alarms"] if a["id"] == str(alarming_asset["alarm_id"])]
        assert rows, f"the seeded alarm is not in the active list ({body['count']} rows)"
        assert rows[0]["asset_name"] == ASSET_NAME, (
            f"the active-alarms row carries asset_name={rows[0].get('asset_name')!r}; the "
            f"dashboard renders it as '{{assetName}} • {{occurredAt}}', so a null prints a "
            f"bullet with nothing in front of it"
        )

    async def test_the_paginated_list_carries_it_too(self, client_a, alarming_asset):
        """The Alarms page reads the same field from a different endpoint. Fixing only the
        one the dashboard uses would leave the larger screen blank."""
        body = (
            await client_a.get("/api/v1/alarms/", params={"limit": 100})
        ).json()
        rows = [a for a in body["items"] if a["id"] == str(alarming_asset["alarm_id"])]
        assert rows, "the seeded alarm is not in the paginated list"
        assert rows[0]["asset_name"] == ASSET_NAME

    async def test_it_is_one_query_for_the_page_not_one_per_row(
        self, client_a, alarming_asset, admin_sync_url
    ):
        """Resolved in a set-based lookup, like `_resolve_trailer_plates` next door.

        Asserted structurally rather than by counting queries: the resolver takes the whole
        id set, so a second alarm on the SAME asset must not change the answer, and one on a
        different asset must resolve independently.
        """
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        second = uuid4()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alarms (id, organization_id, asset_id, alarm_code, severity, "
                "message, is_active, is_acknowledged, occurred_at) VALUES "
                "(%s, %s, %s, 'E-43', 'high', 'Second fault', true, false, %s)",
                (
                    str(second),
                    str(alarming_asset['organization_id']),
                    str(alarming_asset['asset_id']),
                    datetime.now(timezone.utc),
                ),
            )
        try:
            body = (await client_a.get("/api/v1/alarms/active")).json()
            named = [
                a for a in body["alarms"]
                if a["id"] in {str(alarming_asset["alarm_id"]), str(second)}
            ]
            assert len(named) == 2
            assert all(a["asset_name"] == ASSET_NAME for a in named)
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM alarms WHERE id = %s", (str(second),))
            conn.close()


class TestItDoesNotBreakTheEmptyCase:
    async def test_no_alarms_is_still_a_clean_answer(self, client_b):
        """The resolver returns early on an empty id set. Org B has no alarms, and a page
        with nothing on it must not 500 on a lookup of nothing."""
        response = await client_b.get("/api/v1/alarms/active")
        assert response.status_code == 200, response.text
        assert response.json()["count"] == 0
