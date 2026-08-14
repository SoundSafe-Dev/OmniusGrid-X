"""Evidence-backed Operations Lead questions and shift briefings.

This router deliberately reuses the deterministic evidence request path.  A
question can change how the findings are presented, but it can never create a
join, upgrade an association into causation, or trigger an operating action.
"""

from __future__ import annotations

from uuid import UUID
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.api.correlation_evidence import EvidencePreviewRequest, _execute_evidence_request
from app.db.database import get_db
from app.db.models import User
from app.services.correlation_jobs import correlation_jobs
from app.services.operations_question_service import (
    answer_operations_question,
    suggested_operations_questions,
)


router = APIRouter(
    prefix="/api/v1/correlation/operations",
    tags=["Operations Lead Assistant"],
)

MAX_CITATION_EVIDENCE_ROWS = 50


class OperationsQuestionRequest(EvidencePreviewRequest):
    """Ask an evidence-backed operations question over selected intake data."""

    question: str = Field(min_length=3, max_length=2_000)


class OperationsJobQuestionRequest(BaseModel):
    """Ask a question over a completed asynchronous evidence job."""

    question: str = Field(min_length=3, max_length=2_000)


class _OpenModel(BaseModel):
    """Open by construction — see the note on the response models in
    `correlation_evidence.py`. An operations answer carries engine-decided keys, and a
    closed model would delete them from the response without saying so."""

    model_config = ConfigDict(extra="allow")


class OperationsQuestionTypesResponse(_OpenModel):
    questions: List[Dict[str, Any]] = Field(default_factory=list)
    answer_contract: Dict[str, Any] = Field(default_factory=dict)


class OperationsAnswerResponse(_OpenModel):
    """`citation_evidence` and `evidence_scope` are declared, not incidental: they are what
    makes the answer checkable, and an SDK that drops them leaves a confident paragraph
    with nothing behind it."""

    question: str
    answer: Dict[str, Any] = Field(default_factory=dict)
    citation_evidence: Optional[Dict[str, Any]] = None
    evidence_scope: Optional[Dict[str, Any]] = None
    job_id: Optional[str] = None


class OperationsBriefingResponse(_OpenModel):
    overview: Dict[str, Any] = Field(default_factory=dict)
    next_shift_checklist: Dict[str, Any] = Field(default_factory=dict)
    overview_citation_evidence: Optional[Dict[str, Any]] = None
    next_shift_checklist_citation_evidence: Optional[Dict[str, Any]] = None
    evidence_scope: Optional[Dict[str, Any]] = None


def _company_name_from_evidence(evidence: Dict[str, Any]) -> Optional[str]:
    manifests = evidence.get("ingestion_manifests") or []
    if not manifests:
        return None
    first = manifests[0] if isinstance(manifests[0], dict) else {}
    return str(first.get("file_name") or first.get("source_id") or "").strip() or None


def _evidence_scope(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Expose only the evidence run's scope, not a second bulky row payload."""

    return {
        "input_scope": evidence.get("input_scope") or {},
        "response_truncated": bool(evidence.get("response_truncated")),
        "response_row_limit": evidence.get("response_row_limit"),
        "review_required": bool(evidence.get("review_required")),
        "normalization": evidence.get("normalization") or {},
        "operations_source_scope": evidence.get("_operations_source_scope") or {},
        "confirmed_join": _evidence_has_confirmed_join(evidence),
    }


def _answer(question: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    return answer_operations_question(
        question,
        evidence,
        company_name=_company_name_from_evidence(evidence),
    )


def _request_has_confirmed_join(request: EvidencePreviewRequest) -> bool:
    """Return whether this request explicitly approves its join scope.

    A preview is useful for inspection, but an Operations Lead answer is
    decision support.  Do not let the answer path silently promote an
    automatic/proposed join into reviewed operational evidence.
    """

    if request.join_plans:
        return bool(request.confirm_join_plan)
    return bool(request.join_plan and request.confirm_join_plan)


def _evidence_has_confirmed_join(evidence: Dict[str, Any]) -> bool:
    """Check the materialized result too, not just the request flag."""

    edges = evidence.get("evidence_sets")
    if isinstance(edges, list):
        return bool(edges) and all(
            isinstance(edge, dict)
            and isinstance(edge.get("join_plan"), dict)
            and edge["join_plan"].get("approval_state") == "confirmed"
            for edge in edges
        )
    plan = evidence.get("join_plan")
    return isinstance(plan, dict) and plan.get("approval_state") == "confirmed"


def _require_confirmed_join_request(request: EvidencePreviewRequest) -> None:
    if _request_has_confirmed_join(request):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "join_confirmation_required",
            "message": (
                "Preview the proposed join, review its coverage and unmatched rows, "
                "then confirm the selected join plan before asking an Operations Lead question."
            ),
        },
    )


