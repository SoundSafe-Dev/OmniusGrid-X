"""
RAG Retrieval Orchestrator

The query half of the pipeline - mirrors ``rag_ingestion`` on the read side:

    query -> embed (dense + sparse)         # rag-inference
          -> hybrid_search (RRF, org-scoped) # Qdrant
          -> rerank_top_n                     # rag-inference cross-encoder
          -> assemble context (+ citations)
          -> generate answer                  # swappable LLM (grounded prompt)

Design:
- **Two-stage retrieval.** Hybrid search casts a wide net (RAG_RETRIEVE_LIMIT
  fused candidates); the cross-encoder reranker then precisely orders them and
  we keep the top-N. This is the accuracy win of a reranker over raw ANN.
- **Tenant isolation.** ``org_id`` is pushed into the Qdrant filter so a query
  can only ever see its own organization's chunks.
- **Grounded generation.** The LLM is instructed to answer only from the
  provided, numbered context and to cite sources; it is told to say when the
  answer is not present, to curb hallucination.
- **Graceful degradation.** No candidates -> a short no-answer without spending
  an LLM call. LLM unavailable (or ``generate=False``) -> return the ranked
  citations only, so a retrieval-only deployment still answers with sources.
  Inference/vector store unavailable -> ``RuntimeError`` (router maps to 503).
"""

from typing import List, Dict, Any, Optional, Tuple
from functools import lru_cache
import re

import structlog
from pydantic import BaseModel

from app.core.config import settings
from app.services.inference_client import get_rag_inference
from app.services.vector_store import get_vector_store, SearchResult
from app.services.llm_client import get_llm_client

logger = structlog.get_logger()

_SYSTEM_PROMPT = (
    "You are a compliance and operations assistant. Answer the user's question "
    "using ONLY the numbered context passages provided. Cite the passages you "
    "use with bracketed numbers like [1], [2]. If the context does not contain "
    "the answer, say so plainly - do not invent facts or cite outside knowledge."
)

# Appended only when an operational block is present. The second sentence is
# load-bearing: without it the model numbers the operational lines as [6], [7]
# and the client renders citation markers with no citation behind them.
_OPERATIONAL_PROMPT = (
    " You may also be given a section of operational records from the "
    "organization's own systems. Use them to make the answer specific and "
    "current, but ONLY the numbered context passages may be cited - never "
    "attach a bracketed number to an operational record, and never refer to "
    "the operational records section itself."
)

_NO_CONTEXT_ANSWER = (
    "I couldn't find any relevant documents to answer that question."
)

# A document a reader would have to fill in and return, as opposed to one they
# read. A filename heuristic, and a stopgap: there is no document metadata store
# to hold a real doc_type, so this is the only signal available at query time.
# Kept as one named constant so replacing it later is a one-line change.
_FORM_PATTERN = re.compile(
    r"(?:^|[-_ /])(?:form|forms|request|application|checklist|permit|waiver|"
    r"authorization|consent|f-?\d+)(?:[-_ .]|$)",
    re.I,
)


class Citation(BaseModel):
    """A retrieved passage backing an answer, numbered to match the prompt."""

    n: int  # 1-based index used in the prompt and the answer's [n] markers
    doc_id: Optional[str] = None
    filename: Optional[str] = None
    s3_key: Optional[str] = None  # lets the caller pull/presign the original
    source: Dict[str, Any] = {}  # page / section / heading, from chunk meta
    score: float = 0.0  # reranker relevance score
    snippet: str = ""


class SourceDoc(BaseModel):
    """A whole document behind an answer, as opposed to one passage of it.

    Citations are chunks: three of them can be three pages of one PDF, and a form
    that matched the question but lost the top-N rerank slots never appears at all.
    A reader asking "what do I have to file for this" needs the document list, so
    the candidate set is rolled up per document alongside the passage citations.
    """

    doc_id: Optional[str] = None
    filename: Optional[str] = None
    s3_key: Optional[str] = None  # presign this to open the original
    cited: bool = False  # did a passage of it reach the answer's context?
    # ONLY set when cited. Cited documents carry a cross-encoder score; the rest
    # carry an RRF fusion score, and the two are not on one scale. Reporting both
    # as one number would render in a UI as a ranking that does not exist.
    score: Optional[float] = None
    is_form: bool = False


