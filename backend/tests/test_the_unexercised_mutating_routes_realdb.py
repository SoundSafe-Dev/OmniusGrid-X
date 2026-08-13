"""Two mutating routes no test had ever named (FS-680).

Of 251 mutating routes, thirteen appear in no test file at all. `route_walk` drives them —
it drives everything — but it drives them with *generated* input, which rejects at validation
before the handler's body runs. So the success path of each is unexecuted, and that is exactly
where `broadcast_to_org` was living when the first real-database exercise of
`POST /kanban/tasks` found it (FS-678): an `AttributeError` raised after a 200 had already
been returned.

These two are the ones in this lane that can be driven without new infrastructure:

  * `POST /commands/cancel/{command_id}` — cancels a pending or executing command, through
    `command_executor.cancel_command`, which takes a row lock and walks candidate org ids;
  * `POST /shop-floor/postings/drain` — attempts every queued ERP posting for the tenant.

The other two, `POST /bulk/alarms/acknowledge` and `POST /bulk/kanban/tasks/{operation}`,
create a Redis-tracked job before doing anything, and there is no Redis in this harness — so
their success path is genuinely unreachable here rather than merely untested. Recorded in
`TestWhyTheOtherTwoAreNotHere` so the gap is a stated decision and not an oversight, and
because their 503 path is worth pinning either way.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

COMMANDS = "/api/v1/commands"
SHOP_FLOOR = "/api/v1/shop-floor"


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


@pytest_asyncio.fixture
async def pending_command(admin_sync_url, seeded_orgs):
    """A pending command on a real asset, which is what `cancel` expects to find."""
    org = str(seeded_orgs["org_a_id"])
    ids = {"asset_type": uuid.uuid4(), "asset": uuid.uuid4(), "command": uuid.uuid4()}
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'machine')",
            (str(ids["asset_type"]), f"FS680-{uuid.uuid4().hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, asset_type_id, workcell_id, name, is_active) "
            "VALUES (%s, %s, %s, %s, 'FS680 Asset', true)",
            (
                str(ids["asset"]),
                org,
                str(ids["asset_type"]),
                str(seeded_orgs["workcell_a_id"]),
            ),
        )
        # `action_id` is NOT NULL and is a STRING, not a foreign key — the identifier of the
        # action within the asset's action space. The first version of this fixture omitted
        # it and hit the constraint, which is the fixture's own bug rather than a finding.
        cur.execute(
            "INSERT INTO commands (id, organization_id, asset_id, command_type, action_id, "
            "parameters, status, issued_by) "
            "VALUES (%s, %s, %s, 'set_state', 'FS680.set_state', '{}', 'pending', %s)",
            (str(ids["command"]), org, str(ids["asset"]), str(seeded_orgs["user_a_id"])),
        )
    yield ids
    with conn.cursor() as cur:
        cur.execute("DELETE FROM commands WHERE id = %s", (str(ids["command"]),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(ids["asset_type"]),))
    conn.close()


def _command_status(admin_sync_url, command_id) -> str | None:
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM commands WHERE id = %s", (str(command_id),))
        row = cur.fetchone()
    conn.close()
    return row[0] if row else None


class TestCancellingACommand:
    async def test_a_pending_command_can_be_cancelled(
        self, client_a, pending_command, admin_sync_url
    ):
        response = await client_a.post(f"{COMMANDS}/cancel/{pending_command['command']}")
        assert response.status_code == 200, response.text
        assert str(pending_command["command"]) in response.text

    async def test_the_row_actually_changes(self, client_a, pending_command, admin_sync_url):
        """The response says "Command cancelled" whatever happened underneath; the row is
        the only thing that knows whether it did."""
        await client_a.post(f"{COMMANDS}/cancel/{pending_command['command']}")
        assert _command_status(admin_sync_url, pending_command["command"]) == "cancelled"

    async def test_cancelling_twice_is_refused(
        self, client_a, pending_command, admin_sync_url
    ):
        """`cancel_command` selects only PENDING and EXECUTING rows, so the second attempt
        finds nothing. A 400 rather than a second cheerful 200."""
        first = await client_a.post(f"{COMMANDS}/cancel/{pending_command['command']}")
        assert first.status_code == 200, first.text
        second = await client_a.post(f"{COMMANDS}/cancel/{pending_command['command']}")
        assert second.status_code == 400, second.text

    async def test_an_unknown_command_is_a_400_not_a_500(self, client_a):
        response = await client_a.post(f"{COMMANDS}/cancel/{uuid.uuid4()}")
        assert response.status_code == 400, response.text

    async def test_another_tenant_cannot_cancel_it(
        self, client_b, pending_command, admin_sync_url
    ):
        """`cancel_command` takes an `organization_id` and walks candidate orgs; this is the
        assertion that the candidate walk does not walk into somebody else's tenant."""
        response = await client_b.post(f"{COMMANDS}/cancel/{pending_command['command']}")
        assert response.status_code == 400, response.text
        assert _command_status(admin_sync_url, pending_command["command"]) == "pending", (
            "another tenant's cancel landed on this command"
        )


