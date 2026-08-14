"""The evidence pipeline, driven the way a user drives it: upload, catalog, correlate, ask.

WHY THIS EXISTS. Twenty correlation routes had no HTTP test of any kind. The services under
them are well covered — `test_evidence_engine.py`, `test_operations_question_service.py` and
`test_operational_normalization.py` are 900-odd lines between them — and every one of those
calls the service directly. Nothing had ever sent a request to these routes and read the
body, so everything that lives only at the route boundary was unexercised: the session
dependency, the response model, the background task.

THREE DEFECTS WERE FOUND BY WRITING IT, and all three were invisible to a unit test:

  * `POST /operations/answer` and `POST /operations/briefing` took `Depends(get_db)`. Their
    session goes to `_execute_evidence_request`, which reads `intake_items` — FORCE ROW
    LEVEL SECURITY — so both answered **404 "One or more intake sources were not found"**
    for the caller's own uploads, while `/intake/preview` returned 200 for the same ids.
  * The asynchronous job rebuilt its session with `AsyncSessionLocal()`, under a comment
    claiming every query was scoped explicitly. **Every async evidence job failed**, with
    an error a caller would read as "I passed bad ids".

The static tenant guard could not see any of them: it flags a router that names an
RLS-backed model, and these routers name none — the query is one import away. That guard is
now cross-module, but this file is the check that does not depend on a detector being clever
enough. It asks the system for an answer and looks at what comes back.

WHAT IT PINS. Not the analysis — the numbers belong to the service tests, and asserting a
correlation coefficient here would make this file fail for reasons that are not about HTTP.
It pins that each step reaches a 2xx and that the tenant actually sees their own data, which
is precisely what all three defects broke.
"""

from __future__ import annotations

import asyncio
import io

import pytest

pytestmark = pytest.mark.asyncio

#: Two small sheets that share an entity column, so the engine has a real join to propose.
#: Shared `asset_id` and `shift`, one metric each — the smallest input that produces a
#: candidate join plan rather than an empty graph.
DOWNTIME = b"asset_id,downtime_minutes,shift\nA-1,30,day\nA-2,12,night\nA-1,44,day\n"
DEFECTS = b"asset_id,defects,shift\nA-1,3,day\nA-2,1,night\nA-1,7,day\n"


async def _upload(client, name: str, blob: bytes) -> str:
    response = await client.post(
        "/api/v1/nlp/correlation/intake/upload",
        files={"file": (f"{name}.csv", io.BytesIO(blob), "text/csv")},
        data={"title": name, "data_type": "spreadsheet", "category": "operations"},
    )
    assert response.status_code == 200, f"upload failed: {response.text[:300]}"
    return response.json()["id"]


@pytest.fixture
async def intake_ids(client_a) -> list[str]:
    return [
        await _upload(client_a, "downtime", DOWNTIME),
        await _upload(client_a, "defects", DEFECTS),
    ]


class TestTheSynchronousPath:
    async def test_catalog_lists_the_uploaded_tables(self, client_a, intake_ids):
        response = await client_a.post(
            "/api/v1/correlation/evidence/intake/catalog", json={"intake_ids": intake_ids}
        )
        assert response.status_code == 200, response.text[:300]
        sources = response.json()["sources"]
        assert {s["source_id"] for s in sources} == set(intake_ids), (
            "the catalog did not return the caller's own uploads — the shape a session with "
            "no tenant GUC produces against a FORCE RLS table"
        )

    async def test_preview_proposes_a_join_for_sheets_that_share_a_key(
        self, client_a, intake_ids
    ):
        response = await client_a.post(
            "/api/v1/correlation/evidence/intake/preview", json={"intake_ids": intake_ids}
        )
        assert response.status_code == 200, response.text[:300]
        assert response.json().get("candidate_join_plans"), (
            "two sheets sharing asset_id and shift produced no candidate join. Either the "
            "profiler stopped seeing the shared column or the rows never arrived."
        )

    async def test_analytics_returns_a_result(self, client_a, intake_ids):
        response = await client_a.post(
            "/api/v1/correlation/evidence/intake/analytics", json={"intake_ids": intake_ids}
        )
        assert response.status_code == 200, response.text[:300]


class TestTheOperationsAssistant:
    """Both routes 404'd on the caller's own uploads until FS-718. A 404 here is the exact
    regression, so it is asserted by status rather than by content."""

    async def test_a_question_is_answered_from_the_confirmed_scope(
        self, client_a, intake_ids
    ):
        preview = await client_a.post(
            "/api/v1/correlation/evidence/intake/preview", json={"intake_ids": intake_ids}
        )
        plans = preview.json()["candidate_join_plans"][:1]
        response = await client_a.post(
            "/api/v1/correlation/operations/answer",
            json={
                "intake_ids": intake_ids,
                "join_plans": plans,
                "confirm_join_plan": True,
                "question": "Which asset had the most downtime?",
            },
        )
        assert response.status_code == 200, (
            f"the operations assistant did not answer: {response.text[:300]}\n"
            f"A 404 naming missing intake sources means the session lost its tenant scope."
        )
        assert response.json()["question"] == "Which asset had the most downtime?"

    async def test_a_briefing_is_produced_from_the_same_scope(self, client_a, intake_ids):
        preview = await client_a.post(
            "/api/v1/correlation/evidence/intake/preview", json={"intake_ids": intake_ids}
        )
        response = await client_a.post(
            "/api/v1/correlation/operations/briefing",
            json={
                "intake_ids": intake_ids,
                "join_plans": preview.json()["candidate_join_plans"][:1],
                "confirm_join_plan": True,
            },
        )
        assert response.status_code == 200, response.text[:300]
        assert "overview" in response.json()


class TestTheAsynchronousPath:
    """EVERY job failed before FS-718, and the failure was indistinguishable from the
    caller passing ids that do not exist. The status is the assertion."""

    async def test_a_queued_job_completes_rather_than_failing(self, client_a, intake_ids):
        accepted = await client_a.post(
            "/api/v1/correlation/evidence/intake/jobs", json={"intake_ids": intake_ids}
        )
        assert accepted.status_code == 202, accepted.text[:300]
        job_id = accepted.json()["job_id"]

        for _ in range(40):
            status = await client_a.get(f"/api/v1/correlation/evidence/jobs/{job_id}")
            assert status.status_code == 200, status.text[:300]
            body = status.json()
            if body["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.1)

        assert body["status"] == "completed", (
            f"the job ended as {body['status']} with error {body.get('error')!r}. "
            f"'One or more intake sources were not found' here means the background "
            f"session was rebuilt without the tenant GUC, which is FS-718 returning."
        )
        assert body["result"], "a completed job carried no result"

    async def test_a_job_belongs_to_its_tenant(self, client_a, client_b, intake_ids):
        accepted = await client_a.post(
            "/api/v1/correlation/evidence/intake/jobs", json={"intake_ids": intake_ids}
        )
        job_id = accepted.json()["job_id"]
        assert (
            await client_b.get(f"/api/v1/correlation/evidence/jobs/{job_id}")
        ).status_code == 404, "another organisation could read this job"