class RagAnswer(BaseModel):
    answer: Optional[str]  # None when generation was skipped/unavailable
    citations: List[Citation]
    used_context: bool  # whether any passages were retrieved
    generated: bool  # whether the LLM actually produced the answer
    sources: List[SourceDoc] = []  # per-document roll-up of the candidate set


def _source_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the human-facing locator (page/section) out of a chunk payload."""
    keys = ("page", "section_id", "heading", "level", "source_type", "chunk_id")
    return {k: payload[k] for k in keys if payload.get(k) is not None}


def _source_label(payload: Dict[str, Any]) -> str:
    """Short '(filename, p.3)' style label for the context header."""
    name = payload.get("filename", "document")
    if payload.get("page") is not None:
        return f"{name}, p.{payload['page']}"
    if payload.get("heading"):
        return f"{name} — {payload['heading']}"
    if payload.get("section_id") is not None:
        return f"{name}, section {payload['section_id']}"
    return name


class Retriever:
    """Drives embed -> search -> rerank -> generate for one query."""

    def __init__(self) -> None:
        self.inference = get_rag_inference()
        self.vectors = get_vector_store()
        self.llm = get_llm_client()

    async def retrieve(
        self,
        query: str,
        *,
        org_id: str,
        top_n: Optional[int] = None,
        generate: bool = True,
        erp_context: Optional[str] = None,
        erp_meta: Optional[Dict[str, Any]] = None,
    ) -> RagAnswer:
        if not self.inference.available or not self.vectors.available:
            raise RuntimeError(
                "Retrieval unavailable: the inference or vector service is not "
                "configured/reachable."
            )
        top_n = top_n or settings.RAG_RERANK_TOP_N

        # 1. Embed the query (BGE-M3 asymmetric query encoding).
        embedding = await self.inference.embed_query(query)

        # 2. Hybrid (dense + sparse) search, scoped to the caller's org.
        candidates = await self.vectors.hybrid_search(
            dense=embedding.dense,
            sparse_indices=embedding.sparse.indices,
            sparse_values=embedding.sparse.values,
            limit=settings.RAG_RETRIEVE_LIMIT,
            org_id=org_id,
        )
        if not candidates:
            # No document matched. An operational block alone must NEVER produce an
            # answer: a compliance assistant that answers from work-order rows with
            # no policy behind them is worse than one that declines.
            return RagAnswer(
                answer=_NO_CONTEXT_ANSWER,
                citations=[],
                used_context=False,
                generated=False,
                sources=[],
            )

        # 3. Cross-encoder rerank; keep the strongest top_n passages.
        passages = [c.payload.get("text", "") for c in candidates]
        ranked = await self.inference.rerank_top_n(query, passages, top_n)
        top: List[Tuple[SearchResult, float]] = [
            (candidates[idx], score) for idx, score in ranked
        ]

        # 4. Assemble numbered context (capped) + citations, then roll the whole
        #    candidate set up per document so the caller gets the files and forms,
        #    not just the passages that fit the context budget.
        context, citations = self._build_context(top)
        sources = self._build_sources(candidates, citations)

        # 5. Generate a grounded answer (or return citations only).
        if not generate or not self.llm.available:
            return RagAnswer(
                answer=None,
                citations=citations,
                used_context=True,
                generated=False,
                sources=sources,
            )
        prompt = (
            f"Context:\n{context}\n\n"
            f"Question: {query}\n\n"
            "Answer using only the context above, citing sources as [n]."
        )
        system = _SYSTEM_PROMPT
        if erp_context:
            # Placed AFTER the numbered context and before the question, without
            # numbers of its own - the separation is what keeps [n] meaning
            # "document passage" and nothing else.
            prompt = (
                f"Context:\n{context}\n\n"
                f"Operational records:\n{erp_context}\n\n"
                f"Question: {query}\n\n"
                "Answer using only the context above, citing sources as [n]."
            )
            system = _SYSTEM_PROMPT + _OPERATIONAL_PROMPT
        answer = await self.llm.generate(prompt=prompt, system=system)
        # The ERP fields below are the ONLY record that operational data reached
        # the prompt - RagAnswer deliberately carries none of it. If an answer is
        # ever challenged, this log line is the audit trail.
        logger.info(
            "rag_retriever.answered",
            org_id=org_id,
            candidates=len(candidates),
            cited=len(citations),
            sources=len(sources),
            erp_rows=(erp_meta or {}).get("rows", 0),
            erp_entity_types=(erp_meta or {}).get("entity_types", []),
            erp_chars=(erp_meta or {}).get("chars", 0),
        )
        return RagAnswer(
            answer=answer,
            citations=citations,
            used_context=True,
            generated=True,
            sources=sources,
        )

    def _build_context(
        self, top: List[Tuple[SearchResult, float]]
    ) -> Tuple[str, List[Citation]]:
        """Number passages [1..N], concatenate up to the char cap, cite each."""
        blocks: List[str] = []
        citations: List[Citation] = []
        used = 0
        n = 0
        for result, score in top:
            payload = result.payload or {}
            text = payload.get("text", "").strip()
            if not text:
                continue
            if used + len(text) > settings.RAG_MAX_CONTEXT_CHARS and blocks:
                break  # context budget spent
            n += 1
            used += len(text)
            blocks.append(f"[{n}] ({_source_label(payload)})\n{text}")
            citations.append(
                Citation(
                    n=n,
                    doc_id=payload.get("doc_id"),
                    filename=payload.get("filename"),
                    s3_key=payload.get("s3_key"),
                    source=_source_meta(payload),
                    score=round(float(score), 4),
                    snippet=text[: settings.RAG_CITATION_SNIPPET_CHARS],
                )
            )
        return "\n\n".join(blocks), citations

    def _build_sources(
        self, candidates: List[SearchResult], citations: List[Citation]
    ) -> List[SourceDoc]:
        """Roll the candidate set up per document, cited ones first.

        Built from the FULL fused candidate set, not the reranked few: a form that
        matched the question but placed sixth is exactly what a reader asking
        "what do I file" needs, and it never appears in the citations.
        """
        cited_scores: Dict[str, float] = {}
        for c in citations:
            key = c.doc_id or c.s3_key or c.filename or ""
            # A document cited by several passages takes its best passage's score.
            if key and (key not in cited_scores or c.score > cited_scores[key]):
                cited_scores[key] = c.score

        by_doc: Dict[str, SourceDoc] = {}
        for result in candidates:
            payload = result.payload or {}
            key = payload.get("doc_id") or payload.get("s3_key") or payload.get("filename")
            if not key or key in by_doc:
                continue
            filename = payload.get("filename")
            heading = payload.get("heading") or ""
            by_doc[key] = SourceDoc(
                doc_id=payload.get("doc_id"),
                filename=filename,
                s3_key=payload.get("s3_key"),
                cited=key in cited_scores,
                score=cited_scores.get(key),
                is_form=bool(_FORM_PATTERN.search(f"{filename or ''} {heading}")),
            )
        # Cited first, then by filename so the "also relevant" group has a stable
        # order rather than Qdrant's fusion order, which means nothing to a reader.
        return sorted(
            by_doc.values(),
            key=lambda s: (not s.cited, -(s.score or 0.0), s.filename or ""),
        )

    async def health_check(self) -> Dict[str, Any]:
        return {
            "inference": await self.inference.health_check(),
            "vector_store": await self.vectors.health_check(),
            "llm": await self.llm.health_check(),
        }


@lru_cache()
def get_retriever() -> Retriever:
    """Cached singleton accessor, mirroring the other RAG services."""
    return Retriever()
