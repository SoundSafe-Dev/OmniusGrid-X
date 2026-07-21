"""Tenant isolation: org B must never retrieve or delete org A's documents.

Requires a second org (see the ``second_org_client`` fixture); skips cleanly if
the environment can't provision one. This is the security-critical property for a
multi-tenant compliance product, so a skip is loud, not a silent pass."""

import pytest

from client import FORMATS, DOCS_DIR, ApiError

pytestmark = pytest.mark.isolation


def test_org_cannot_read_or_delete_others_docs(rag_client, second_org_client, run_id, record):
    fmt = "txt"
    filename, ctype = FORMATS[fmt]
    doc_id = f"pytest-iso-{run_id}"
    probe = "acid rinse contact time"
    org_a, org_b = rag_client, second_org_client

    org_a.wipe_all()
    try:
        org_a.ingest(DOCS_DIR / filename, ctype, doc_id)

        # Org A sees its own content.
        a_view = org_a.query(probe, generate=False)
        assert a_view.get("citations"), "org A cannot see its own doc (setup failed)"

        # Org B must NOT retrieve org A's content.
        b_view = org_b.query(probe, generate=False)
        leaked = bool(b_view.get("citations"))
        record("isolation", "no_cross_read", not leaked,
               note=f"org_b citations={len(b_view.get('citations', []))}")
        assert not leaked, "TENANT LEAK: org B retrieved org A's document content"

        # Org B must NOT be able to delete org A's doc.
        try:
            org_b.delete_doc(doc_id)
        except ApiError:
            pass  # a rejection is fine
        still_there = bool(org_a.query(probe, generate=False).get("citations"))
        record("isolation", "no_cross_delete", still_there,
               note="org A doc survived org B delete attempt")
        assert still_there, "TENANT LEAK: org B deleted org A's document"
    finally:
        org_a.wipe_all()
