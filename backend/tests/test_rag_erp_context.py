"""The operational (ERP) leg of the RAG pipeline, and the seams it must not cross.

The Compliance Assistant answers policy questions from the document corpus and is
additionally given a block of the organization's own ERP records so the answer can
be specific to current conditions. That block is prompt-side only: it informs the
generation and appears nowhere in the response.

Three properties hold this together, and each is easy to lose in a later edit:

  1. **The block is scoped to the caller's organization.** It is read from Postgres
     rather than Qdrant, so the org filter is a separate piece of code from the one
     the document leg uses, and a separate place to forget it.
  2. **The block never reaches the client.** Not as text, not as a citation, not as
     an entry in `sources`. A future contributor adding "just a debug field" to
     `RagAnswer` breaks the feature's contract, and nothing else would catch it.
  3. **A broken operational leg does not break the answer.** It is an enrichment.
     An ERP outage must degrade the answer's specificity, not its availability.

The existing RAG tests all live under `tests/rag_eval/` and need the full docker
stack. These are hermetic: no Qdrant, no SeaweedFS, no LLM, no database.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.services.rag_erp_context import (
    _query_tokens,
    _render_row,
    _routed_entity_types,
    build_erp_context,
)
from app.services.rag_retriever import (
    Citation,
    RagAnswer,
    Retriever,
    SourceDoc,
    _FORM_PATTERN,
)


# --------------------------------------------------------------------------- #
# Fakes. The DB session is stubbed to the one call build_erp_context makes, so
# these tests exercise the selection logic without a database.
# --------------------------------------------------------------------------- #


def erp_row(
    entity_type: str = "WorkOrder",
    entity_id: str = "WO-1",
    source_system: str = "sap",
    **data: Any,
):
    """One ERPEntity as `flatten_erp_entity` sees it (attribute access only)."""
    return SimpleNamespace(
        entity_type=entity_type,
        entity_id=entity_id,
        source_system=source_system,
        entity_data=data,
    )


class FakeSession:
    """Returns a fixed row set for the single select build_erp_context issues."""

    def __init__(self, rows: List[Any]):
        self._rows = rows
        self.executed = 0

    async def execute(self, _stmt):
        self.executed += 1
        scalars = SimpleNamespace(all=lambda: self._rows)
        return SimpleNamespace(scalars=lambda: scalars)


def search_result(
    doc_id: str,
    filename: str,
    text: str = "some passage text",
    heading: Optional[str] = None,
    page: Optional[int] = 1,
):
    payload: Dict[str, Any] = {
        "doc_id": doc_id,
        "filename": filename,
        "s3_key": f"org-a/{doc_id}/{filename}",
        "text": text,
    }
    if heading:
        payload["heading"] = heading
    if page is not None:
        payload["page"] = page
    return SimpleNamespace(id=doc_id, score=0.5, payload=payload)


def build_retriever(candidates: List[Any], *, llm_answer: str = "Answer [1]."):
    """A Retriever with all three network dependencies replaced."""
    with patch("app.services.rag_retriever.get_rag_inference"), patch(
        "app.services.rag_retriever.get_vector_store"
    ), patch("app.services.rag_retriever.get_llm_client"):
        r = Retriever()

    r.inference = SimpleNamespace(
        available=True,
        embed_query=AsyncMock(
            return_value=SimpleNamespace(
                dense=[0.1], sparse=SimpleNamespace(indices=[1], values=[1.0])
            )
        ),
        # Rerank in candidate order; scores descend so ordering is checkable.
        rerank_top_n=AsyncMock(
            return_value=[
                (i, 0.9 - i * 0.1)
                for i in range(min(len(candidates), settings.RAG_RERANK_TOP_N))
            ]
        ),
    )
    r.vectors = SimpleNamespace(
        available=True, hybrid_search=AsyncMock(return_value=candidates)
    )
    r.llm = SimpleNamespace(available=True, generate=AsyncMock(return_value=llm_answer))
    return r


# --------------------------------------------------------------------------- #
# 1. Tenancy
# --------------------------------------------------------------------------- #


class TestTenancy:
    @pytest.mark.asyncio
    async def test_the_query_is_filtered_on_the_callers_organization(self):
        """The org filter is compiled into the statement, not applied afterwards.

        Asserting on the rendered SQL rather than on the returned rows because a
        fake session returns whatever it is given: a `build_erp_context` that
        dropped its `where` clause entirely would still "pass" a rows-based test.
        """
        session = FakeSession([erp_row()])
        captured: Dict[str, Any] = {}

        async def capture(stmt):
            captured["sql"] = str(stmt)
            scalars = SimpleNamespace(all=lambda: session._rows)
            return SimpleNamespace(scalars=lambda: scalars)

        session.execute = capture
        await build_erp_context(session, "org-a", "lockout procedure")

        sql = captured["sql"].lower()
        assert "organization_id" in sql
        assert "is_active" in sql

    @pytest.mark.asyncio
    async def test_no_rows_yields_an_empty_block_not_an_error(self):
        """Most deployments have no ERP integration at all. That is not a failure."""
        block, meta = await build_erp_context(FakeSession([]), "org-a", "anything")
        assert block == ""
        assert meta["rows"] == 0
        assert meta["entity_types"] == []


# --------------------------------------------------------------------------- #
# 2. Selection
# --------------------------------------------------------------------------- #


class TestRouting:
    @pytest.mark.parametrize(
        "query,expected",
        [
            ("What does our lockout tagout procedure require?", "WorkOrder"),
            ("Are the PM work orders overdue?", "WorkOrder"),
            ("Which millwrights have expired certifications?", "Employee"),
            ("How much overtime does the union agreement allow?", "Employee"),
            ("Do we have signed contracts with that supplier?", "PurchaseOrder"),
            ("What are the cold chain requirements for this shipment?", "Shipment"),
            ("Which materials are below the minimum stock level?", "Inventory"),
        ],
    )
    def test_a_question_routes_to_the_entity_type_it_is_about(self, query, expected):
        routed = _routed_entity_types(query)
        assert routed is not None and expected in routed

    def test_an_unroutable_question_expresses_no_opinion(self):
        """None, not an empty set — the difference decides whether an unrouted
        question sees the most recent records or none at all, and 'none at all'
        would silently disable the leg for every question the keywords miss."""
        assert _routed_entity_types("What colour is the building?") is None

    def test_stopwords_do_not_become_relevance_signal(self):
        tokens = _query_tokens("What does the policy require for our workers?")
        assert "workers" in tokens
        for noise in ("does", "the", "policy", "require", "for", "our", "what"):
            assert noise not in tokens


class TestSelection:
    @pytest.mark.asyncio
    async def test_routed_rows_outrank_unrouted_ones(self):
        rows = [
            erp_row("Invoice", "INV-1", amount=100),
            erp_row("Invoice", "INV-2", amount=200),
            erp_row("WorkOrder", "WO-9", description="lockout on press line"),
        ]
        block, meta = await build_erp_context(
            FakeSession(rows), "org-a", "lockout tagout on the press"
        )
        assert block.splitlines()[0].startswith("WorkOrder | WO-9")
        assert meta["entity_types"][0] == "WorkOrder"

    @pytest.mark.asyncio
    async def test_nothing_is_excluded_outright(self):
        """Rank, don't filter. Recency carries real signal, so an over-eager
        relevance filter would empty the block on any question its keywords miss."""
        rows = [erp_row("Invoice", f"INV-{i}") for i in range(3)]
        block, meta = await build_erp_context(FakeSession(rows), "org-a", "zzzz nothing")
        assert meta["rows"] == 3
        assert "INV-0" in block

    @pytest.mark.asyncio
    async def test_the_row_cap_holds(self):
        rows = [erp_row("WorkOrder", f"WO-{i}") for i in range(200)]
        _, meta = await build_erp_context(
            FakeSession(rows), "org-a", "work order", max_rows=5
        )
        assert meta["rows"] == 5

    @pytest.mark.asyncio
    async def test_the_char_cap_holds_and_never_truncates_a_row(self):
        rows = [erp_row("WorkOrder", f"WO-{i}", note="x" * 300) for i in range(50)]
        block, meta = await build_erp_context(
            FakeSession(rows), "org-a", "work order", max_chars=1000
        )
        assert meta["chars"] <= 1000
        # A half-written record is worse than a missing one: the generator cannot
        # tell a truncated value from a real one.
        for line in block.splitlines():
            assert line.count("note: ") == 0 or "x" * 300 in line

    def test_a_rendered_row_is_self_describing(self):
        line = _render_row(
            {
                "entity_type": "WorkOrder",
                "entity_id": "WO-77105",
                "status": "open",
                "priority": "high",
            }
        )
        assert line.startswith("WorkOrder | WO-77105")
        assert "status: open" in line and "priority: high" in line

    def test_empty_and_noise_fields_are_dropped(self):
        line = _render_row(
            {
                "entity_type": "WorkOrder",
                "entity_id": "WO-1",
                "etag": "W/abc",
                "blank": "",
                "missing": None,
                "status": "open",
            }
        )
        assert "etag" not in line and "blank" not in line and "missing" not in line
        assert "status: open" in line


# --------------------------------------------------------------------------- #
# 3. The concealment contract
# --------------------------------------------------------------------------- #


class TestOperationalContextStaysOutOfTheResponse:
    """The feature's defining property, asserted rather than assumed."""

    @pytest.mark.asyncio
    async def test_erp_text_reaches_the_prompt(self):
        r = build_retriever([search_result("d1", "lockout-sop.pdf")])
        await r.retrieve(
            "lockout procedure",
            org_id="org-a",
            erp_context="WorkOrder | WO-77105 | status: open",
            erp_meta={"rows": 1, "entity_types": ["WorkOrder"], "chars": 40},
        )
        prompt = r.llm.generate.await_args.kwargs["prompt"]
        system = r.llm.generate.await_args.kwargs["system"]
        assert "WO-77105" in prompt
        assert "Operational records:" in prompt
        # Without this clause the model numbers operational lines as [6] and the
        # client renders a citation marker with no citation behind it.
        assert "never attach a bracketed number" in system.lower()

    @pytest.mark.asyncio
    async def test_erp_text_does_not_reach_the_response(self):
        r = build_retriever([search_result("d1", "lockout-sop.pdf")])
        answer = await r.retrieve(
            "lockout procedure",
            org_id="org-a",
            erp_context="WorkOrder | WO-77105 | status: open",
            erp_meta={"rows": 1, "entity_types": ["WorkOrder"], "chars": 40},
        )
        serialized = answer.model_dump_json()
        assert "WO-77105" not in serialized
        assert "Operational records" not in serialized
        assert all("WO-77105" not in (c.snippet or "") for c in answer.citations)
        assert all(s.doc_id != "WO-77105" for s in answer.sources)

    def test_the_response_model_carries_no_operational_field(self):
        """A later 'just for debugging' field on RagAnswer would quietly publish
        the operational block. The field list is the contract; pin it."""
        assert set(RagAnswer.model_fields) == {
            "answer",
            "citations",
            "used_context",
            "generated",
            "sources",
        }

    @pytest.mark.asyncio
    async def test_the_prompt_is_unchanged_when_there_is_no_erp_context(self):
        r = build_retriever([search_result("d1", "lockout-sop.pdf")])
        await r.retrieve("lockout procedure", org_id="org-a")
        assert "Operational records" not in r.llm.generate.await_args.kwargs["prompt"]
        assert r.llm.generate.await_args.kwargs["system"].endswith("outside knowledge.")

    @pytest.mark.asyncio
    async def test_operational_records_alone_never_produce_an_answer(self):
        """No document matched. A compliance assistant answering from work-order
        rows with no policy behind them is worse than one that declines."""
        r = build_retriever([])
        answer = await r.retrieve(
            "lockout procedure",
            org_id="org-a",
            erp_context="WorkOrder | WO-77105 | status: open",
            erp_meta={"rows": 1, "entity_types": ["WorkOrder"], "chars": 40},
        )
        assert answer.used_context is False
        assert answer.generated is False
        assert answer.citations == [] and answer.sources == []
        r.llm.generate.assert_not_awaited()


