"""A kanban task may only link ids the caller owns, and completing one is not a back door
onto the command API (FS-736).

TWO DEFECTS ON ONE ROUTE, found by asking what ELSE the create body carries.

**One.** `create_task` validated `board_id` against the organisation and `column_id`
against the board, and then copied six more ids out of the request body onto the row
without looking at any of them: `asset_id`, `operation_id`, `alarm_id`, `command_id`,
`parent_task_id`, `assigned_to`. A foreign key is checked BELOW row-level security, so the
database accepted every one — this is the fifth instance of that class (FS-720, FS-724,
FS-726, FS-729) and the largest.

The shape that makes it worth a file of its own: **`update_task` already refused a foreign
`parent_task_id`** — its ancestry walk calls `get_organization_task`, which 404s — while
`create_task`, thirty lines above it, accepted the same field on the same model. The same
id, defended on one verb and unchecked on the other. A reader auditing the update path
would have come away satisfied.

`alarm_id` and `command_id` are worse than unvalidated: neither column carries a foreign
key at all, so they accepted a UUID naming nothing in any tenant.

**Two, and the more serious.** `completion_actions` is a free-form `Dict[str, Any]` on the
same body, and completing a task hands its `execute_command` entry straight to
`command_executor.submit_command`. That is a second entrance to the command surface, and
it had none of the three checks the front entrance performs in `app/api/commands.py`:

    POST /commands/submit          POST /kanban/tasks/{id}/complete
    ------------------------       --------------------------------
    remote op            → 400     remote op            → 200, command queued, NO AUDIT
    another org's asset  → 404     another org's asset  → 200, command row written
    emergency_stop,
      non-admin          → 403     emergency_stop, non-admin → 200, command queued

WHAT THE CROSS-TENANT VARIANT IS AND IS NOT. `submit_command` never checks that its
`asset_id` and its `organization_id` agree, so the row it wrote named org A's machine and
belonged to org B. It was not deliverable: the dispatched message carries the SUBMITTING
org and the edge agent drops any command whose `organization_id` is not its own
(`edge-agent/opsgrid_agent/commands/consumer.py:440`). So the honest description is a bad
row plus a `command_executed: True` that never executed — not remote actuation of another
tenant's machine. Recording that distinction rather than the alarming version of it is the
point; the two same-tenant variants ARE fully deliverable, and those defeat an
authorisation rule rather than a data boundary, which is why they are the worse half.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

TASKS = "/api/v1/kanban/tasks"
SUBMIT = "/api/v1/commands/submit"


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


def _asset(admin_sync_url, org_id, workcell_id) -> uuid.UUID:
    asset_id, type_id = uuid.uuid4(), uuid.uuid4()
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'machine')",
            (str(type_id), f"FS736-{uuid.uuid4().hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, asset_type_id, workcell_id, name, "
            "is_active) VALUES (%s, %s, %s, %s, 'FS736 Asset', true)",
            (str(asset_id), str(org_id), str(type_id), str(workcell_id)),
        )
    conn.close()
    return asset_id


@pytest_asyncio.fixture
async def org_a_refs(admin_sync_url, seeded_orgs):
    """One row of every kind a task can link to, all owned by ORG A."""
    refs = {
        "asset_id": _asset(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"]
        ),
        "operation_id": uuid.uuid4(),
        "alarm_id": uuid.uuid4(),
        "command_id": uuid.uuid4(),
        "assigned_to": seeded_orgs["user_a_id"],
    }
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO operations (id, asset_id, operation_name, status) "
            "VALUES (%s, %s, 'FS736 Operation', 'running')",
            (str(refs["operation_id"]), str(refs["asset_id"])),
        )
        cur.execute(
            "INSERT INTO alarms (id, organization_id, asset_id, alarm_code, severity, "
            "message, occurred_at) "
            "VALUES (%s, %s, %s, 'FS736', 'high', 'FS736 alarm', now())",
            (
                str(refs["alarm_id"]),
                str(seeded_orgs["org_a_id"]),
                str(refs["asset_id"]),
            ),
        )
        cur.execute(
            "INSERT INTO commands (id, organization_id, asset_id, command_type, "
            "action_id, parameters, status, timeout_seconds) "
            "VALUES (%s, %s, %s, 'system', 'pause_job', '{}', 'pending', 30)",
            (
                str(refs["command_id"]),
                str(seeded_orgs["org_a_id"]),
                str(refs["asset_id"]),
            ),
        )
    yield refs
    with conn.cursor() as cur:
        # By EVERY link, not only `asset_id` — a task created for the `operation_id`
        # case carries no asset, and left behind it blocks the operation's delete.
        cur.execute(
            "DELETE FROM tasks WHERE asset_id = %(asset)s OR operation_id = %(op)s "
            "OR alarm_id = %(alarm)s OR command_id = %(cmd)s OR assigned_to = %(user)s",
            {
                "asset": str(refs["asset_id"]),
                "op": str(refs["operation_id"]),
                "alarm": str(refs["alarm_id"]),
                "cmd": str(refs["command_id"]),
                "user": str(refs["assigned_to"]),
            },
        )
        cur.execute("DELETE FROM commands WHERE asset_id = %s", (str(refs["asset_id"]),))
        cur.execute("DELETE FROM alarms WHERE asset_id = %s", (str(refs["asset_id"]),))
        cur.execute("DELETE FROM operations WHERE asset_id = %s", (str(refs["asset_id"]),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(refs["asset_id"]),))
    conn.close()


@pytest_asyncio.fixture
async def org_b_board(client_b):
    """`GET /board` creates the organisation's default board and columns if it has none."""
    response = await client_b.get("/api/v1/kanban/board")
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    return body["board"]["id"], body["columns"][0]["id"]


