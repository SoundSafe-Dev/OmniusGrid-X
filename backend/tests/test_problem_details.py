"""FS-102: RFC-9457 (application/problem+json) additive conformance.

Verifies that error responses produced by the app's exception handlers carry
the four standard problem-details members (``type``/``title``/``status``/
``instance``) AND still carry the existing OmniusGrid envelope
(``error.code`` + ``detail`` mirror), and that the ``Content-Type`` is the
RFC-9457 media type. A minimal app mounts the real handlers so no DB or full
app import is needed.
"""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import AppError, register_exception_handlers


class _Body(BaseModel):
    n: int


def _app() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/thing")
    def thing():
        raise HTTPException(status_code=404, detail="thing not found")

    @app.post("/validate")
    def validate(body: _Body):
        return {"ok": body.n}

    @app.get("/conflict")
    def conflict():
        raise AppError("already exists", code="conflict", status_code=409)

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return TestClient(app, raise_server_exceptions=False)


def _assert_problem(body: dict, *, status_code: int, code: str, instance: str):
    # RFC-9457 members present.
    assert body["title"], "title should be a non-empty human summary"
    assert body["status"] == status_code
    assert body["instance"] == instance
    assert isinstance(body["type"], str) and body["type"]
    # Existing OmniusGrid envelope preserved (back-compat).
    assert body["error"]["code"] == code
    assert body["detail"] == body["error"]["message"]


def test_404_carries_problem_and_legacy_fields():
    r = _app().get("/thing")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    _assert_problem(body, status_code=404, code="not_found", instance="/thing")
    assert body["type"] == "https://omniusgrid.dev/problems/not_found"
    assert body["title"] == "Not Found"
    assert body["detail"] == "thing not found"


def test_422_validation_carries_problem_and_legacy_fields():
    r = _app().post("/validate", json={"n": "not-an-int"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    _assert_problem(body, status_code=422, code="validation_error", instance="/validate")
    # Validation details still surfaced under the legacy envelope.
    assert "errors" in body["error"]["details"]


def test_app_error_problem_type_uses_machine_code():
    r = _app().get("/conflict")
    assert r.status_code == 409
    body = r.json()
    _assert_problem(body, status_code=409, code="conflict", instance="/conflict")
    assert body["type"] == "https://omniusgrid.dev/problems/conflict"


def test_500_carries_problem_type_and_masks_internals():
    r = _app().get("/boom")
    assert r.status_code == 500
    body = r.json()
    _assert_problem(body, status_code=500, code="internal_error", instance="/boom")
    assert body["type"] == "https://omniusgrid.dev/problems/internal_error"
    assert "kaboom" not in r.text  # internals never leaked
