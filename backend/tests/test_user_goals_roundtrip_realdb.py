"""User goals: created at all, and still there on the next read.

TWO DEFECTS, AND THE FIRST MEANS THE FEATURE HAD NEVER WORKED ONCE.

**`str(UUID())`.** `uuid.UUID` has no zero-argument form — it raises
`TypeError: one of the hex, bytes, bytes_le, fields, or int arguments must be given`.
So `POST /api/v1/user/goals` answered **500 to every caller**, for every input, since it
was written. `userContext.ts:69` calls it from the UI. And because nothing could ever be
created, the PUT and DELETE beside it could only ever answer 404 — the whole goals feature
was dead, behind an endpoint that looked wired.

Found by the contract gate (FS-259), which sent `{"title": ""}` and got a 500. Note what
that means: the input was irrelevant. Any test that had called this endpoint even once,
with anything, would have caught it. There was none.

**The JSON column was mutated in place.** `users.user_goals` is a plain `Column(JSON)`
with no `MutableList`, so SQLAlchemy never sees `.append()` — the attribute is not marked
dirty, no UPDATE is emitted, and the `refresh()` that follows reloads the row without the
goal. The caller gets 200 and their goal is gone.

The handler guarded `if user.user_goals is None: user.user_goals = []` first, which reads
like it rescues the case — an assignment does flag the attribute. But the column is
`Column(JSON, default=[])`, so every user created through the ORM already holds `[]` and
that branch never runs. Measured rather than reasoned: reverting the fix loses the FIRST
goal, not merely the second. `update_user_goal` had the same bug, and its symptom is worse
— 200 carrying the operator's *previous* values, reading as an edit that accepted itself
and then reverted.

`delete_user_goal` builds a new list and assigns it. It was correct all along, in the same
file, which is what makes the other two readable as slips rather than as a misunderstanding.

WHY THIS IS A REAL-DB TEST. Both defects are about what reaches Postgres. A stubbed
session records the `.append()` and reports success; only a real commit-then-reload shows
the row unchanged. This is the same lesson as FS-284b — the only thing that disagrees with
a wrong write is a real row read back.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/user/goals"
CONTEXT = "/api/v1/user/context"


@pytest.fixture(autouse=True)
async def clear_goals(client_a):
    """Goals live on the shared user row, so leave it as it was found."""
    yield
    body = (await client_a.get(CONTEXT)).json()
    for goal in body.get("user_goals") or []:
        await client_a.delete(f"{BASE}/{goal['id']}")


class TestTheEndpointCanCreateAGoalAtAll:
    async def test_creating_a_goal_is_not_a_500(self, client_a):
        """The whole defect, in one assertion. This returned 500 for every input."""
        response = await client_a.post(BASE, json={"title": "Reduce unplanned downtime"})
        assert response.status_code == 200, response.text

    async def test_the_goal_comes_back_with_a_real_uuid(self, client_a):
        from uuid import UUID

        body = (await client_a.post(BASE, json={"title": "Cut changeover time"})).json()
        goal = next(g for g in body["user_goals"] if g["title"] == "Cut changeover time")
        UUID(goal["id"])  # raises if the id is not a uuid

    async def test_an_empty_title_is_not_a_server_error(self, client_a):
        """The exact body the contract gate sent. Whatever the API decides an empty title
        means, it is the caller's business and not a 5xx."""
        response = await client_a.post(BASE, json={"title": ""})
        assert response.status_code < 500, response.text


class TestAGoalSurvivesTheCommit:
    """The in-place-mutation half. Every assertion here reads the goal back through a
    SEPARATE request, because the bug is invisible in the response that created it."""

    async def test_a_created_goal_is_still_there_on_the_next_read(self, client_a):
        await client_a.post(BASE, json={"title": "First goal"})
        body = (await client_a.get(CONTEXT)).json()
        assert [g["title"] for g in body["user_goals"]] == ["First goal"]

    async def test_the_second_goal_is_not_silently_dropped(self, client_a):
        """Mutation-verified: reverting to `.append()` fails this AND the single-goal test
        above, because `Column(JSON, default=[])` means the `is None` rescue branch never
        runs for a real user. Both are kept — one goal proves the write lands, two prove
        it lands on a list that came back from the database."""
        await client_a.post(BASE, json={"title": "First goal"})
        await client_a.post(BASE, json={"title": "Second goal"})

        body = (await client_a.get(CONTEXT)).json()
        titles = sorted(g["title"] for g in body["user_goals"])
        assert titles == ["First goal", "Second goal"], (
            "the second goal was appended to a JSON column in place, so no UPDATE was "
            "emitted and the write was lost while the request returned 200"
        )

    async def test_an_edit_survives_the_commit(self, client_a):
        created = (await client_a.post(BASE, json={"title": "Before"})).json()
        goal_id = next(g["id"] for g in created["user_goals"] if g["title"] == "Before")

        patched = await client_a.put(
            f"{BASE}/{goal_id}", json={"title": "After", "progress": 40}
        )
        assert patched.status_code == 200, patched.text

        body = (await client_a.get(CONTEXT)).json()
        goal = next(g for g in body["user_goals"] if g["id"] == goal_id)
        assert goal["title"] == "After", (
            "the edit mutated a dict inside a JSON column in place; the response carried "
            "the reloaded PREVIOUS value, which reads as an edit that reverted itself"
        )
        assert goal["progress"] == 40

    async def test_deleting_removes_only_that_goal(self, client_a):
        """`delete_user_goal` already reassigned the list. Asserted so the correct one
        cannot regress to match the two that were wrong."""
        first = (await client_a.post(BASE, json={"title": "Keep"})).json()
        await client_a.post(BASE, json={"title": "Remove"})
        body = (await client_a.get(CONTEXT)).json()
        doomed = next(g["id"] for g in body["user_goals"] if g["title"] == "Remove")

        response = await client_a.delete(f"{BASE}/{doomed}")
        assert response.status_code == 200, response.text

        remaining = (await client_a.get(CONTEXT)).json()["user_goals"]
        assert [g["title"] for g in remaining] == ["Keep"]


class TestTheCrashItselfCannotComeBack:
    def test_uuid_takes_no_zero_argument_form(self):
        """Guards the guard. If this ever stops raising, the assertions above stop
        meaning what they say."""
        from uuid import UUID

        with pytest.raises(TypeError):
            UUID()

    def test_no_handler_calls_uuid_with_no_arguments(self):
        """It was the only `UUID()` in the codebase, and it cost a whole feature.

        WALKS THE AST, not the text. The first version of this used a regex over source
        lines and failed on the comment above the fix, which quotes the broken call to
        explain it — a sweep that cannot tell code from prose reports the explanation as
        the defect, and the obvious way to "fix" that is to stop writing the explanation.
        `ast` sees calls only.
        """
        import ast
        import pathlib

        api = pathlib.Path(__file__).resolve().parent.parent / "app"
        offenders = []
        for path in api.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "UUID"
                    and not node.args
                    and not node.keywords
                ):
                    offenders.append(f"{path.relative_to(api.parent)}:{node.lineno}")
        assert not offenders, (
            "`UUID()` raises TypeError — it is never what the author meant, and it is "
            f"always a 500 on the line that runs it: {offenders}"
        )