def _task_body(board_id, column_id, **extra):
    return {
        "board_id": board_id,
        "column_id": column_id,
        "title": "FS736",
        "task_type": "custom",
        **extra,
    }


LINKS = ["asset_id", "operation_id", "alarm_id", "command_id", "assigned_to"]


class TestCreateRefusesAForeignLink:
    @pytest.mark.parametrize("field", LINKS)
    async def test_it_is_refused(self, client_b, org_b_board, org_a_refs, field):
        board_id, column_id = org_b_board
        response = await client_b.post(
            TASKS, json=_task_body(board_id, column_id, **{field: str(org_a_refs[field])})
        )
        assert response.status_code == 404, (
            f"org B created a task linking org A's {field} and got "
            f"{response.status_code}. The foreign key is checked below RLS, so only the "
            f"handler can refuse it."
        )

    async def test_a_foreign_parent_is_refused(
        self, client_a, client_b, org_b_board, admin_sync_url
    ):
        """THE ASYMMETRY THIS FILE EXISTS FOR. `update_task` refused this and
        `create_task` did not."""
        board = (await client_a.get("/api/v1/kanban/board")).json()
        parent = await client_a.post(
            TASKS,
            json=_task_body(board["board"]["id"], board["columns"][0]["id"]),
        )
        assert parent.status_code == 200, parent.text[:200]
        parent_id = parent.json()["id"]

        board_id, column_id = org_b_board
        response = await client_b.post(
            TASKS, json=_task_body(board_id, column_id, parent_task_id=parent_id)
        )
        assert response.status_code == 404, (
            f"org B parented a task on org A's task and got {response.status_code}"
        )

    async def test_an_id_belonging_to_nobody_is_refused(self, client_b, org_b_board):
        """`tasks.alarm_id` has no foreign key at all, so before this it accepted a UUID
        naming nothing in any tenant — not even a wrong row, just a fiction."""
        board_id, column_id = org_b_board
        response = await client_b.post(
            TASKS, json=_task_body(board_id, column_id, alarm_id=str(uuid.uuid4()))
        )
        assert response.status_code == 404, response.text[:200]

    async def test_a_non_uuid_command_id_is_a_refusal_not_a_crash(
        self, client_b, org_b_board
    ):
        """`tasks.command_id` is a TEXT column, so an ordinary string reaches the
        comparison against `commands.id`, which is a uuid. Postgres refuses to compare
        them, and that must read as 'not found' rather than escape as a 500."""
        board_id, column_id = org_b_board
        response = await client_b.post(
            TASKS, json=_task_body(board_id, column_id, command_id="not-a-uuid")
        )
        assert response.status_code == 404, response.text[:200]


