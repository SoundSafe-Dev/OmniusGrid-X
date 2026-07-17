"""FS-103: extended Idempotency-Key coverage on HAMAD-lane mutation surfaces.

Builds a minimal app wired with the IdempotencyMiddleware over the newly-covered
prefixes and asserts replay semantics: same key replays, different key re-runs,
non-mutating GET passes through, out-of-scope prefixes are untouched, and a
failed (non-2xx) mutation is NOT cached so the client can retry.
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.middleware.idempotency import IdempotencyMiddleware, InMemoryIdempotencyStore

# The FS-103 additions (must stay in sync with app.main's protected_prefixes).
NEW_PREFIXES = (
    "/api/v1/assets",
    "/api/v1/alarms",
    "/api/v1/telemetry",
    "/api/v1/maintenance",
    "/api/v1/notifications",
)


def _app():
    app = FastAPI()
    app.add_middleware(
        IdempotencyMiddleware,
        protected_prefixes=NEW_PREFIXES,
        store=InMemoryIdempotencyStore(),
    )
    state = {"calls": 0, "fail_calls": 0}

    @app.post("/api/v1/assets")
    def create_asset():
        state["calls"] += 1
        return {"calls": state["calls"]}

    @app.get("/api/v1/assets")
    def list_assets():
        state["calls"] += 1
        return {"calls": state["calls"]}

    @app.post("/api/v1/notifications")
    def notify():
        state["calls"] += 1
        return {"calls": state["calls"]}

    @app.post("/api/v1/maintenance/fail")
    def fail():
        # Always errors (non-2xx) — must not be cached.
        state["fail_calls"] += 1
        raise HTTPException(status_code=409, detail="conflict")

    @app.post("/api/v1/correlation/do")
    def out_of_scope():
        state["calls"] += 1
        return {"calls": state["calls"]}

    return TestClient(app, raise_server_exceptions=False), state


def test_config_matches_main_registration():
    """Guard: the tested prefixes are actually registered in app.main."""
    import inspect

    from app import main

    src = inspect.getsource(main)
    for prefix in NEW_PREFIXES:
        assert f'"{prefix}"' in src, f"{prefix} not registered in app.main"


@pytest.mark.parametrize("path", ["/api/v1/assets", "/api/v1/notifications"])
def test_same_key_replays_on_new_prefix(path):
    client, state = _app()
    h = {"Idempotency-Key": "k1"}
    first = client.post(path, headers=h)
    second = client.post(path, headers=h)
    assert first.json() == second.json() == {"calls": 1}  # action ran once
    assert second.headers.get("Idempotency-Replayed") == "true"
    assert state["calls"] == 1


def test_different_key_reruns():
    client, state = _app()
    client.post("/api/v1/assets", headers={"Idempotency-Key": "a"})
    client.post("/api/v1/assets", headers={"Idempotency-Key": "b"})
    assert state["calls"] == 2


def test_get_passes_through_uncached():
    client, state = _app()
    h = {"Idempotency-Key": "g1"}
    client.get("/api/v1/assets", headers=h)
    client.get("/api/v1/assets", headers=h)
    assert state["calls"] == 2  # GET is non-mutating; never deduped


def test_failed_mutation_is_not_cached():
    client, state = _app()
    h = {"Idempotency-Key": "f1"}
    first = client.post("/api/v1/maintenance/fail", headers=h)
    second = client.post("/api/v1/maintenance/fail", headers=h)
    assert first.status_code == second.status_code == 409
    # Not replayed, and the handler ran both times so a client can retry.
    assert second.headers.get("Idempotency-Replayed") is None
    assert state["fail_calls"] == 2


def test_out_of_scope_prefix_not_deduped():
    client, state = _app()
    h = {"Idempotency-Key": "o1"}
    client.post("/api/v1/correlation/do", headers=h)
    client.post("/api/v1/correlation/do", headers=h)
    assert state["calls"] == 2  # correlation is another lane; not protected
