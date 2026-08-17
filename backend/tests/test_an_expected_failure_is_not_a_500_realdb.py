"""A failure the code anticipated must not arrive as a 500 (FS-742).

THE POPULATION, AND WHY IT IS SMALL. The API contract gate drives all 546 operations with
generated input. Separating real 500s from declared 503s (FS-741) left **eight** operations
that genuinely returned a 500. This file pins the six that were fixed here; the other two
are `POST /users/` (a NUL byte reaching Postgres) and `PUT /user/context`, recorded in
`docs/engineering/api-contract-gate.md`.

Not one of them was an unanticipated crash. Every one was a condition the code had thought
about, arriving through a door nobody had wired up:

    logistics x2   `raise ValueError("Shipment not found")` — the engine says exactly what
                   happened, in the right vocabulary for a service, and no route listened
    fleet          `PermissionError` from `mkdir` under an unwritable release root — the
                   artifact store being unavailable is not the caller's mistake
    rag            `httpx.ConnectError` — the handler catches `RuntimeError` under a comment
                   reading "inference/vector store unavailable", which is precisely this
                   case; the commonest form of it just is not a `RuntimeError`
    correlation    the route's own response model declares `Dict[str, List[str]]` and the
                   background branch passed a string, so FastAPI failed to serialise its own
                   response
    kanban         `board_id: ""` compared against a `uuid` column; asyncpg raises rather
                   than returning no rows

WHY A 500 IS THE WRONG ANSWER TO EACH. A 500 tells a caller "your request was fine and we
broke" — so a client retries a 404 forever, an operator investigating 500s on release upload
has no reason to check disk permissions, and a monitoring page cannot tell an outage from a
bug. The status code is the only channel these distinctions travel on.

WHAT THIS ASSERTS. Not the exact code for every case — that would pin decisions this file
should not own — but that each of these operations answers something DECLARED. The two
tests below split on the thing that matters: a caller error (4xx) versus a dependency outage
(503), because those are the two honest answers and 500 is neither.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio

#: A shipment id belonging to nobody. The engine's own "not found" path.
ABSENT = "e3e70682-c209-1cac-a29f-6fbed82c07cd"

#: (label, method, path, body, the statuses that are honest answers)
CASES = [
    (
        "logistics readiness, absent shipment",
        "get",
        f"/api/v1/logistics/truck-asset-readiness?shipment_id={ABSENT}",
        None,
        {404},
    ),
    (
        "logistics optimise, absent shipment",
        "post",
        f"/api/v1/logistics/optimize-assignment?shipment_id={ABSENT}",
        None,
        {404},
    ),
    (
        "kanban task, unparseable board id",
        "post",
        "/api/v1/kanban/tasks",
        {"board_id": "", "column_id": "", "task_type": "custom", "title": "x"},
        {404, 422},
    ),
    (
        "correlation analyse, empty metrics",
        "post",
        "/api/v1/engines/correlation/integration/analyze",
        {"metrics": {}},
        {200},
    ),
    (
        "fleet release, artifact store unwritable",
        "post",
        "/api/v1/fleet/releases",
        {"config_bundle": "0", "image_tag": "0", "version": "0"},
        {201, 400, 503},
    ),
    (
        "rag query, inference host unreachable",
        "post",
        "/api/v1/rag/query",
        {"query": "0"},
        {200, 503},
    ),
]


class TestNoAnticipatedFailureIsA500:
    @pytest.mark.parametrize(
        "label,method,path,body,allowed", CASES, ids=[c[0] for c in CASES]
    )
    async def test_it_answers_a_declared_status(
        self, client_a, label, method, path, body, allowed
    ):
        call = getattr(client_a, method)
        response = await (call(path) if body is None else call(path, json=body))
        assert response.status_code != 500, (
            f"{label}: 500. This condition is one the code anticipated — it has a "
            f"`raise`, an `except`, or a declared type covering it — and a 500 tells the "
            f"caller their request was fine and we broke. {response.text[:200]}"
        )
        assert response.status_code in allowed, (
            f"{label}: {response.status_code}, expected one of {sorted(allowed)}. "
            f"{response.text[:200]}"
        )


class TestTheCorrelationRouteKeepsItsContract:
    """The correlation 500 was FastAPI refusing to serialise the route's own response.
    Widening the model to `Dict[str, Any]` would have silenced it and cost the contract
    (rule 187), so the shape stayed and the queued state got its own field."""

    async def test_the_queued_shape_is_the_declared_shape(self, client_a):
        response = await client_a.post(
            "/api/v1/engines/correlation/integration/analyze",
            json={"metrics": {}, "auto_create_registry_items": True},
        )
        assert response.status_code == 200, response.text[:300]
        body = response.json()
        assert body["integration_queued"] is True, (
            "the work was handed to a background task and the response does not say so — "
            "so empty result lists read as 'produced nothing'"
        )
        for key, value in body["integration_result"].items():
            assert isinstance(value, list), (
                f"integration_result[{key!r}] is {type(value).__name__}, and the model "
                f"declares List[str]. This is the exact mismatch that made the route 500."
            )

    async def test_an_unqueued_analysis_says_so(self, client_a):
        response = await client_a.post(
            "/api/v1/engines/correlation/integration/analyze",
            json={
                "metrics": {},
                "auto_create_tasks": False,
                "auto_create_registry_items": False,
                "auto_create_correlations": False,
            },
        )
        assert response.status_code == 200, response.text[:300]
        assert response.json()["integration_queued"] is False, (
            "nothing was queued and the response claims it was — the flag has to "
            "distinguish, or it is decoration"
        )


class TestTheIntegrationActuallyRuns:
    """THE DEFECT THE 500 WAS HIDING. Once the route stopped erroring, the background task
    it schedules turned out to write on `AsyncSessionLocal()` — no `app.current_org_id`, so
    RLS refused every INSERT and the `except` logged and continued. The caller was told
    their analysis was integrated; nothing was created, ever."""

    async def test_registry_items_are_created(self, client_a, admin_sync_url, seeded_orgs):
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM actionable_registries WHERE organization_id = %s",
                (str(seeded_orgs["org_a_id"]),),
            )
            before = cur.fetchone()[0]

        response = await client_a.post(
            "/api/v1/engines/correlation/integration/analyze",
            json={"metrics": {}, "auto_create_registry_items": True},
        )
        assert response.status_code == 200, response.text[:300]

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM actionable_registries WHERE organization_id = %s",
                (str(seeded_orgs["org_a_id"]),),
            )
            after = cur.fetchone()[0]
        conn.close()
        assert after > before, (
            "the route reported success and the background integration created nothing. "
            "That is the shape this whole file is about: a side-effect path whose failure "
            "is invisible from the response."
        )