class TestUpdateRefusesAForeignLink:
    @pytest.mark.parametrize("field", LINKS)
    async def test_a_task_cannot_be_repointed(
        self, client_b, org_b_board, org_a_refs, field
    ):
        """Fixing creation alone would leave the row settable one request later."""
        board_id, column_id = org_b_board
        created = await client_b.post(TASKS, json=_task_body(board_id, column_id))
        assert created.status_code == 200, created.text[:200]
        task_id = created.json()["id"]

        response = await client_b.put(
            f"{TASKS}/{task_id}", json={field: str(org_a_refs[field])}
        )
        assert response.status_code == 404, (
            f"org B re-pointed a task at org A's {field} and got {response.status_code}"
        )


class TestTheOwnersOwnLinksStillWork:
    """Every assertion above is satisfied by a route that refuses every link. This is the
    denominator (rule 165)."""

    @pytest.mark.parametrize("field", LINKS)
    async def test_a_link_you_own_is_accepted(
        self, client_a, admin_sync_url, org_a_refs, field
    ):
        board = (await client_a.get("/api/v1/kanban/board")).json()
        response = await client_a.post(
            TASKS,
            json=_task_body(
                board["board"]["id"],
                board["columns"][0]["id"],
                **{field: str(org_a_refs[field])},
            ),
        )
        assert response.status_code == 200, response.text[:300]

    async def test_a_task_with_no_links_still_works(self, client_b, org_b_board):
        board_id, column_id = org_b_board
        response = await client_b.post(TASKS, json=_task_body(board_id, column_id))
        assert response.status_code == 200, response.text[:300]

    async def test_an_explicit_null_still_unlinks(
        self, client_a, org_a_refs
    ):
        """`exclude_unset` is what makes the check skip an absent field; a caller sending
        an explicit `null` must still be able to detach a task from an asset."""
        board = (await client_a.get("/api/v1/kanban/board")).json()
        created = await client_a.post(
            TASKS,
            json=_task_body(
                board["board"]["id"],
                board["columns"][0]["id"],
                asset_id=str(org_a_refs["asset_id"]),
            ),
        )
        task_id = created.json()["id"]
        response = await client_a.put(f"{TASKS}/{task_id}", json={"asset_id": None})
        assert response.status_code == 200, response.text[:300]
        assert response.json()["asset_id"] is None


# --- the second door -------------------------------------------------------------


def _commands_for(admin_sync_url, asset_id, action_id) -> int:
    """Counted by ACTION as well as asset. `org_a_refs` seeds a real `pause_job` command
    against org A's asset so that `command_id` has something to point at — count by asset
    alone and the fixture's own row reads as the one the route was supposed to refuse."""
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM commands WHERE asset_id = %s AND action_id = %s",
            (str(asset_id), action_id),
        )
        count = cur.fetchone()[0]
    conn.close()
    return count


async def _complete_with(client, board, actions):
    board_id, column_id = board
    created = await client.post(
        TASKS, json=_task_body(board_id, column_id, completion_actions=actions)
    )
    assert created.status_code == 200, created.text[:300]
    return await client.post(f"{TASKS}/{created.json()['id']}/complete")


@pytest_asyncio.fixture
async def org_b_asset(admin_sync_url, seeded_orgs):
    asset_id = _asset(
        admin_sync_url, seeded_orgs["org_b_id"], seeded_orgs["workcell_b_id"]
    )
    yield asset_id
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE asset_id = %s", (str(asset_id),))
        cur.execute("DELETE FROM commands WHERE asset_id = %s", (str(asset_id),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(asset_id),))
    conn.close()


@pytest_asyncio.fixture
async def operator_client(app, admin_sync_url, seeded_orgs):
    """An OPERATOR in org B. Both seeded users are admins, so the role gate cannot be
    exercised without one — and a role check that is never tested with a non-admin is a
    role check that has never been tested."""
    from httpx import ASGITransport, AsyncClient

    from app.core.config import settings
    from tests.conftest import _make_jwt

    user_id = uuid.uuid4()
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, email, hashed_password, organization_id, role, "
            "is_active) VALUES (%s, %s, 'x', %s, 'operator', true)",
            (str(user_id), f"op-{user_id.hex[:8]}@test.local", str(seeded_orgs["org_b_id"])),
        )
    token = _make_jwt(user_id, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (str(user_id),))
    conn.close()


