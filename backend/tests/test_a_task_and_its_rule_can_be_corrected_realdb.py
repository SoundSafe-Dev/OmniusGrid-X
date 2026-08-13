"""Nineteen kanban fields that could be set once and never changed (FS-677).

Twelve on a task — its type, planned start and duration, effort estimate, tags, completion
actions, and every link it carries: board, asset, operation, alarm, command, parent. Six on an
automation rule — what fires it, where the task it creates lands, who it goes to, who is told,
and what happens on completion. On a board whose entire purpose is that work changes.

WHY THIS ONE NEEDED MORE THAN A SCHEMA CHANGE, and why it is tested against a real database
rather than by comparing model fields. Every other update handler in this codebase applies
`model_dump(exclude_unset=True)` and `setattr`, so widening the schema is the whole fix.
`update_task` does not: it hand-writes an `if x is not None` block per field so it can build
the activity-log changelog. A field added to the schema and not to the handler is **declared,
accepted, validated and silently dropped** — the exact defect FS-676 had just finished fixing
elsewhere, and one a schema-level test cannot see.

TWO OF THE TWELVE CARRY CONSTRAINTS:

  * `board_id` — a task moving to another board needs a column on the DESTINATION board, or it
    lands in a column belonging to the board it just left. The column check read
    `task.board_id`, so it also had to learn about the effective board, or a legitimate move
    would 404 on a column that plainly exists.
  * `parent_task_id` — a task must not become its own ancestor. Two tasks made each other's
    parent will hang anything that renders a task tree, and nothing prevented it.

The thirteenth `organization_id` is also closed here. `TaskRuleCreate` required a tenant id
that `create_task_rule` discards, so the natural client — which carries none — got a 422 on
every rule it tried to create. FS-523 removed exactly this from twelve other create schemas;
this one was found by the guard, recorded as another lane's, and left.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

KANBAN = "/api/v1/kanban"


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


@pytest_asyncio.fixture
async def board(client_a, admin_sync_url, seeded_orgs):
    """The org's board and its columns, plus a SECOND board to move tasks to."""
    response = await client_a.get(f"{KANBAN}/board")
    assert response.status_code == 200, response.text
    data = response.json()
    columns = data["columns"]
    assert len(columns) >= 2, "the default board should come with six columns"

    other_board, other_column = uuid.uuid4(), uuid.uuid4()
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO task_boards (id, organization_id, name, board_type, is_active) "
            "VALUES (%s, %s, 'FS677 Second Board', 'unified', false)",
            (str(other_board), str(seeded_orgs["org_a_id"])),
        )
        cur.execute(
            "INSERT INTO task_columns (id, board_id, name, position, column_type) "
            "VALUES (%s, %s, 'Intake', 0, 'backlog')",
            (str(other_column), str(other_board)),
        )
    yield {
        "board_id": data["board"]["id"],
        "columns": columns,
        "other_board": str(other_board),
        "other_column": str(other_column),
    }
    with conn.cursor() as cur:
        cur.execute("DELETE FROM task_comments WHERE content LIKE '%%FS677%%'")
        cur.execute("DELETE FROM tasks WHERE title LIKE 'FS677%%'")
        cur.execute("DELETE FROM task_columns WHERE id = %s", (str(other_column),))
        cur.execute("DELETE FROM task_boards WHERE id = %s", (str(other_board),))
        cur.execute("DELETE FROM task_rules WHERE rule_name LIKE 'FS677%%'")
    conn.close()