class TestTheAuditTrail:
    @pytest.mark.asyncio
    async def test_the_erp_contribution_is_logged(self):
        """The log line is the ONLY record that operational data shaped the answer,
        since the response carries none of it. Losing these fields loses the
        ability to explain an answer that is later challenged."""
        r = build_retriever([search_result("d1", "lockout-sop.pdf")])
        with patch("app.services.rag_retriever.logger") as log:
            await r.retrieve(
                "lockout procedure",
                org_id="org-a",
                erp_context="WorkOrder | WO-77105 | status: open",
                erp_meta={"rows": 3, "entity_types": ["WorkOrder"], "chars": 120},
            )
        kwargs = log.info.call_args.kwargs
        assert kwargs["erp_rows"] == 3
        assert kwargs["erp_entity_types"] == ["WorkOrder"]
        assert kwargs["erp_chars"] == 120


# --------------------------------------------------------------------------- #
# 4. The source roll-up (documents and forms)
# --------------------------------------------------------------------------- #


class TestSourceRollup:
    @pytest.mark.asyncio
    async def test_several_passages_of_one_document_collapse_to_one_source(self):
        candidates = [
            search_result("d1", "lockout-sop.pdf", page=1),
            search_result("d1", "lockout-sop.pdf", page=4),
            search_result("d1", "lockout-sop.pdf", page=9),
        ]
        answer = await build_retriever(candidates).retrieve("loto", org_id="org-a")
        assert len(answer.citations) == 3
        assert len(answer.sources) == 1
        assert answer.sources[0].cited is True

    @pytest.mark.asyncio
    async def test_a_candidate_that_lost_the_rerank_still_appears_as_a_source(self):
        """The whole reason the roll-up reads the full candidate set: a form that
        matched the question but placed sixth is exactly what the reader needs."""
        candidates = [search_result(f"d{i}", f"doc{i}.pdf") for i in range(8)]
        answer = await build_retriever(candidates).retrieve("loto", org_id="org-a")
        assert len(answer.citations) == settings.RAG_RERANK_TOP_N
        assert len(answer.sources) == 8
        uncited = [s for s in answer.sources if not s.cited]
        assert uncited, "candidates beyond the rerank cut must still be listed"

    @pytest.mark.asyncio
    async def test_an_uncited_source_carries_no_score(self):
        """Cited documents carry a cross-encoder score; the rest carry an RRF
        fusion score. Reporting both as one number renders in a UI as a ranking
        that does not exist — so uncited documents report nothing."""
        candidates = [search_result(f"d{i}", f"doc{i}.pdf") for i in range(8)]
        answer = await build_retriever(candidates).retrieve("loto", org_id="org-a")
        for source in answer.sources:
            if source.cited:
                assert source.score is not None
            else:
                assert source.score is None

    @pytest.mark.asyncio
    async def test_cited_sources_are_ordered_first(self):
        candidates = [search_result(f"d{i}", f"doc{i}.pdf") for i in range(8)]
        answer = await build_retriever(candidates).retrieve("loto", org_id="org-a")
        cited_flags = [s.cited for s in answer.sources]
        assert cited_flags == sorted(cited_flags, reverse=True)

    @pytest.mark.parametrize(
        "filename",
        [
            "fmla-request-form.pdf",
            "PPE Request Form.docx",
            "hazard_checklist.pdf",
            "hot-work-permit.pdf",
            "F-102.pdf",
            "leave-application.docx",
        ],
    )
    def test_a_form_is_recognised(self, filename):
        assert _FORM_PATTERN.search(filename)

    @pytest.mark.parametrize(
        "filename",
        [
            "safety-informational.pdf",
            "local-49-cba.docx",
            "osha-1910-147.pdf",
            "cold-chain-sop.md",
            "performance.csv",
        ],
    )
    def test_a_policy_document_is_not_mistaken_for_a_form(self, filename):
        """'performance' contains 'form'. A substring match would flag it, and the
        reader would be told to fill in a policy document."""
        assert not _FORM_PATTERN.search(filename)

    @pytest.mark.asyncio
    async def test_forms_are_flagged_on_the_source(self):
        candidates = [
            search_result("d1", "leave-policy.pdf"),
            search_result("d2", "fmla-request-form.pdf"),
        ]
        answer = await build_retriever(candidates).retrieve("fmla", org_id="org-a")
        by_name = {s.filename: s for s in answer.sources}
        assert by_name["fmla-request-form.pdf"].is_form is True
        assert by_name["leave-policy.pdf"].is_form is False


