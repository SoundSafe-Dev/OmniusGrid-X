"""The rows a tenant owns come back to them (FS-431).

FOUR ENDPOINTS WERE ALLOWLISTED TO 5xx. Thirteen more in the same two files had the same
root cause and were never probed by anything, so nothing recorded what they were doing:
answering **200 with an empty list**.

That is the half of this failure mode that survives review. `list_task_rules` filters on
`organization_id` itself and is CORRECT to — it makes no difference, because
`task_rules` is FORCE ROW LEVEL SECURITY and the policy had already removed the row on a
session with no `app.current_org_id`. Nothing in a code review of that handler points at
the session. The automation-rules screen showed an empty list to every tenant that had
rules, and the only visible symptom was a screen that looked new.

WHY A STRUCTURAL GUARD IS NOT ENOUGH. `test_lane_failure_root_causes_stay_fixed` asserts
that `Depends(get_db)` is gone, which is the mechanism. This asserts the CONSEQUENCE, with
a row that plainly exists, against a real Postgres with RLS enforced. The two fail for
different reasons: a future handler could bind the tenant session and still filter itself
into emptiness, and only this one would notice.

The 5xx walks cannot cover this. They ask whether an endpoint errored, and an endpoint
that answers 200 about rows it cannot see has not errored.

MEASURED BY PUTTING THE DEFECT BACK. Reverting both files to `Depends(get_db)`:

    FAIL  /kanban/rules                     200, **0 rows**, with the rule sitting there
    FAIL  /nlp/correlation/intake/list      200, **0 rows**
    FAIL  /nlp/correlation/intake/{id}      404 for an item the caller owns
    FAIL  /kanban/board                     500
    FAIL  /kanban/metrics, /workload        500
    FAIL  POST /kanban/board/view           500
    pass  /kanban/rules/premade             (takes no session)
    pass  org B cannot see org A's rule
    pass  org B cannot read org A's item

**THE LAST TWO ARE THE WARNING.** Both tenant-isolation assertions pass while the system is
comprehensively broken, because "org B cannot see org A's rule" is satisfied perfectly by
nobody being able to see anything. An isolation suite alone would have called this healthy
and been right about the only question it asked. Proving that a tenant cannot see what is
not theirs is worth nothing without also proving they can see what is.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

pytest.importorskip("testcontainers")


@pytest_asyncio.fixture
async def owned_task_rule(admin_sync_url, seeded_orgs):
    """One automation rule belonging to org A, inserted past RLS as a superuser."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    rule_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO task_rules (id, organization_id, rule_name, trigger_type, "
            "is_active) VALUES (%s, %s, %s, 'alarm_created', true)",
            (str(rule_id), str(seeded_orgs["org_a_id"]), f"Rule {rule_id.hex[:8]}"),
        )
    yield rule_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM task_rules WHERE id = %s", (str(rule_id),))
    conn.close()


@pytest_asyncio.fixture
async def owned_intake_item(admin_sync_url, seeded_orgs):
    """One intake item belonging to org A's user."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    item_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO intake_items (id, organization_id, user_id, title, status) "
            "VALUES (%s, %s, %s, %s, 'pending')",
            (
                str(item_id),
                str(seeded_orgs["org_a_id"]),
                str(seeded_orgs["user_a_id"]),
                f"Intake {item_id.hex[:8]}",
            ),
        )
    yield item_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM intake_items WHERE id = %s", (str(item_id),))
    conn.close()


class TestTheQuietHalf:
    """200 with nothing in it. No error, no clue, and a screen that looks merely new."""

    async def test_the_rules_list_contains_the_org_s_rule(self, client_a, owned_task_rule):
        response = await client_a.get("/api/v1/kanban/rules")
        assert response.status_code == 200, response.text
        body = response.json()
        assert any(row["id"] == str(owned_task_rule) for row in body), (
            f"/kanban/rules returned {len(body)} rows and none is the caller's own rule. "
            f"The handler filters on organization_id and is right to; RLS removed the row "
            f"before that filter ran"
        )

    async def test_the_intake_list_contains_the_user_s_item(
        self, client_a, owned_intake_item
    ):
        response = await client_a.get("/api/v1/nlp/correlation/intake/list")
        assert response.status_code == 200, response.text
        body = response.json()
        rows = body if isinstance(body, list) else body.get("items", body.get("data", []))
        assert any(str(row.get("id")) == str(owned_intake_item) for row in rows), (
            f"the intake list returned {len(rows)} rows and none is the caller's own item"
        )


class TestTheLoudHalf:
    """The endpoints that were allowlisted to 500, asserted to answer about real rows."""

    async def test_the_intake_item_is_readable_by_id(self, client_a, owned_intake_item):
        """This 500'd on every call — `select()` was given the module's PYDANTIC
        `IntakeItem` rather than the ORM class it imports as `IntakeItemModel`."""
        response = await client_a.get(
            f"/api/v1/nlp/correlation/intake/{owned_intake_item}"
        )
        assert response.status_code == 200, (
            f"reading an intake item the caller owns answered {response.status_code}: "
            f"{response.text[:200]}"
        )
        assert str(response.json()["id"]) == str(owned_intake_item)

    async def test_the_board_is_created_on_first_read(self, client_a):
        """`/kanban/board` INSERTs a default board when the org has none. On the unscoped
        session that INSERT was refused by RLS, so a brand-new organisation's board never
        rendered — and the same one write served /metrics, /workload and the view POST."""
        response = await client_a.get("/api/v1/kanban/board")
        assert response.status_code == 200, response.text
        assert response.json().get("columns"), (
            "the board came back with no columns, so the default board was not created"
        )

    @pytest.mark.parametrize("path", ["/api/v1/kanban/metrics", "/api/v1/kanban/workload"])
    async def test_the_board_derived_reads_answer(self, client_a, path):
        assert (await client_a.get(path)).status_code == 200

    async def test_the_view_post_answers(self, client_a):
        response = await client_a.post("/api/v1/kanban/board/view", json={})
        assert response.status_code == 200, response.text

    async def test_the_premade_templates_are_listed(self, client_a):
        """Five static constants, declared as `List[TaskRuleResponse]` — a model needing a
        UUID id, an organization_id and timestamps a template cannot have. Response
        validation raised on every call, on any database."""
        response = await client_a.get("/api/v1/kanban/rules/premade")
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body) == 5
        assert all(row["template_id"].startswith("template-") for row in body)


class TestTheOtherTenantStillSeesNothing:
    """The fix binds a tenant to the session. If it bound the wrong one — or none — this
    is what would catch it, and it is the assertion that makes the two above meaningful."""

    async def test_org_b_does_not_see_org_a_s_rule(self, client_b, owned_task_rule):
        body = (await client_b.get("/api/v1/kanban/rules")).json()
        assert not any(row["id"] == str(owned_task_rule) for row in body), (
            "org B can see org A's automation rule"
        )

    async def test_org_b_cannot_read_org_a_s_intake_item(
        self, client_b, owned_intake_item
    ):
        response = await client_b.get(
            f"/api/v1/nlp/correlation/intake/{owned_intake_item}"
        )
        assert response.status_code == 404, (
            f"org B read org A's intake item: {response.status_code}"
        )
