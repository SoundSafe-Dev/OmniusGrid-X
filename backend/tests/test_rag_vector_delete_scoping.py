"""Vector deletion must be scoped to one tenant (FS-669).

``doc_id`` is caller-suppliable at ingest, so two orgs can legitimately hold the
same one. A Qdrant delete filtered on ``doc_id`` alone therefore matches both
copies: one tenant's delete — or, worse, their routine re-ingest — silently
destroys another tenant's vectors while leaving that tenant's ``rag_documents``
row still reading ``indexed``. Nothing raises on either side, so only a test
that inspects the outgoing filter can catch a regression here.

These assert on the filter handed to the client rather than on a live Qdrant,
so they stay fast and run anywhere.
"""

from __future__ import annotations

import pytest

pytest.importorskip("qdrant_client")

from app.services.vector_store import VectorStore  # noqa: E402


class _RecordingClient:
    """Captures the ``points_selector`` of each delete instead of performing it."""

    def __init__(self) -> None:
        self.selectors = []

    async def delete(self, *, collection_name, points_selector):
        self.selectors.append(points_selector)


def _store() -> VectorStore:
    """A VectorStore wired to a recording client, bypassing __init__/settings."""
    store = VectorStore.__new__(VectorStore)
    store.collection = "test_collection"
    store.url = "http://stub"
    store.api_key = None
    store._client = _RecordingClient()
    return store


def _must_conditions(selector) -> dict:
    return {c.key: c.match.value for c in selector.filter.must}


async def test_delete_by_doc_filters_on_both_doc_and_org():
    store = _store()

    await store.delete_by_doc("shared-doc-id", "org-a")

    assert _must_conditions(store._client.selectors[0]) == {
        "doc_id": "shared-doc-id",
        "org_id": "org-a",
    }


async def test_generation_swap_delete_filters_on_both_doc_and_org():
    """The re-ingest path matters most: it runs far more often than delete."""
    store = _store()

    await store.delete_by_doc_excluding_generation("shared-doc-id", "org-a", "gen2")

    selector = store._client.selectors[0]
    assert _must_conditions(selector) == {
        "doc_id": "shared-doc-id",
        "org_id": "org-a",
    }
    # The generation exclusion must survive alongside the org scope, or the swap
    # would delete the generation it just wrote.
    assert [c.match.value for c in selector.filter.must_not] == ["gen2"]


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.delete_by_doc("doc"),
        lambda s: s.delete_by_doc_excluding_generation("doc", "gen"),
    ],
)
def test_org_id_cannot_be_omitted(call):
    """org_id is required, not defaulted.

    A default would let a future call site drop tenant scoping and still pass
    type checking and review — the exact shape of the original bug.
    """
    with pytest.raises(TypeError):
        call(_store())
