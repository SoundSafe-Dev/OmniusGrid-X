"""
Tenant isolation + multi-document co-tenancy, exercised with the real corpus.

The two corpus documents drive two complementary scenarios:

  * SAME org  — both documents indexed under ONE org. The org must see BOTH, and
    each document-anchored query must be answered from the right document; and
    deleting one must not remove the other. Needs no second org, so it ALWAYS
    runs. (This is the co-tenant coexistence property.)

  * CROSS org — document A under org A, document B under org B. Each org must
    retrieve ONLY its own document and must not be able to delete the other's.
    This is the security guarantee. It needs a genuine second org identity, which
    this stack cannot self-provision (organization_id is FK-enforced and there is
    no create-org endpoint), so it SKIPS LOUDLY unless a second org is supplied —
    seed one and pass RAG_TEST_ORG_B_TOKEN or RAG_TEST_ORG_B_EMAIL/PASSWORD.

Both documents are queried with strongly doc-anchored questions ("What does CIP
mean?" lives only in SOP-QA-014; "What does TOR mean?" only in SOP-WH-021), so a
citation from the wrong document is an unambiguous leak.
"""

import pytest

from corpus import DOCS, doc_id_for_citation

pytestmark = pytest.mark.isolation

FMT = "md"
DOC_A, DOC_B = DOCS[0], DOCS[1]

# A question answerable ONLY from each document (used to detect both presence and
# cross-tenant leakage).
ANCHOR = {
    DOC_A.id: "What does CIP mean?",
    DOC_B.id: "What does TOR mean?",
}


def _cites_doc(resp, doc) -> bool:
    """True if any citation in the response comes from ``doc``."""
    return any(doc_id_for_citation(c) == doc.id for c in resp.get("citations", []))


def test_same_org_sees_both_documents(rag_client, run_id, record):
    """One org, both documents: both are retrievable and each anchored query is
    answered from the correct document; deleting one leaves the other intact."""
    a_id = f"iso-same-a-{run_id}"
    b_id = f"iso-same-b-{run_id}"
    rag_client.wipe_all()
    try:
        rag_client.ingest(DOC_A.path(FMT), DOC_A.ctype(FMT), a_id)
        rag_client.ingest(DOC_B.path(FMT), DOC_B.ctype(FMT), b_id)

        a_ok = _cites_doc(rag_client.query(ANCHOR[DOC_A.id], generate=False, top_n=5), DOC_A)
        b_ok = _cites_doc(rag_client.query(ANCHOR[DOC_B.id], generate=False, top_n=5), DOC_B)
        record("isolation", "same_org_both_docs", a_ok and b_ok,
               note=f"A_visible={a_ok} B_visible={b_ok}")
        assert a_ok, "same-org: doc A not retrievable alongside doc B"
        assert b_ok, "same-org: doc B not retrievable alongside doc A"

        # Deleting A must not take B down with it.
        rag_client.delete_doc(a_id)
        b_after = _cites_doc(rag_client.query(ANCHOR[DOC_B.id], generate=False, top_n=5), DOC_B)
        a_gone = not _cites_doc(rag_client.query(ANCHOR[DOC_A.id], generate=False, top_n=5), DOC_A)
        record("isolation", "same_org_scoped_delete", b_after and a_gone,
               note=f"B_survives={b_after} A_purged={a_gone}")
        assert b_after, "same-org: deleting doc A also removed doc B (over-broad delete)"
        assert a_gone, "same-org: doc A still retrievable after delete"
    finally:
        rag_client.wipe_all()


def test_cross_org_document_isolation(rag_client, second_org_client, run_id, record):
    """Two orgs, one document each: neither org may retrieve or delete the other's
    document. The security-critical property for a multi-tenant compliance product;
    skips loudly (not a silent pass) when no second org is available."""
    org_a, org_b = rag_client, second_org_client
    a_id = f"iso-x-a-{run_id}"
    b_id = f"iso-x-b-{run_id}"
    org_a.wipe_all()
    try:
        org_b.wipe_all()
    except Exception:
        pass
    try:
        org_a.ingest(DOC_A.path(FMT), DOC_A.ctype(FMT), a_id)
        org_b.ingest(DOC_B.path(FMT), DOC_B.ctype(FMT), b_id)

        # Each org sees its OWN document (setup sanity).
        assert _cites_doc(org_a.query(ANCHOR[DOC_A.id], generate=False, top_n=5), DOC_A), \
            "org A cannot see its own document (setup failed)"
        assert _cites_doc(org_b.query(ANCHOR[DOC_B.id], generate=False, top_n=5), DOC_B), \
            "org B cannot see its own document (setup failed)"

        # Neither org sees the OTHER's document.
        leak_into_a = _cites_doc(org_a.query(ANCHOR[DOC_B.id], generate=False, top_n=5), DOC_B)
        leak_into_b = _cites_doc(org_b.query(ANCHOR[DOC_A.id], generate=False, top_n=5), DOC_A)
        record("isolation", "cross_org_no_read", not (leak_into_a or leak_into_b),
               note=f"B_leaked_to_A={leak_into_a} A_leaked_to_B={leak_into_b}")
        assert not leak_into_a, "TENANT LEAK: org A retrieved org B's document"
        assert not leak_into_b, "TENANT LEAK: org B retrieved org A's document"

        # Org B must not be able to delete org A's document.
        try:
            org_b.delete_doc(a_id)
        except Exception:
            pass  # a rejection is fine
        survived = _cites_doc(org_a.query(ANCHOR[DOC_A.id], generate=False, top_n=5), DOC_A)
        record("isolation", "cross_org_no_delete", survived,
               note="org A doc survived org B delete attempt")
        assert survived, "TENANT LEAK: org B deleted org A's document"
    finally:
        org_a.wipe_all()
        try:
            org_b.wipe_all()
        except Exception:
            pass
