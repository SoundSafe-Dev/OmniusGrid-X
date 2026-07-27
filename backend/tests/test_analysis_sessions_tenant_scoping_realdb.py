"""The NLP analysis-session surface must work, and stay inside the tenant.

THE DEFECT. `analysis_sessions` is RLS-protected, and all 22 handlers in
`analysis_sessions.py` ran on `get_db`, which sets no `app.current_org_id`. The entire
feature was dead — and it failed in **both** directions at once:

    POST /api/v1/nlp/sessions   -> 500  InsufficientPrivilegeError:
                                        new row violates row-level security policy
    GET  /api/v1/nlp/sessions   -> 200  []          (matched nothing)
    GET  /api/v1/nlp/sessions/{id} -> 404

WHY THE SPLIT MATTERS. Under RLS a **read fails silently** — the policy filters rows and
the endpoint returns an empty list — while a **write fails loudly**, because the policy's
WITH CHECK rejects the INSERT outright. Every other defect in this sweep was the quiet
kind, which is exactly why they survived. This one would have been noticed the first time
anyone opened the feature, which suggests nobody had.

The application layer was correct throughout: `organization_id=current_user.organization_id`
was already set on create. Only the GUC was missing.

NOT IN THIS WEEK'S TASK POOL. Kanban RLS (#16) and `/nlp/correlation/intake/{id}` (#17)
are, and are deliberately untouched.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def _rows(payload):
    if isinstance(payload, dict):
        for key in ("sessions", "items", "data"):
            if key in payload:
                return payload[key]
    return payload


class TestASessionCanBeCreatedAtAll:
    async def test_creating_a_session_succeeds(self, client_a):
        """THE ASSERTION THIS FILE EXISTS FOR. This raised
        InsufficientPrivilegeError — a 500 — because the RLS policy's WITH CHECK
        rejects an INSERT made with no tenant GUC."""
        response = await client_a.post(
            "/api/v1/nlp/sessions", json={"title": "scoping test"}
        )
        assert response.status_code == 200, response.text
        assert response.json().get("id")

    async def test_the_created_session_is_listed(self, client_a):
        """A 200 from create proves the INSERT passed the policy, not that the row is
        readable — the read path has its own USING clause."""
        created = await client_a.post(
            "/api/v1/nlp/sessions", json={"title": "listed"}
        )
        session_id = created.json()["id"]

        listing = await client_a.get("/api/v1/nlp/sessions")
        assert listing.status_code == 200, listing.text
        assert session_id in {row.get("id") for row in _rows(listing.json())}

    async def test_the_created_session_is_fetchable(self, client_a):
        created = await client_a.post("/api/v1/nlp/sessions", json={"title": "fetched"})
        session_id = created.json()["id"]

        response = await client_a.get(f"/api/v1/nlp/sessions/{session_id}")
        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("suffix", ["messages", "data"])
    async def test_the_child_collections_answer(self, client_a, suffix):
        """Messages and data sources hang off the session; if the parent lookup 404s
        they do too, so these are separate assertions rather than assumed."""
        created = await client_a.post("/api/v1/nlp/sessions", json={"title": "children"})
        session_id = created.json()["id"]

        response = await client_a.get(f"/api/v1/nlp/sessions/{session_id}/{suffix}")
        assert response.status_code == 200, response.text


class TestSessionsStayInsideTheTenant:
    async def test_another_orgs_session_is_not_listed(self, client_a, client_b):
        created = await client_a.post("/api/v1/nlp/sessions", json={"title": "org a only"})
        session_id = created.json()["id"]

        listing = await client_b.get("/api/v1/nlp/sessions")
        assert listing.status_code == 200, listing.text
        assert session_id not in {row.get("id") for row in _rows(listing.json())}

    async def test_another_orgs_session_is_404_by_id(self, client_a, client_b):
        """The list filter and the by-id lookup are separate code paths."""
        created = await client_a.post("/api/v1/nlp/sessions", json={"title": "org a only"})
        session_id = created.json()["id"]

        response = await client_b.get(f"/api/v1/nlp/sessions/{session_id}")
        assert response.status_code == 404, response.text

    async def test_each_org_sees_only_its_own(self, client_a, client_b):
        a_id = (await client_a.post("/api/v1/nlp/sessions", json={"title": "A"})).json()["id"]
        b_id = (await client_b.post("/api/v1/nlp/sessions", json={"title": "B"})).json()["id"]

        a_ids = {r.get("id") for r in _rows((await client_a.get("/api/v1/nlp/sessions")).json())}
        b_ids = {r.get("id") for r in _rows((await client_b.get("/api/v1/nlp/sessions")).json())}

        assert a_id in a_ids and a_id not in b_ids
        assert b_id in b_ids and b_id not in a_ids

    async def test_another_org_cannot_delete_it(self, client_a, client_b):
        """A write path aimed at someone else's row must refuse, not silently no-op."""
        created = await client_a.post("/api/v1/nlp/sessions", json={"title": "protected"})
        session_id = created.json()["id"]

        response = await client_b.delete(f"/api/v1/nlp/sessions/{session_id}")
        assert response.status_code == 404, response.text

        still_there = await client_a.get(f"/api/v1/nlp/sessions/{session_id}")
        assert still_there.status_code == 200, "the session was deleted by another tenant"