class TestCompletingATaskIsNotABackDoor:
    async def test_a_remote_operation_is_refused(
        self, client_b, org_b_board, org_b_asset, admin_sync_url
    ):
        """`POST /commands/submit` answers 400 and says to use the Fleet operations API —
        which exists because a remote agent operation must carry an audit context.
        Submitted through a completion action, `remote_audit` is `None`."""
        response = await _complete_with(
            client_b,
            org_b_board,
            {
                "execute_command": {
                    "asset_id": str(org_b_asset),
                    "action_id": "collector_restart",
                    "command_type": "system",
                    "parameters": {"collector_name": "x"},
                }
            },
        )
        assert response.status_code == 400, (
            f"a remote operation was queued through a task completion "
            f"({response.status_code}); the direct route answers 400"
        )
        assert _commands_for(admin_sync_url, org_b_asset, "collector_restart") == 0

    async def test_emergency_stop_still_requires_an_admin(
        self, operator_client, org_b_asset, admin_sync_url
    ):
        """The direct route refuses this with 403. An operator could stop a line by
        completing a card instead."""
        board = (await operator_client.get("/api/v1/kanban/board")).json()
        response = await _complete_with(
            operator_client,
            (board["board"]["id"], board["columns"][0]["id"]),
            {
                "execute_command": {
                    "asset_id": str(org_b_asset),
                    "action_id": "emergency_stop",
                    "command_type": "system",
                }
            },
        )
        assert response.status_code == 403, (
            f"an operator queued an emergency stop by completing a task "
            f"({response.status_code})"
        )
        assert _commands_for(admin_sync_url, org_b_asset, "emergency_stop") == 0

    async def test_another_tenants_asset_is_refused(
        self, client_b, org_b_board, org_a_refs, admin_sync_url
    ):
        response = await _complete_with(
            client_b,
            org_b_board,
            {
                "execute_command": {
                    "asset_id": str(org_a_refs["asset_id"]),
                    "action_id": "set_speed",
                    "command_type": "system",
                }
            },
        )
        assert response.status_code == 404, response.text[:200]
        assert _commands_for(admin_sync_url, org_a_refs["asset_id"], "set_speed") == 0, (
            "a command row was written against org A's asset and attributed to org B"
        )

    async def test_the_task_is_not_completed_when_the_action_is_refused(
        self, client_b, org_b_board, org_a_refs
    ):
        """The gate runs BEFORE the move to Done. A completion that cannot lawfully run
        its action must not half-happen — otherwise the card reads as finished and the
        side effect the card exists for never occurred."""
        board_id, column_id = org_b_board
        created = await client_b.post(
            TASKS,
            json=_task_body(
                board_id,
                column_id,
                completion_actions={
                    "execute_command": {
                        "asset_id": str(org_a_refs["asset_id"]),
                        "action_id": "pause_job",
                        "command_type": "system",
                    }
                },
            ),
        )
        task_id = created.json()["id"]
        await client_b.post(f"{TASKS}/{task_id}/complete")
        after = await client_b.get(f"{TASKS}/{task_id}")
        assert after.json()["status"] != "completed", (
            "the task was marked complete even though its completion action was refused"
        )


class TestAnOrdinaryCompletionStillRuns:
    """Everything above is satisfied by a gate that refuses every completion action."""

    async def test_a_lawful_command_is_still_queued(
        self, client_b, org_b_board, org_b_asset, admin_sync_url
    ):
        response = await _complete_with(
            client_b,
            org_b_board,
            {
                "execute_command": {
                    "asset_id": str(org_b_asset),
                    "action_id": "pause_job",
                    "command_type": "system",
                }
            },
        )
        assert response.status_code == 200, response.text[:300]
        assert _commands_for(admin_sync_url, org_b_asset, "pause_job") == 1, (
            "an admin's command against their own asset was not queued"
        )

    async def test_a_completion_with_no_command_action_is_untouched(
        self, client_b, org_b_board
    ):
        response = await _complete_with(
            client_b, org_b_board, {"clear_alarm": True}
        )
        assert response.status_code == 200, response.text[:300]
