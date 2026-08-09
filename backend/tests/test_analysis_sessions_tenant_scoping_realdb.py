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
kind, which is exactly why they survived.

A 500 on create would normally have been noticed immediately — but the correlation model
and its LoRA adapter are DELIBERATELY not loaded at the moment, so this surface is meant
to be dormant. Nobody exercising it is the expected state, not evidence of neglect.

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


class TestSimulatedAnalysisIsLabelledAsSuch:
    """The correlation model and its LoRA adapter are DELIBERATELY not loaded right
    now, so `correlation_ai_engine` serves a heuristic fallback. It marks that output
    `simulated: True` with confidence dropped to 0.4 — honestly.

    Both chat handlers read the fallback's text and DISCARDED the flag, so heuristic
    output reached the caller indistinguishable from a real inference.

    This was latent while the RLS defect above made these endpoints unreachable.
    Fixing that made it live, which is why it is fixed in the same pass: a change that
    turns a dead path into a working one owns whatever that path then does.

    WHAT THIS CLASS DOES NOT COVER. Every assertion here exercises the FALLBACK, because
    that is the current state. The `simulated: false` branch has never run against a real
    adapter — `test_the_flag_is_not_hardcoded` patches the engine to force one, which
    proves the plumbing forwards it and nothing about whether a loaded adapter produces
    it. When the LoRA is restored, confirm a real inference returns `simulated: false`
    with a confidence above the fallback's 0.4; if it still says `true`, the adapter did
    not load and the engine is serving heuristics under a model-version string that
    suggests otherwise. See docs/CORRELATION_AI_ENGINE.md, "Current state".
    """

    async def test_the_response_says_it_was_simulated(self, client_a):
        session_id = (
            await client_a.post("/api/v1/nlp/sessions", json={"title": "provenance"})
        ).json()["id"]

        response = await client_a.post(
            f"/api/v1/nlp/sessions/{session_id}/chat",
            json={"message": "why is line 3 down?"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["simulated"] is True, (
            "heuristic output is being presented as a real model inference — the "
            "engine set simulated=True and the endpoint dropped it"
        )

    async def test_the_reason_and_confidence_come_through(self, client_a):
        """`simulated: true` alone tells a caller something is off but not what. The
        engine supplies both; neither should be lost."""
        session_id = (
            await client_a.post("/api/v1/nlp/sessions", json={"title": "provenance 2"})
        ).json()["id"]

        body = (
            await client_a.post(
                f"/api/v1/nlp/sessions/{session_id}/chat",
                json={"message": "explain the correlation"},
            )
        ).json()
        assert body["simulation_reason"], "no reason given for the simulated result"
        assert body["confidence"] == 0.4, (
            f"expected the fallback's lowered confidence, got {body['confidence']}"
        )
        assert body["model_version"] == "fallback-chat"

    async def test_the_flag_is_not_hardcoded(self, client_a, monkeypatch):
        """Guards the guard: if `simulated` were pinned True, the assertions above
        would pass no matter what the engine returned. Force a non-simulated result
        and confirm it comes through as False."""
        from app.services import correlation_ai_engine as engine_module

        async def _fake_chat(message, context=None):
            return {
                "response_text": "real inference",
                "simulated": False,
                "confidence": 0.92,
                "model_version": "gemma-4-lora-v2",
                "follow_up_questions": [],
            }

        monkeypatch.setattr(engine_module.correlation_ai_engine, "chat", _fake_chat)
        session_id = (
            await client_a.post("/api/v1/nlp/sessions", json={"title": "not simulated"})
        ).json()["id"]

        body = (
            await client_a.post(
                f"/api/v1/nlp/sessions/{session_id}/chat", json={"message": "hello"}
            )
        ).json()
        assert body["simulated"] is False
        assert body["confidence"] == 0.92
        assert body["model_version"] == "gemma-4-lora-v2"


class TestTheLastResortFallbackAdmitsItIsOne:
    """The path taken when the correlation engine RAISES, rather than when it falls
    back to its heuristic.

    `SessionChatResponse.simulated` defaults to False, and this handler constructed the
    response without those fields at all — so the one reply that is not an analysis in
    any sense was the only one asserting it was a genuine inference. The two paths above
    it carry the flag through deliberately ("never defaulted to False here"); the
    exception handler undid exactly that discipline, and it is reachable today because
    the model and its LoRA adapter are deliberately not loaded.

    The old text — "the correlation AI integration is being set up" — described a
    deployment state rather than what happened, so an operator reading it had no way to
    know an exception had been thrown and logged.
    """

    @staticmethod
    def _break_the_engine(monkeypatch):
        from app.services import correlation_ai_engine as engine_module

        async def _raise(*args, **kwargs):
            raise RuntimeError("adapter weights unavailable")

        monkeypatch.setattr(engine_module.correlation_ai_engine, "chat", _raise)
        monkeypatch.setattr(
            engine_module.correlation_ai_engine, "analyze_scenario", _raise
        )

    async def _chat(self, client_a):
        session_id = (
            await client_a.post("/api/v1/nlp/sessions", json={"title": "engine down"})
        ).json()["id"]
        return await client_a.post(
            f"/api/v1/nlp/sessions/{session_id}/chat", json={"message": "why did line 3 stop?"}
        )

    async def test_the_request_still_succeeds(self, client_a, monkeypatch):
        """The fallback exists so a failed analysis does not 500. That part was right
        and stays — what changes is what the successful response CLAIMS."""
        self._break_the_engine(monkeypatch)
        response = await self._chat(client_a)
        assert response.status_code == 200, response.text

    async def test_it_is_not_reported_as_a_real_inference(self, client_a, monkeypatch):
        """THE ASSERTION THIS CLASS EXISTS FOR."""
        self._break_the_engine(monkeypatch)
        body = (await self._chat(client_a)).json()
        assert body["simulated"] is True, (
            "the engine raised and produced nothing, yet the response says this was a "
            "genuine inference"
        )

    async def test_the_reason_names_the_failure(self, client_a, monkeypatch):
        self._break_the_engine(monkeypatch)
        body = (await self._chat(client_a)).json()
        assert body["simulation_reason"], "no reason given for a result that is not one"
        assert "failed" in body["simulation_reason"].lower()

    async def test_the_reason_does_not_leak_the_exception_message(
        self, client_a, monkeypatch
    ):
        """An exception message is the field most likely to carry internal detail or
        customer data — the same reason /admin/errors redacts message samples across
        tenants. The type name is enough to triage."""
        self._break_the_engine(monkeypatch)
        body = (await self._chat(client_a)).json()
        assert "adapter weights unavailable" not in body["simulation_reason"]
        assert "RuntimeError" in body["simulation_reason"]

    async def test_no_confidence_is_claimed_for_a_non_result(self, client_a, monkeypatch):
        self._break_the_engine(monkeypatch)
        body = (await self._chat(client_a)).json()
        assert body["confidence"] is None
        assert body["model_version"] is None

    async def test_the_text_describes_the_failure_not_a_rollout(
        self, client_a, monkeypatch
    ):
        self._break_the_engine(monkeypatch)
        body = (await self._chat(client_a)).json()
        assert "being set up" not in body["content"], (
            "the reply blames deployment state for what was an exception"
        )
        assert body["risk_score"] is None, "a risk score implies an analysis happened"
