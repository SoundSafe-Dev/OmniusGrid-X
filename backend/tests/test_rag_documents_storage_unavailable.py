"""GET /rag/documents must degrade to 503 when SeaweedFS is unreachable.

Covers the bug where a raw infrastructure connection error (naming internal
hosts/ports) was surfaced verbatim to the client instead of a generic 503.
Split into two layers:

- ``DocumentStore.list_documents`` normalizes any connection failure into a
  client-safe ``RuntimeError``, logging the real exception server-side.
- The route converts that ``RuntimeError`` into an HTTP 503 with the generic
  message, never the original exception text.

DB-free by design (same pattern as ``test_route_auth_walk.py``): auth and
tenant-db dependencies are overridden with inert stand-ins so the route walk
never touches a real database.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.rag as rag_module
import app.services.document_store as document_store_module
from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db
from app.db.database import get_db
from app.main import app
from app.services.document_store import DocumentStore

RAW_CONNECTION_ERROR = "Could not connect to the endpoint URL: http://seaweedfs:8333/raw-bucket"


class _FailingClientCtx:
    """Stands in for the aioboto3 S3 client, failing like a dead SeaweedFS."""

    async def __aenter__(self):
        raise OSError(RAW_CONNECTION_ERROR)

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_list_documents_normalizes_connection_error(monkeypatch):
    store = DocumentStore.__new__(DocumentStore)
    store.raw_bucket = "raw-bucket"
    store.text_bucket = "text-bucket"
    store._session = object()  # truthy: .available reads True without real aioboto3

    logged = {}
    monkeypatch.setattr(
        document_store_module.logger,
        "error",
        lambda event, **kwargs: logged.update(event=event, **kwargs),
    )
    monkeypatch.setattr(store, "_require_client", lambda: _FailingClientCtx())

    with pytest.raises(RuntimeError) as exc_info:
        await store.list_documents(prefix="org-1/")

    message = str(exc_info.value)
    assert message == "Document store is currently unavailable."
    assert "seaweedfs" not in message.lower()
    assert "8333" not in message

    # The real detail is preserved server-side, just not handed to the caller.
    assert logged["event"] == "document_store.list_failed"
    assert RAW_CONNECTION_ERROR in logged["error"]


async def _no_db():
    yield None


class _UnavailableDocs:
    available = True

    async def list_documents(self, prefix=""):
        raise RuntimeError("Document store is currently unavailable.")


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_db] = _no_db
    app.dependency_overrides[get_tenant_db] = _no_db

    async def _user():
        return SimpleNamespace(
            id=uuid4(), organization_id=uuid4(), role="admin", is_active=True,
        )

    app.dependency_overrides[get_current_active_user] = _user
    monkeypatch.setattr(rag_module, "get_document_store", lambda: _UnavailableDocs())

    yield TestClient(app, raise_server_exceptions=False)

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_tenant_db, None)
    app.dependency_overrides.pop(get_current_active_user, None)


def test_documents_endpoint_returns_503_not_the_raw_error(client):
    resp = client.get("/api/v1/rag/documents")

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"] == "Document store is currently unavailable."
    assert "seaweedfs" not in resp.text.lower()
    assert "8333" not in resp.text
