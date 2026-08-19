"""POST /rag/query/stream streams citations + generation over SSE (FS-666).

DB-free by design, same pattern as test_route_auth_walk.py's `client` fixture:
get_db/get_tenant_db are overridden with an inert stub and get_current_active_user
is overridden directly, so this needs no Postgres/testcontainers. get_retriever()
is monkeypatched to a fake so no live inference/vector/LLM service is needed
either — this test is about the SSE framing and org-scoping wiring, not the
retrieval pipeline (that's covered live by backend/tests/rag_eval/).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import AsyncIterator, List, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.rag as rag_api
from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db
from app.db.database import get_db
from app.main import app
from app.services.rag_retriever import Citation


async def _no_db():
    yield None


@pytest.fixture
def client():
    org_id = uuid4()
    app.dependency_overrides[get_db] = _no_db
    app.dependency_overrides[get_tenant_db] = _no_db
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        id=uuid4(), organization_id=org_id, role="operator", is_active=True,
    )
    try:
        yield TestClient(app, raise_server_exceptions=False), org_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_tenant_db, None)
        app.dependency_overrides.pop(get_current_active_user, None)


async def _tokens(chunks: List[str]) -> AsyncIterator[str]:
    for chunk in chunks:
        yield chunk


class _FakeRetriever:
    """Stands in for Retriever.stream() so no live RAG services are needed."""

    def __init__(self, citations, used_context, generated, tokens):
        self._result = (citations, used_context, generated, tokens)
        self.seen_org_id: Optional[str] = None

    async def stream(self, query, *, org_id, top_n=None, generate=True):
        self.seen_org_id = org_id
        return self._result


def _events(body: str) -> List[str]:
    return [e for e in body.split("\n\n") if e.strip()]


def test_query_stream_emits_citations_then_deltas_then_done(client, monkeypatch):
    http_client, org_id = client
    citation = Citation(n=1, doc_id="doc-1", filename="a.txt", score=0.9, snippet="hi")
    fake = _FakeRetriever([citation], True, True, _tokens(["Hel", "lo"]))
    monkeypatch.setattr(rag_api, "get_retriever", lambda: fake)

    resp = http_client.post("/api/v1/rag/query/stream", json={"query": "what is x?"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _events(resp.text)
    kinds = [e.split("\n", 1)[0] for e in events]
    assert kinds == ["event: citations", "event: delta", "event: delta", "event: done"]
    assert "doc-1" in events[0]
    # Retrieval was scoped to the org resolved from the caller's JWT, not a
    # caller-suppliable value - the FS-669 property this route must not undo.
    assert fake.seen_org_id == str(org_id)


def test_query_stream_no_context_skips_straight_to_done(client, monkeypatch):
    http_client, _ = client
    fake = _FakeRetriever([], False, False, None)
    monkeypatch.setattr(rag_api, "get_retriever", lambda: fake)

    resp = http_client.post("/api/v1/rag/query/stream", json={"query": "anything"})

    assert resp.status_code == 200
    events = _events(resp.text)
    kinds = [e.split("\n", 1)[0] for e in events]
    assert kinds == ["event: citations", "event: done"]