async def _task(client_a, board, **extra):
    body = {
        "title": f"FS677 {uuid.uuid4().hex[:6]}",
        "task_type": "custom",
        "board_id": board["board_id"],
        "column_id": board["columns"][0]["id"],
        **extra,
    }
    response = await client_a.post(f"{KANBAN}/tasks", json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def _put(client_a, task_id, body, expect=200):
    response = await client_a.put(f"{KANBAN}/tasks/{task_id}", json=body)
    assert response.status_code == expect, f"{response.status_code}\n{response.text}"
    return response.json() if response.status_code == 200 else response


class TestTheTwelveFieldsReachTheRow:
    async def test_the_plain_fields_are_applied(self, client_a, board):
        """The half a schema-only change would have missed: these are declared on
        `TaskUpdate` and would be dropped without the handler loop."""
        task = await _task(client_a, board)
        updated = await _put(
            client_a,
            task["id"],
            {
                "task_type": "maintenance_pm",
                "planned_duration": 90,
                "estimated_effort_minutes": 45,
                "tags": ["reactor", "night-shift"],
            },
        )
        assert updated["task_type"] == "maintenance_pm"
        assert updated["planned_duration"] == 90
        assert updated["estimated_effort_minutes"] == 45
        assert updated["tags"] == ["reactor", "night-shift"]

    async def test_they_survive_a_reread(self, client_a, board):
        """The response is built from the in-session object and would show the new value
        whether or not the commit landed."""
        task = await _task(client_a, board)
        await _put(client_a, task["id"], {"estimated_effort_minutes": 15})
        reread = await client_a.get(f"{KANBAN}/tasks/{task['id']}")
        assert reread.json()["estimated_effort_minutes"] == 15

    async def test_an_omitted_field_is_left_alone(self, client_a, board):
        task = await _task(client_a, board)
        await _put(client_a, task["id"], {"planned_duration": 30})
        after = await _put(client_a, task["id"], {"estimated_effort_minutes": 5})
        assert after["planned_duration"] == 30

    async def test_a_link_can_be_cleared_with_an_explicit_null(self, client_a, board):
        """`exclude_unset` rather than `is not None` for the new fields, deliberately:
        these links are nullable and unlinking has to be expressible. The older fields keep
        their `is not None` behaviour so an existing client's `null` still means nothing."""
        task = await _task(client_a, board)
        parent = await _task(client_a, board)
        await _put(client_a, task["id"], {"parent_task_id": parent["id"]})
        cleared = await _put(client_a, task["id"], {"parent_task_id": None})
        assert cleared["parent_task_id"] is None


class TestMovingATaskBetweenBoards:
    async def test_a_move_with_a_destination_column_succeeds(self, client_a, board):
        task = await _task(client_a, board)
        updated = await _put(
            client_a,
            task["id"],
            {"board_id": board["other_board"], "column_id": board["other_column"]},
        )
        assert updated["board_id"] == board["other_board"]
        assert updated["column_id"] == board["other_column"]

    async def test_a_move_without_a_column_is_refused(self, client_a, board):
        """Otherwise the task lands in a column belonging to the board it just left."""
        task = await _task(client_a, board)
        response = await _put(
            client_a, task["id"], {"board_id": board["other_board"]}, expect=400
        )
        assert "column_id" in response.text

    async def test_a_column_from_the_wrong_board_is_refused(self, client_a, board):
        task = await _task(client_a, board)
        await _put(
            client_a,
            task["id"],
            {"board_id": board["other_board"], "column_id": board["columns"][1]["id"]},
            expect=404,
        )

    async def test_a_same_board_column_move_still_works(self, client_a, board):
        """The effective-board change must not break the ordinary case, which is the one
        the drag-and-drop UI performs constantly."""
        task = await _task(client_a, board)
        updated = await _put(client_a, task["id"], {"column_id": board["columns"][1]["id"]})
        assert updated["column_id"] == board["columns"][1]["id"]


class TestAParentCannotCloseACycle:
    async def test_a_task_cannot_be_its_own_parent(self, client_a, board):
        task = await _task(client_a, board)
        await _put(client_a, task["id"], {"parent_task_id": task["id"]}, expect=400)

    async def test_a_two_task_cycle_is_refused(self, client_a, board):
        """Two tasks each other's parent will hang anything that renders a task tree."""
        first = await _task(client_a, board)
        second = await _task(client_a, board)
        await _put(client_a, second["id"], {"parent_task_id": first["id"]})
        await _put(client_a, first["id"], {"parent_task_id": second["id"]}, expect=400)

    async def test_a_legitimate_parent_is_accepted(self, client_a, board):
        """The negative control. A cycle check that refuses everything would pass the two
        tests above and break the feature."""
        parent = await _task(client_a, board)
        child = await _task(client_a, board)
        updated = await _put(client_a, child["id"], {"parent_task_id": parent["id"]})
        assert updated["parent_task_id"] == parent["id"]

    async def test_an_unknown_parent_is_a_404(self, client_a, board):
        task = await _task(client_a, board)
        await _put(client_a, task["id"], {"parent_task_id": str(uuid.uuid4())}, expect=404)


class TestATaskRule:
    async def _rule(self, client_a):
        response = await client_a.post(
            f"{KANBAN}/rules",
            json={
                "rule_name": f"FS677 {uuid.uuid4().hex[:6]}",
                "trigger_type": "alarm_raised",
            },
        )
        assert response.status_code in (200, 201), response.text
        return response.json()

    async def test_a_rule_can_be_created_without_a_tenant_in_the_body(self, client_a, board):
        """The thirteenth FS-523. `TaskRuleCreate` required an `organization_id` that
        `create_task_rule` discards, so the natural client got 422 on every attempt."""
        rule = await self._rule(client_a)
        assert rule["rule_name"].startswith("FS677")

    async def test_the_routing_fields_can_be_corrected(self, client_a, board):
        rule = await self._rule(client_a)
        response = await client_a.put(
            f"{KANBAN}/rules/{rule['id']}",
            json={
                "trigger_type": "threshold_breach",
                "target_board_id": board["board_id"],
                "target_column_id": board["columns"][0]["id"],
                "completion_actions": {"notify": True},
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["trigger_type"] == "threshold_breach"
        assert body["target_board_id"] == board["board_id"]
        assert body["completion_actions"] == {"notify": True}

    async def test_an_omitted_field_is_left_alone(self, client_a, board):
        rule = await self._rule(client_a)
        await client_a.put(
            f"{KANBAN}/rules/{rule['id']}", json={"target_board_id": board["board_id"]}
        )
        response = await client_a.put(
            f"{KANBAN}/rules/{rule['id']}", json={"rule_name": "FS677 renamed"}
        )
        assert response.json()["target_board_id"] == board["board_id"]

    async def test_a_nullable_link_can_be_cleared(self, client_a, board):
        rule = await self._rule(client_a)
        await client_a.put(
            f"{KANBAN}/rules/{rule['id']}",
            json={"specific_assignee_id": str(uuid.uuid4())},
        )
        response = await client_a.put(
            f"{KANBAN}/rules/{rule['id']}", json={"specific_assignee_id": None}
        )
        assert response.json()["specific_assignee_id"] is None
