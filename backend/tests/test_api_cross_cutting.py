"""Tests for cross-cutting API primitives: error envelope, pagination,
request-context, idempotency (tasks 7-10).

Each builds a minimal FastAPI app wired with the primitive under test, so no DB
or full app import is needed.
"""

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import AppError, register_exception_handlers
from app.core.pagination import PageParams, PaginatedResponse, paginate
from app.middleware.idempotency import IdempotencyMiddleware, InMemoryIdempotencyStore
from app.middleware.request_context import RequestContextMiddleware


# --- task 7: error envelope --------------------------------------------------

def _err_app():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom-http")
    def boom_http():
        raise HTTPException(status_code=404, detail="thing not found")

    @app.get("/boom-app")
    def boom_app():
        raise AppError("nope", code="custom_code", status_code=409, details={"x": 1})

    @app.get("/boom-500")
    def boom_500():
        raise RuntimeError("kaboom")

    return TestClient(app, raise_server_exceptions=False)


def test_http_exception_envelope_and_detail_mirror():
    r = _err_app().get("/boom-http")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "thing not found"
    assert body["detail"] == "thing not found"  # back-compat mirror preserved


def test_app_error_uses_custom_code_and_details():
    r = _err_app().get("/boom-app")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "custom_code"
    assert r.json()["error"]["details"] == {"x": 1}


def test_unhandled_exception_is_masked_500():
    r = _err_app().get("/boom-500")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "kaboom" not in r.text  # internals not leaked


# --- task 8: pagination ------------------------------------------------------

class Thing(BaseModel):
    id: int


def test_pagination_envelope_has_more():
    app = FastAPI()

    @app.get("/things", response_model=PaginatedResponse[Thing])
    def things(page: PageParams = Depends()):
        allrows = [Thing(id=i) for i in range(10)]
        window = allrows[page.skip : page.skip + page.limit]
        return paginate(window, total=len(allrows), page=page)

    client = TestClient(app)
    r = client.get("/things?skip=0&limit=3").json()
    assert [t["id"] for t in r["items"]] == [0, 1, 2]
    assert r["meta"] == {"total": 10, "skip": 0, "limit": 3, "count": 3, "has_more": True}

    last = client.get("/things?skip=9&limit=3").json()
    assert last["meta"]["has_more"] is False


# --- task 9: request context -------------------------------------------------

def test_request_id_generated_and_echoed():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    r = TestClient(app).get("/ping")
    assert "X-Request-ID" in r.headers and len(r.headers["X-Request-ID"]) > 0


def test_request_id_honoured_from_header():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    r = TestClient(app).get("/ping", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


# --- task 10: idempotency ----------------------------------------------------

def _idem_app():
    app = FastAPI()
    app.add_middleware(
        IdempotencyMiddleware,
        protected_prefixes=("/api/v1/operations",),
        store=InMemoryIdempotencyStore(),
    )
    state = {"calls": 0}

    @app.post("/api/v1/operations/do")
    def do():
        state["calls"] += 1
        return {"calls": state["calls"]}

    @app.post("/api/v1/other/do")
    def other():
        state["calls"] += 1
        return {"calls": state["calls"]}

    return TestClient(app), state


def test_idempotent_replay_same_key():
    client, state = _idem_app()
    h = {"Idempotency-Key": "k1"}
    first = client.post("/api/v1/operations/do", headers=h)
    second = client.post("/api/v1/operations/do", headers=h)
    assert first.json() == second.json() == {"calls": 1}      # action ran once
    assert second.headers.get("Idempotency-Replayed") == "true"
    assert state["calls"] == 1


def test_no_key_runs_every_time():
    client, state = _idem_app()
    client.post("/api/v1/operations/do")
    client.post("/api/v1/operations/do")
    assert state["calls"] == 2


def test_out_of_scope_path_not_deduped():
    client, state = _idem_app()
    h = {"Idempotency-Key": "k2"}
    client.post("/api/v1/other/do", headers=h)
    client.post("/api/v1/other/do", headers=h)
    assert state["calls"] == 2  # /other is not a protected prefix


# --- task 11: OpenAPI operationId polish -------------------------------------

def test_clean_operation_ids():
    from app.core.openapi import custom_generate_unique_id

    app = FastAPI(generate_unique_id_function=custom_generate_unique_id)

    @app.get("/api/v1/edge/fleet", tags=["Edge"])
    def list_fleet():
        return []

    schema = app.openapi()
    op_id = schema["paths"]["/api/v1/edge/fleet"]["get"]["operationId"]
    assert op_id == "edge_list_fleet"  # <tag>_<route_name>, no path noise