# --------------------------------------------------------------------------- #
# 5. Degradation
# --------------------------------------------------------------------------- #


class TestDegradation:
    @pytest.mark.asyncio
    async def test_a_failing_erp_leg_leaves_the_document_answer_intact(self):
        """Enrichment, not dependency. An ERP outage must cost the answer its
        specificity, never its availability."""
        from app.api import rag as rag_api

        r = build_retriever([search_result("d1", "lockout-sop.pdf")])
        user = SimpleNamespace(organization_id="org-a", id="u1")

        with patch.object(
            rag_api, "build_erp_context", AsyncMock(side_effect=RuntimeError("db down"))
        ), patch.object(rag_api, "get_retriever", return_value=r):
            answer = await rag_api.query(
                rag_api.QueryRequest(query="lockout procedure"),
                current_user=user,
                db=FakeSession([]),
            )

        assert answer.generated is True
        assert answer.citations
        assert r.llm.generate.await_args.kwargs["prompt"].count("Operational records") == 0

    @pytest.mark.asyncio
    async def test_the_leg_can_be_switched_off(self):
        from app.api import rag as rag_api

        r = build_retriever([search_result("d1", "lockout-sop.pdf")])
        user = SimpleNamespace(organization_id="org-a", id="u1")
        build = AsyncMock(return_value=("WorkOrder | WO-1", {"rows": 1}))

        with patch.object(settings, "RAG_ERP_CONTEXT_ENABLED", False), patch.object(
            rag_api, "build_erp_context", build
        ), patch.object(rag_api, "get_retriever", return_value=r):
            await rag_api.query(
                rag_api.QueryRequest(query="lockout procedure"),
                current_user=user,
                db=FakeSession([]),
            )

        build.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generation_unavailable_still_returns_sources(self):
        """A retrieval-only deployment must still hand back the documents and
        forms — that is most of what the page is for."""
        r = build_retriever([search_result("d1", "fmla-request-form.pdf")])
        r.llm = SimpleNamespace(available=False, generate=AsyncMock())
        answer = await r.retrieve("fmla", org_id="org-a")
        assert answer.answer is None and answer.generated is False
        assert answer.citations and answer.sources
        assert answer.sources[0].is_form is True