def _iter_evidence_rows(evidence: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Yield bounded, already-authorized rows from an in-flight evidence run."""

    for row in evidence.get("_operations_source_rows") or []:
        if isinstance(row, dict):
            yield row
    for row in evidence.get("evidence_rows") or []:
        if isinstance(row, dict):
            yield row
    for edge in evidence.get("evidence_sets") or []:
        if not isinstance(edge, dict):
            continue
        for row in edge.get("evidence_rows") or []:
            if isinstance(row, dict):
                yield row


def _citation_evidence(answer: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return only rows cited by an answer so its evidence is inspectable.

    The operations route keeps its larger raw source packet private.  This
    small map exposes at most the cited records, whose sources have already
    been tenant-authorized by the evidence request.
    """

    citation_ids = set()
    for citation in answer.get("citations") or []:
        if isinstance(citation, dict) and citation.get("evidence_id"):
            citation_ids.add(str(citation["evidence_id"]))
    for item in answer.get("checklist") or []:
        if not isinstance(item, dict):
            continue
        for citation in item.get("citations") or []:
            if isinstance(citation, dict) and citation.get("evidence_id"):
                citation_ids.add(str(citation["evidence_id"]))

    resolved: Dict[str, Dict[str, Any]] = {}
    for row in _iter_evidence_rows(evidence):
        evidence_id = str(row.get("evidence_id") or "")
        if not evidence_id or evidence_id not in citation_ids or evidence_id in resolved:
            continue
        resolved[evidence_id] = {
            "evidence_id": evidence_id,
            "match_status": row.get("match_status"),
            "join_key": row.get("join_key"),
            "lineage": row.get("lineage") or [],
            "source_rows": row.get("source_rows") or [],
            "fields": row.get("fields") or {},
        }
        if len(resolved) >= MAX_CITATION_EVIDENCE_ROWS:
            break
    return resolved


def _answer_with_citation_evidence(question: str, evidence: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    answer = _answer(question, evidence)
    return answer, _citation_evidence(answer, evidence)


async def _run_question(
    request: OperationsQuestionRequest,
    db: AsyncSession,
    current_user: User,
) -> Dict[str, Any]:
    _require_confirmed_join_request(request)
    evidence_request = EvidencePreviewRequest(
        **request.model_dump(exclude={"question"})
    ).model_copy(update={"include_operational_analytics": True})
    evidence = await _execute_evidence_request(
        db,
        evidence_request,
        current_user,
        asynchronous=False,
        include_operations_source_rows=True,
    )
    if not _evidence_has_confirmed_join(evidence):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "confirmed_join_unavailable",
                "message": "The approved join plan could not be materialized. Review the selected keys and source tables before asking a question.",
            },
        )
    answer, citation_evidence = _answer_with_citation_evidence(request.question, evidence)
    return {
        "question": request.question,
        "answer": answer,
        "citation_evidence": citation_evidence,
        "evidence_scope": _evidence_scope(evidence),
    }


@router.get("/question-types", response_model=OperationsQuestionTypesResponse)
async def operations_question_types(
    current_user: User = Depends(get_current_active_user),
):
    """Return natural-language prompts an operations lead can use directly."""

    return {
        "questions": suggested_operations_questions(),
        "answer_contract": {
            "evidence_backed": True,
            "causation": "not established from observational correlation",
            "actions": "next-shift checklists are drafts pending supervisor approval",
        },
    }


@router.post("/answer", response_model=OperationsAnswerResponse)
async def answer_operations_lead_question(
    request: OperationsQuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Build evidence first, then answer an Operations Lead's question."""

    return await _run_question(request, db, current_user)


@router.post("/briefing", response_model=OperationsBriefingResponse)
async def create_operations_briefing(
    request: EvidencePreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return a consistent overview plus a proposed next-shift checklist."""

    _require_confirmed_join_request(request)

    evidence = await _execute_evidence_request(
        db,
        request.model_copy(update={"include_operational_analytics": True}),
        current_user,
        asynchronous=False,
        include_operations_source_rows=True,
    )
    if not _evidence_has_confirmed_join(evidence):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "confirmed_join_unavailable",
                "message": "The approved join plan could not be materialized. Review the selected keys and source tables before creating a briefing.",
            },
        )
    # Keep this phrasing unambiguously in the overview intent. "What changed"
    # is intentionally its own evidence-backed question type.
    overview_question = "Give me an operations overview: performance and risks."
    checklist_question = "Give me a next-shift checklist based only on the evidence."
    overview, overview_citation_evidence = _answer_with_citation_evidence(overview_question, evidence)
    next_shift_checklist, checklist_citation_evidence = _answer_with_citation_evidence(checklist_question, evidence)
    return {
        "overview": overview,
        "next_shift_checklist": next_shift_checklist,
        "overview_citation_evidence": overview_citation_evidence,
        "next_shift_checklist_citation_evidence": checklist_citation_evidence,
        "evidence_scope": _evidence_scope(evidence),
    }


@router.post("/jobs/{job_id}/answer", response_model=OperationsAnswerResponse)
async def answer_completed_job_question(
    job_id: UUID,
    request: OperationsJobQuestionRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Answer a question from a completed tenant-scoped evidence job result."""

    job = await correlation_jobs.get(str(job_id))
    if (
        job is None
        or job.get("organization_id") != str(current_user.organization_id)
        or job.get("actor_id") != str(current_user.id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Correlation job not found")
    if job.get("status") != "completed" or not isinstance(job.get("result"), dict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The evidence job must finish before it can answer operations questions.",
        )
    evidence = dict(job["result"])
    if not _evidence_has_confirmed_join(evidence):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "join_confirmation_required",
                "message": "This job contains a proposed preview, not a confirmed join. Review and confirm a join plan before asking an Operations Lead question.",
            },
        )
    answer, citation_evidence = _answer_with_citation_evidence(request.question, evidence)
    return {
        "question": request.question,
        "answer": answer,
        "citation_evidence": citation_evidence,
        "evidence_scope": _evidence_scope(evidence),
        "job_id": job_id,
    }