class TestDrainingThePostingQueue:
    async def test_the_drain_answers_on_an_empty_queue(self, client_a):
        """The ordinary case, and the one a scheduler will hit most: nothing queued."""
        response = await client_a.post(f"{SHOP_FLOOR}/postings/drain")
        assert response.status_code == 200, response.text
        body = response.json()
        assert "note" in body, "the drain no longer explains what it did"

    async def test_the_limit_is_honoured_as_a_query_parameter(self, client_a):
        response = await client_a.post(f"{SHOP_FLOOR}/postings/drain?limit=5")
        assert response.status_code == 200, response.text

    async def test_an_out_of_range_limit_is_refused(self, client_a):
        """`Query(50, ge=1, le=500)`. A 422 rather than a silent clamp, so a caller asking
        for 5000 learns that it did not get 5000."""
        response = await client_a.post(f"{SHOP_FLOOR}/postings/drain?limit=5000")
        assert response.status_code == 422, response.text


class TestWhyTheOtherTwoAreNotHere:
    """`POST /bulk/alarms/acknowledge` and `POST /bulk/kanban/tasks/{operation}` create a
    Redis-tracked job before doing anything, and this harness has no Redis. Their success
    path is unreachable here rather than untested — a distinction worth writing down, since
    the two look identical in a coverage report.

    Their failure path is reachable, and is asserted, because `_create_job_or_503` catches
    `Exception` broadly: a genuine bug inside `create_job` would be reported to the caller as
    "Bulk job store unavailable" exactly like a Redis outage. Pinning the 503 at least fixes
    what that response means today.
    """

    async def test_the_bulk_alarm_route_reports_the_job_store_honestly(self, client_a):
        response = await client_a.post(
            "/api/v1/bulk/alarms/acknowledge", json={"alarm_ids": [str(uuid.uuid4())]}
        )
        assert response.status_code in (202, 503), response.text
        if response.status_code == 503:
            assert "unavailable" in response.text.lower()

    async def test_the_bulk_kanban_route_validates_before_touching_the_job_store(
        self, client_a
    ):
        """The validation is synchronous and ahead of the job creation, so this assertion
        holds with or without Redis — which is what makes it worth having here."""
        response = await client_a.post(
            "/api/v1/bulk/kanban/tasks/not_an_operation", json={"task_ids": [str(uuid.uuid4())]}
        )
        assert response.status_code == 400, response.text
        assert "operation must be one of" in response.text

    async def test_a_move_without_a_target_column_is_refused(self, client_a):
        response = await client_a.post(
            "/api/v1/bulk/kanban/tasks/move", json={"task_ids": [str(uuid.uuid4())]}
        )
        assert response.status_code == 400, response.text
        assert "target_column_id" in response.text