# --------------------------------------------------------------------------- #
# 6. The document link endpoint
# --------------------------------------------------------------------------- #


class TestDocumentLink:
    @pytest.mark.asyncio
    async def test_a_key_from_another_organization_is_rejected(self):
        """The key arrives from the client. Keys are `{org_id}/{doc_id}/{name}`, so
        without the prefix check any authenticated user presigns any tenant's
        document by editing one UUID — and gets a URL that keeps working for an
        hour after the check would have failed."""
        from fastapi import HTTPException
        from app.api import rag as rag_api

        user = SimpleNamespace(organization_id="org-a", id="u1")
        with pytest.raises(HTTPException) as exc:
            await rag_api.document_link(
                rag_api.DocumentLinkRequest(s3_key="org-b/doc-1/secret.pdf"),
                current_user=user,
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_a_traversing_key_is_rejected_rather_than_normalised(self):
        from fastapi import HTTPException
        from app.api import rag as rag_api

        user = SimpleNamespace(organization_id="org-a", id="u1")
        with pytest.raises(HTTPException) as exc:
            await rag_api.document_link(
                rag_api.DocumentLinkRequest(s3_key="org-a/../org-b/doc-1/secret.pdf"),
                current_user=user,
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_an_own_key_is_presigned(self):
        from app.api import rag as rag_api

        user = SimpleNamespace(organization_id="org-a", id="u1")
        store = SimpleNamespace(
            available=True,
            generate_presigned_url=AsyncMock(return_value="https://s3/signed"),
        )
        with patch.object(rag_api, "get_document_store", return_value=store):
            result = await rag_api.document_link(
                rag_api.DocumentLinkRequest(s3_key="org-a/doc-1/lockout-sop.pdf"),
                current_user=user,
            )
        assert result.url == "https://s3/signed"
        assert result.expires_in == settings.S3_PRESIGN_EXPIRE_SECONDS

    @pytest.mark.asyncio
    async def test_an_unavailable_store_is_a_503_not_a_500(self):
        from fastapi import HTTPException
        from app.api import rag as rag_api

        user = SimpleNamespace(organization_id="org-a", id="u1")
        store = SimpleNamespace(available=False, generate_presigned_url=AsyncMock())
        with patch.object(rag_api, "get_document_store", return_value=store):
            with pytest.raises(HTTPException) as exc:
                await rag_api.document_link(
                    rag_api.DocumentLinkRequest(s3_key="org-a/doc-1/x.pdf"),
                    current_user=user,
                )
        assert exc.value.status_code == 503
