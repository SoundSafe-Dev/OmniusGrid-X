from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.csrf import CSRFMiddleware


def _csrf_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.get("/csrf")
    async def csrf_seed():
        return {"ok": True}

    @app.post("/write")
    async def write():
        return {"ok": True}

    return app


def test_missing_and_mismatched_csrf_tokens_return_json_403():
    client = TestClient(_csrf_app())

    missing = client.post("/write")
    header_missing = client.post("/write", cookies={"csrf_token": "cookie-token"})
    mismatch = client.post(
        "/write",
        cookies={"csrf_token": "cookie-token"},
        headers={"X-CSRF-Token": "header-token"},
    )

    assert missing.status_code == 403
    assert header_missing.status_code == 403
    assert mismatch.status_code == 403
    assert missing.json()["detail"].startswith("CSRF token missing")


def test_valid_csrf_token_is_rotated_after_write():
    client = TestClient(_csrf_app())
    seed = client.get("/csrf")
    token = seed.headers["X-CSRF-Token"]

    response = client.post(
        "/write",
        cookies={"csrf_token": token},
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 200
    assert response.headers["X-CSRF-Token"] != token


def test_bearer_write_does_not_require_csrf_token():
    client = TestClient(_csrf_app())

    response = client.post(
        "/write",
        headers={"Authorization": "Bearer local-access-token"},
    )

    assert response.status_code == 200
