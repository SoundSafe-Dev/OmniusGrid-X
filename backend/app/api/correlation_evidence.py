"""Evidence-first operational correlation APIs.

This router is deliberately separate from the conversational Correlation AI
routes.  It provides a reviewable, deterministic record-linking result first;
an LLM may explain that evidence later, but cannot manufacture a match or
trigger an action from an unreviewed join.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.api.nlp_correlation import load_intake_content
from app.core.config import settings
from app.db.database import AsyncSessionLocal
# `get_tenant_db`, not `get_db`: `intake_items` is FORCE ROW LEVEL SECURITY (migration
# 011), so a session with no `app.current_org_id` GUC reads ZERO rows and no error —
# these handlers would 404 on the caller's own uploads. The explicit user/org filters in
# `_owned_intake_items` stay as the second layer; RLS is the one a new handler cannot
# forget, the filter is the one that survives a session opened without the GUC.
from app.middleware.tenant_isolation import get_tenant_db
from app.db.models import IntakeItem, User
from app.models.correlation_evaluation import (
    ApprovalPolicy,
    ApprovalResult,
    AutomatedAction,
    CorrelationEvaluationFixture,
    CorrelationEvaluationCase,
    CorrelationEvaluationResult,
    CorrelationEvaluationSuiteReport,
    CorrelationQualityReport,
    CorrelationCandidate,
    CustomerVocabularyFeedback,
    HumanApprovalDecision,
    InputDataQualitySnapshot,
    QualityGateThresholds,
    VocabularyFeedbackKind,
    VocabularyFeedbackStatus,
    EvidenceReference,
)
from app.services.correlation_evaluation import (
    ApprovalPolicyService,
    CorrelationQualityMonitor,
    CustomerVocabularyService,
    VocabularyFeedbackError,
    VocabularyFeedbackNotFound,
    build_quality_report,
    evaluate_correlation_case,
    evaluate_correlation_suite,
)
from app.services.correlation_jobs import correlation_jobs
from app.services.evidence_engine import (
    build_evidence_graph,
    build_evidence_table,
    build_entity_rollups,
    profile_join_candidates,
)
from app.services.ingestion_adapters import (
    IngestionLimits,
    capability_manifest,
    detect_format,
    ingest_file,
    plan_connector_ingestion,
)

logger = structlog.get_logger()

router = APIRouter(
    prefix="/api/v1/correlation/evidence",
    tags=["Evidence Correlation"],
)

MAX_SOURCES_PER_REQUEST = 25
MAX_PREVIEW_ROWS = 5_000
# The response itself is still compacted to five thousand rows per evidence
# edge. This larger *processing* budget lets a normal six-domain shift packet
# (15 pairs × roughly 1k records) be analyzed without silently reducing every
# relationship to a few hundred records.
MAX_PREVIEW_MATCH_PAIRS = 25_000
# Operations answers may summarize selected source tables that do not form a
# safe pairwise join (for example, a safety log). Keep that internal evidence
# packet bounded and fair across tables; it never becomes a raw API response.
MAX_OPERATIONAL_ANSWER_SOURCE_ROWS = 50_000
# This limits the tables that reach pairwise candidate profiling. Ingestion
# may catalogue more archive children safely, but a user must select a bounded
# operational subset before asking the graph engine to compare them all.
MAX_TABLE_SELECTIONS_PER_SOURCE = 50


class EvidencePreviewRequest(BaseModel):
    """Request a deterministic, lineage-preserving common-table preview."""

    # A single workbook, archive, or document can expose several structured
    # tables (for example, Excel sheets).  The request therefore accepts one
    # intake item; _load_evidence_sources enforces the actual invariant that
    # there must be at least two readable tables to correlate.
    intake_ids: List[UUID] = Field(min_length=1, max_length=MAX_SOURCES_PER_REQUEST)
    join_plan: Optional[Dict[str, Any]] = None
    join_plans: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=25)
    confirm_join_plan: bool = False
    time_bucket_minutes: int = Field(default=60, ge=1, le=24 * 60)
    include_weak_keys: bool = False
    include_operational_analytics: bool = False
    assumed_timezone: str = Field(default="UTC", min_length=1, max_length=64)
    # Mapping scope keys are either "*" or "<source_id>/<table_name>". The
    # mappings are explicit review aids, never fuzzy schema guesses.
    schema_mappings: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    # Maps an Intake UUID to exact workbook table names or ZIP archive-member
    # paths returned by `/intake/catalog`. A ZIP selection is intentionally a
    # whole archive member (such as a multi-sheet FY2024 workbook), applied
    # before parsing so irrelevant archive children do not consume capacity.
    table_selection: Dict[str, List[str]] = Field(default_factory=dict)
    apply_long_form_normalization: bool = True
    max_match_pairs: int = Field(default=MAX_PREVIEW_ROWS, ge=1, le=MAX_PREVIEW_MATCH_PAIRS)


class EvidenceJobRequest(EvidencePreviewRequest):
    """The same intent as a preview, scheduled outside the request lifecycle."""

    max_match_pairs: int = Field(default=MAX_PREVIEW_ROWS, ge=1, le=MAX_PREVIEW_MATCH_PAIRS)


class EvidenceCatalogRequest(BaseModel):
    """List selectable tables/archive children without creating a join."""

    intake_ids: List[UUID] = Field(min_length=1, max_length=MAX_SOURCES_PER_REQUEST)


class EvaluationRunRequest(BaseModel):
    """Run a human-curated known-good false-match/false-negative fixture."""

    fixture: CorrelationEvaluationFixture
    input_quality: Optional[InputDataQualitySnapshot] = None
    thresholds: Optional[QualityGateThresholds] = None


class EvidenceEvaluationRequest(BaseModel):
    """Run a known-good evaluation against a freshly built evidence preview."""

    evidence: EvidencePreviewRequest
    case: CorrelationEvaluationCase
    input_quality: Optional[InputDataQualitySnapshot] = None
    thresholds: Optional[QualityGateThresholds] = None


class VocabularyReviewRequest(BaseModel):
    approved: bool
    review_note: Optional[str] = Field(default=None, max_length=2_000)


class ActionAssessmentRequest(BaseModel):
    action: AutomatedAction
    policy: Optional[ApprovalPolicy] = None


class ActionDecisionRequest(BaseModel):
    action: AutomatedAction
    policy: Optional[ApprovalPolicy] = None
    decision: HumanApprovalDecision


class ConnectorPlanRequest(BaseModel):
    """A credential-reference-only plan for a future external source job."""

    configuration: Dict[str, Any] = Field(default_factory=dict)
    entities: Optional[List[str]] = Field(default=None, max_length=100)
    cursor: Optional[str] = Field(default=None, max_length=2_000)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
#
# EVERY ONE OF THESE SETS `extra="allow"`, AND THAT IS THE WHOLE DESIGN.
#
# These routes answer with evidence payloads whose keys the engine decides per request:
# which tables it could join, which qualifiers it had to attach, which rollups it
# truncated. A closed model would DROP the keys it does not name — `response_model`
# filters silently — so declaring one by enumerating today's keys would quietly delete
# tomorrow's from the response, with no error anywhere.
#
# `extra="allow"` gives both halves: the fields below are named in the OpenAPI schema, the
# contract gate and the generated SDK, and anything else the engine sends passes through
# untouched. Verified rather than assumed — a route declaring one of these was called with
# an undeclared nested key and the key came back.
#
# The alternative was `response_model=Dict[str, Any]`, which is what these routes carried
# for about an hour. It satisfies the coverage ratchet and declares nothing, which is the
# exact trap `test_a_permissive_response_model_is_not_a_contract.py` was written for
# (rule 187: ask what the cheapest reduction of a ratchet would do). That file caught it.


class _OpenModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class EvidenceCapabilitiesResponse(_OpenModel):
    """What this deployment can ingest, and the bounds it will enforce."""

    capabilities: Dict[str, Any] = Field(default_factory=dict)
    limits: Dict[str, Any] = Field(default_factory=dict)
    normalization: Dict[str, Any] = Field(default_factory=dict)
    #: A SENTENCE, not an object — read from the handler after typing it as a dict here
    #: 500'd the route. `extra="allow"` protects against a missing key, never against a
    #: wrong type for a declared one.
    approval: str = ""


class ConnectorPlanResponse(_OpenModel):
    """A plan only. `connection_attempted` is always false and is declared so a caller
    cannot read a plan as evidence that the source was reached."""

    status: str
    connection_attempted: bool = False
    connector: Optional[Dict[str, Any]] = None
    provided_configuration_keys: Optional[List[str]] = None
    missing_required_configuration_keys: Optional[List[str]] = None
    requested_entities: Optional[List[str]] = None
    cursor_supplied: Optional[bool] = None
    available_connectors: Optional[List[str]] = None
    error: Optional[Dict[str, Any]] = None


class EvidenceCatalogResponse(_OpenModel):
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    selection_contract: Dict[str, Any] = Field(default_factory=dict)


class EvidenceResultResponse(_OpenModel):
    """The correlated evidence payload.

    The bounding flags are declared explicitly — `truncated`, `response_truncated`,
    `review_required` — because a caveat that is not in the schema is a caveat the
    generated client does not carry, and these are the fields that say how far the numbers
    beside them can be trusted.
    """

    selection_mode: Optional[str] = None
    join_plan: Optional[Dict[str, Any]] = None
    candidate_join_plans: Optional[List[Dict[str, Any]]] = None
    evidence_rows: Optional[List[Dict[str, Any]]] = None
    quality: Optional[Dict[str, Any]] = None
    normalization: Optional[Dict[str, Any]] = None
    operational_analytics: Optional[Dict[str, Any]] = None
    entity_rollups: Optional[Dict[str, Any]] = None
    ingestion_manifests: Optional[List[Dict[str, Any]]] = None
    input_scope: Optional[Dict[str, Any]] = None
    vocabulary_provenance: Optional[Dict[str, Any]] = None
    review_required: Optional[bool] = None
    truncated: Optional[bool] = None
    response_truncated: Optional[bool] = None


class EvidenceJobAcceptedResponse(_OpenModel):
    """202. The two URLs are declared because they are the only way a caller learns where
    to poll and how to stop the work it just started."""

    job_id: str
    status: str
    status_url: str
    cancel_url: str


class EvidenceJobResponse(_OpenModel):
    job_id: str
    type: Optional[str] = None
    status: str
    stage: Optional[str] = None
    progress: Optional[float] = None
    processed: Optional[int] = None
    total: Optional[int] = None
    organization_id: Optional[str] = None
    actor_id: Optional[str] = None
    input_summary: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CorrelationEvaluationResponse(_OpenModel):
    #: THE REAL MODELS, not `Dict[str, Any]`. These handlers return
    #: `CorrelationEvaluationResult` / `SuiteReport` / `QualityReport` objects, and a dict
    #: annotation does not merely under-describe them — pydantic refuses to validate a
    #: BaseModel as a mapping, so the route would 500 on serialisation. Read the callee's
    #: return type before annotating what a handler returns; `GET /capabilities` proved the
    #: same point from the other direction by declaring a sentence as an object.
    case_result: Optional[CorrelationEvaluationResult] = None
    suite_report: Optional[CorrelationEvaluationSuiteReport] = None
    quality_report: Optional[CorrelationQualityReport] = None


class FreshEvidenceEvaluationResponse(CorrelationEvaluationResponse):
    evidence: Optional[Dict[str, Any]] = None
    observed_candidates: Optional[List[CorrelationCandidate]] = None


class CorrelationQualityResponse(_OpenModel):
    """`quality_report` is nullable: no evaluation has run yet is a distinct state from a
    report saying quality is bad, and a caller must be able to tell them apart."""

    quality_report: Optional[CorrelationQualityReport] = None


class VocabularyListResponse(_OpenModel):
    items: List[CustomerVocabularyFeedback] = Field(default_factory=list)


_vocabulary = CustomerVocabularyService()
_quality_monitor = CorrelationQualityMonitor()
_approval_policy = ApprovalPolicyService()


_VOCABULARY_FIELD_ALIASES = {
    "asset": "asset_id",
    "machine": "asset_id",
    "machine_id": "asset_id",
    "equipment": "asset_id",
    "equipment_id": "asset_id",
    "facility": "facility",
    "facility_id": "facility",
    "plant": "facility",
    "site": "facility",
    "date": "event_time",
    "timestamp": "event_time",
    "time": "event_time",
}


def _vocabulary_field_name(value: Optional[str], *, default: str = "asset_id") -> str:
    """Map a reviewed feedback field to the evidence engine's stable names."""
    from app.services.shared_key_detector import normalize_column_header

    normalized = normalize_column_header(value or default)
    return _VOCABULARY_FIELD_ALIASES.get(normalized, normalized or default)


def _approved_vocabulary_mappings(
    organization_id: str,
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str], List[str]]:
    """Return only tenant-approved, deterministic vocabulary mappings.

    Pending feedback is intentionally absent.  This makes entity resolution a
    reproducible normalization rule rather than a model suggestion.
    """
    value_aliases: Dict[str, Dict[str, str]] = {}
    column_aliases: Dict[str, str] = {}
    feedback_ids: List[str] = []
    for feedback in _vocabulary.list_feedback(
        organization_id,
        status=VocabularyFeedbackStatus.APPROVED,
    ):
        if feedback.kind in {
            VocabularyFeedbackKind.ENTITY_ALIAS,
            VocabularyFeedbackKind.VALUE_ALIAS,
        }:
            field_name = _vocabulary_field_name(feedback.field_name)
            value_aliases.setdefault(field_name, {})[feedback.raw_term] = feedback.canonical_term
            feedback_ids.append(feedback.feedback_id)
        elif feedback.kind is VocabularyFeedbackKind.COLUMN_ALIAS:
            column_aliases[feedback.raw_term] = feedback.canonical_term
            feedback_ids.append(feedback.feedback_id)
    return value_aliases, column_aliases, feedback_ids


def _normalization_mapping_for_table(
    source_id: str,
    table_name: str,
    *,
    approved_column_aliases: Dict[str, str],
    requested_mappings: Dict[str, Dict[str, str]],
) -> Dict[str, str]:
    mapping = dict(approved_column_aliases)
    mapping.update(requested_mappings.get("*", {}))
    mapping.update(requested_mappings.get(f"{source_id}/{table_name}", {}))
    return mapping


def _prepare_normalized_sources(
    sources: Sequence[Dict[str, Any]],
    *,
    assumed_timezone: str,
    requested_mappings: Dict[str, Dict[str, str]],
    approved_column_aliases: Dict[str, str],
    apply_long_form_normalization: bool,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Apply safe long-form normalization and expose mapping/quality evidence.

    Wide operational tables retain their original values; they receive schema
    and unit-detection aids only.  Long-form value/unit rows gain canonical
    fields alongside their originals, preserving both source fidelity and a
    reviewable normalized representation.
    """
    from app.services.operational_normalization import (
        OperationalEvidenceNormalizer,
        normalize_header,
    )

    normalizer = OperationalEvidenceNormalizer(assumed_timezone=assumed_timezone)
    prepared: List[Dict[str, Any]] = []
    table_summaries: List[Dict[str, Any]] = []
    total_measurement_rows = 0
    normalized_row_count = 0
    review_required_rows = 0
    quality_scores: List[int] = []
    issue_counts: Dict[str, int] = {}
    timestamp_normalized_rows = 0
    timestamp_failure_rows = 0
    timestamp_assumption_rows = 0

    for source in sources:
        source_id = str(source["source_id"])
        output_source = dict(source)
        output_tables: Dict[str, List[Dict[str, Any]]] = {}
        for table_name, rows in (source.get("tables") or {}).items():
            row_list = [dict(row) for row in rows]
            headers: List[str] = []
            for row in row_list[:100]:
                for header in row:
                    if str(header) not in headers:
                        headers.append(str(header))
            requested_mapping = _normalization_mapping_for_table(
                source_id,
                str(table_name),
                approved_column_aliases=approved_column_aliases,
                requested_mappings=requested_mappings,
            )
            # Vocabulary feedback is normalized for matching but applied back
            # to the exact source header so the normalizer can retain lineage.
            explicit_mapping = {
                header: target
                for source, target in requested_mapping.items()
                for header in headers
                if header == source or normalize_header(header) == normalize_header(source)
            }
            mapping_aids = normalizer.mapping_aids(headers)
            resolved_mapping = dict(mapping_aids.get("suggested_mapping") or {})
            # Explicit mappings deliberately override aids after being
            # validated by the normalizer for each source row.
            resolved_mapping.update(explicit_mapping)
            target_fields = set(resolved_mapping.values())
            can_normalize_values = (
                apply_long_form_normalization
                and "value" in target_fields
                and "unit" in target_fields
            )
            can_normalize_timestamps = "event_time" in target_fields
            converted_rows = row_list
            table_normalized_count = 0
            table_review_count = 0
            table_scores: List[int] = []
            table_timestamp_normalized_count = 0
            table_timestamp_failure_count = 0
            table_timestamp_assumption_count = 0
            if can_normalize_values or can_normalize_timestamps:
                converted_rows = []
                for row in row_list:
                    normalized = normalizer.normalize_row(
                        row,
                        field_mapping=explicit_mapping or None,
                    )
                    enriched = dict(row)
                    if can_normalize_values:
                        for field, value in normalized.normalized_row.items():
                            if value is not None:
                                enriched[field] = value
                    else:
                        # A wide table keeps its measurements untouched while
                        # still gaining a timezone-explicit canonical join key.
                        for field in (
                            "asset_id", "facility_id", "line_id", "work_order_id",
                            "batch_id", "shift", "event_time",
                        ):
                            value = normalized.normalized_row.get(field)
                            if value is not None:
                                enriched[field] = value
                    converted_rows.append(enriched)
                    if can_normalize_values:
                        table_normalized_count += 1
                        table_scores.append(normalized.quality.score)
                        if normalized.quality.review_required:
                            table_review_count += 1
                        for issue in normalized.quality.issues:
                            issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1
                    if can_normalize_timestamps:
                        if normalized.timestamp.success:
                            table_timestamp_normalized_count += 1
                            if normalized.timestamp.timezone_assumption:
                                table_timestamp_assumption_count += 1
                        else:
                            table_timestamp_failure_count += 1
                            if normalized.timestamp.error_code and not can_normalize_values:
                                code = normalized.timestamp.error_code
                                issue_counts[code] = issue_counts.get(code, 0) + 1

            output_tables[str(table_name)] = converted_rows
            if can_normalize_values:
                total_measurement_rows += len(row_list)
                normalized_row_count += table_normalized_count
                review_required_rows += table_review_count
                quality_scores.extend(table_scores)
            timestamp_normalized_rows += table_timestamp_normalized_count
            timestamp_failure_rows += table_timestamp_failure_count
            timestamp_assumption_rows += table_timestamp_assumption_count
            table_summaries.append({
                "source_id": source_id,
                "table_name": str(table_name),
                "row_count": len(row_list),
                "normalization_applied": can_normalize_values,
                "timestamp_normalization_applied": can_normalize_timestamps,
                "normalized_row_count": table_normalized_count,
                "review_required_row_count": table_review_count,
                "timestamp_normalized_row_count": table_timestamp_normalized_count,
                "timestamp_failure_row_count": table_timestamp_failure_count,
                "timestamp_assumption_row_count": table_timestamp_assumption_count,
                "average_quality_score": (
                    round(sum(table_scores) / len(table_scores), 2)
                    if table_scores else None
                ),
                "schema_mapping_aids": mapping_aids,
                "explicit_mapping": explicit_mapping,
            })
        output_source["tables"] = output_tables
        prepared.append(output_source)

    return prepared, {
        "assumed_timezone": assumed_timezone,
        "long_form_normalization_enabled": apply_long_form_normalization,
        "measurement_row_count": total_measurement_rows,
        "normalized_row_count": normalized_row_count,
        "review_required_row_count": review_required_rows,
        "average_quality_score": (
            round(sum(quality_scores) / len(quality_scores), 2)
            if quality_scores else None
        ),
        "issue_counts": issue_counts,
        "timestamp_normalized_row_count": timestamp_normalized_rows,
        "timestamp_failure_row_count": timestamp_failure_rows,
        "timestamp_assumption_row_count": timestamp_assumption_rows,
        "tables": table_summaries,
    }


def _ingestion_limits(*, asynchronous: bool, source_count: int) -> IngestionLimits:
    """Return bounded parsing limits appropriate to preview or job execution."""
    # Evidence joins are currently materialized in the worker process.  The
    # bounds keep an accidental huge source from becoming an unbounded Python
    # list while raw files remain durable in object storage for reprocessing.
    row_limit = (
        settings.CORRELATION_MAX_ROWS_PER_TABLE
        if asynchronous
        else min(settings.CORRELATION_SYNC_MAX_ROWS, settings.CORRELATION_MAX_ROWS_PER_TABLE)
    )
    return IngestionLimits(
        max_file_bytes=settings.CORRELATION_MAX_UPLOAD_BYTES,
        # Retain a complete bounded archive/workbook catalog per source. The
        # separate graph scope below prevents these retained tables from
        # becoming an unbounded all-pairs correlation request.
        max_tables=settings.CORRELATION_MAX_INGESTED_TABLES_PER_SOURCE,
        max_rows_per_table=row_limit,
        max_total_rows=row_limit,
        max_columns=settings.CORRELATION_MAX_COLUMNS_PER_TABLE,
        max_zip_entries=settings.CORRELATION_MAX_ARCHIVE_ENTRIES,
        max_zip_uncompressed_bytes=settings.CORRELATION_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
    )


def _normalised_table_selection(
    table_selection: Dict[str, List[str]],
    source_id: str,
) -> List[str]:
    """Validate exact, user-visible selection refs for one owned source."""

    raw_refs = table_selection.get(source_id) or []
    if not isinstance(raw_refs, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="table_selection must map each source ID to a list of exact table references.",
        )
    refs: List[str] = []
    for value in raw_refs:
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Each table selection must be a non-empty string returned by the table catalog.",
            )
        text = value.strip()
        if text not in refs:
            refs.append(text)
    if len(refs) > MAX_TABLE_SELECTIONS_PER_SOURCE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Select at most %d table/archive entries per source before correlation. "
                "Narrow the scope to the operational tables relevant to the question."
                % MAX_TABLE_SELECTIONS_PER_SOURCE
            ),
        )
    return refs


def _is_zip_source(content: bytes, filename: Optional[str]) -> bool:
    """Use the bounded detector rather than trusting a filename extension."""

    return detect_format(content, str(filename or "upload")).format == "zip"


def _selected_tables(
    tables: Dict[str, Any],
    manifest: Dict[str, Any],
    selection_refs: Sequence[str],
) -> Dict[str, Any]:
    """Filter parsed tables by exact catalog refs while preserving order."""

    if not selection_refs:
        return tables
    wanted = set(selection_refs)
    schemas = {
        str(schema.get("name")): schema
        for schema in (manifest.get("tables") or [])
        if isinstance(schema, dict) and schema.get("name")
    }
    selected: Dict[str, Any] = {}
    for table_name, rows in tables.items():
        schema = schemas.get(str(table_name)) or {}
        metadata = schema.get("source_metadata") or {}
        refs = {
            str(table_name),
            str(schema.get("source_table") or ""),
            str(metadata.get("archive_path") or ""),
            str(metadata.get("normalized_archive_path") or ""),
        }
        refs.discard("")
        if wanted.intersection(refs):
            selected[str(table_name)] = rows
    return selected


def _source_format(manifest: Dict[str, Any]) -> Optional[str]:
    """Read the adapter's detected source format without trusting payload shape."""

    source = manifest.get("source")
    if not isinstance(source, dict):
        return None
    descriptor = source.get("format")
    if not isinstance(descriptor, dict):
        return None
    value = descriptor.get("format")
    return str(value) if value else None


def _table_catalog(
    source_id: str,
    source_name: str,
    tables: Dict[str, Any],
    manifest: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return stable, user-selectable table/ZIP-child references."""

    schemas = {
        str(schema.get("name")): schema
        for schema in (manifest.get("tables") or [])
        if isinstance(schema, dict) and schema.get("name")
    }
    catalog: List[Dict[str, Any]] = []
    # A ZIP can have far more child workbooks/files than the bounded parser is
    # allowed to retain as tables. Its manifest is still complete and safe to
    # expose, so list every archive member as a selectable unit. Selecting one
    # member lets the ZIP adapter avoid parsing unrelated children altogether.
    batch_manifest = manifest.get("batch_manifest")
    if isinstance(batch_manifest, dict):
        children_by_path = {
            str(child.get("normalized_path") or child.get("path")): child
            for child in (batch_manifest.get("children") or [])
            if isinstance(child, dict) and (child.get("normalized_path") or child.get("path"))
        }
        for entry in batch_manifest.get("entries") or []:
            if not isinstance(entry, dict) or entry.get("is_directory"):
                continue
            normalized_path = str(entry.get("normalized_path") or entry.get("path") or "").strip()
            if not normalized_path:
                continue
            child = children_by_path.get(normalized_path) or {}
            catalog.append({
                "selection_ref": normalized_path,
                "selection_kind": "archive_member",
                "table_name": normalized_path,
                "source_table": normalized_path,
                "archive_path": normalized_path,
                "format": entry.get("format"),
                "row_count_preview": None,
                "parsed_table_count_preview": len(child.get("tables") or []),
                "parse_status": child.get("status", "manifested"),
                "source_id": source_id,
                "source_name": source_name,
            })
    for table_name in tables:
        schema = schemas.get(str(table_name)) or {}
        metadata = schema.get("source_metadata") or {}
        archive_path = metadata.get("normalized_archive_path") or metadata.get("archive_path")
        # Archive entries are selected as an all-sheets/files unit. Avoid
        # producing duplicate selectable rows for every sheet in an archived
        # workbook; their parsed count remains visible on the member record.
        if archive_path and isinstance(batch_manifest, dict):
            continue
        selection_ref = str(archive_path or table_name)
        catalog.append({
            "selection_ref": selection_ref,
            "selection_kind": "table",
            "table_name": str(table_name),
            "source_table": str(schema.get("source_table") or table_name),
            "archive_path": archive_path,
            "format": metadata.get("child_format") or _source_format(manifest),
            "row_count_preview": schema.get("row_count"),
            "parsed_table_count_preview": 1,
            "parse_status": "parsed",
            "source_id": source_id,
            "source_name": source_name,
        })
    return catalog


def _catalog_from_sources(sources: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for source in sources:
        catalog.extend(_table_catalog(
            str(source.get("source_id") or ""),
            str(source.get("source_name") or source.get("source_id") or ""),
            source.get("tables") or {},
            source.get("manifest") or {},
        ))
    return catalog


def _readable_table_count(sources: Sequence[Dict[str, Any]]) -> int:
    """Count parsed tables, not just uploaded files.

    A workbook with Production, Maintenance, and Quality sheets is one intake
    source but three independently lineage-preserving evidence tables.  Keeping
    this distinction at the API boundary lets the same safe engine support
    single-workbook and multi-file correlations without fabricating a source.
    """
    return sum(len(source.get("tables") or {}) for source in sources)


def _operations_answer_source_rows(
    sources: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build bounded source-level evidence for an operations answer.

    Pairwise graph rows are the only valid substrate for a correlation claim,
    but an Operations Lead also needs source-specific facts from a selected
    safety, logistics, or workforce table that has no safe join to production.
    These records retain single-row lineage and are held only for the answer
    request; they are never returned as a raw evidence-preview payload.
    """

    table_items: List[Tuple[str, str, str, List[Any]]] = []
    total_available = 0
    for source in sources:
        source_id = str(source.get("source_id") or "source")
        source_name = str(source.get("source_name") or source_id)
        for table_name, table_rows in (source.get("tables") or {}).items():
            rows = list(table_rows or [])
            table_items.append((source_id, source_name, str(table_name), rows))
            total_available += len(rows)
    if not table_items:
        return [], {
            "available_source_record_count": 0,
            "retained_source_record_count": 0,
            "truncated": False,
        }

    per_table_limit = (
        max(1, MAX_OPERATIONAL_ANSWER_SOURCE_ROWS // len(table_items))
        if total_available > MAX_OPERATIONAL_ANSWER_SOURCE_ROWS
        else None
    )
    rows: List[Dict[str, Any]] = []
    truncated = False
    for source_id, source_name, table_name, table_rows in table_items:
        retained_rows = table_rows if per_table_limit is None else table_rows[:per_table_limit]
        if len(retained_rows) < len(table_rows):
            truncated = True
        for row_number, raw_row in enumerate(retained_rows, start=1):
            if not isinstance(raw_row, dict):
                continue
            lineage = {
                "source_id": source_id,
                "source_name": source_name,
                "table_name": table_name,
                "row_number": row_number,
                "row_id": "%s:%s:%d" % (source_id, table_name, row_number),
            }
            rows.append({
                "evidence_id": "source:%s:%s:%d" % (source_id, table_name, row_number),
                "match_status": "source_row",
                "lineage": [lineage],
                "fields": {
                    "%s/%s.%s" % (source_id, table_name, str(field)): value
                    for field, value in raw_row.items()
                },
            })
    return rows, {
        "available_source_record_count": total_available,
        "retained_source_record_count": len(rows),
        "truncated": truncated,
        "per_table_row_limit": per_table_limit,
    }


async def _owned_intake_items(
    db: AsyncSession,
    intake_ids: Sequence[UUID],
    current_user: User,
) -> List[IntakeItem]:
    unique_ids = list(dict.fromkeys(str(value) for value in intake_ids))
    result = await db.execute(
        select(IntakeItem).where(
            IntakeItem.id.in_(unique_ids),
            IntakeItem.user_id == current_user.id,
            IntakeItem.organization_id == current_user.organization_id,
        )
    )
    items_by_id = {str(item.id): item for item in result.scalars().all()}
    missing = [value for value in unique_ids if value not in items_by_id]
    if missing:
        # Do not disclose whether an arbitrary UUID exists in another tenant.
        raise HTTPException(status_code=404, detail="One or more intake sources were not found")
    return [items_by_id[value] for value in unique_ids]


async def _load_evidence_sources(
    db: AsyncSession,
    intake_ids: Sequence[UUID],
    current_user: User,
    *,
    asynchronous: bool,
    table_selection: Optional[Dict[str, List[str]]] = None,
    report=None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Read owned raw artifacts through the bounded adapter layer."""
    items = await _owned_intake_items(db, intake_ids, current_user)
    selected_by_source = table_selection or {}
    item_ids = {str(item.id) for item in items}
    unknown_selection_sources = sorted(set(selected_by_source).difference(item_ids))
    if unknown_selection_sources:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="table_selection includes a source that is not in this owned evidence request.",
        )
    sources: List[Dict[str, Any]] = []
    manifests: List[Dict[str, Any]] = []
    limits = _ingestion_limits(
        asynchronous=asynchronous,
        source_count=len(intake_ids),
    )

    for index, item in enumerate(items, start=1):
        source_id = str(item.id)
        selection_refs = _normalised_table_selection(selected_by_source, source_id)
        if report:
            await report(
                stage="ingesting_source",
                progress=round(10.0 + (30.0 * (index - 1) / max(1, len(items))), 1),
                processed=index - 1,
                total=len(items),
            )
        try:
            content = await load_intake_content(item)
        except ValueError as exc:
            manifests.append({
                "source_id": str(item.id),
                "file_name": item.file_name,
                "status": "unavailable",
                "manifest": {},
                "warnings": [],
                "errors": [{
                    "code": "source_artifact_unavailable",
                    "message": str(exc),
                    "remediation": "Re-upload the source or restore its raw evidence artifact.",
                }],
            })
            if report:
                await report(
                    stage="ingesting_source",
                    progress=round(10.0 + (30.0 * index / max(1, len(items))), 1),
                    processed=index,
                    total=len(items),
                )
            continue
        # Catalogued ZIP member paths may sit at the archive root (for example
        # ``FY2024.xlsx``), so do not infer them from a slash. Every selection
        # for a ZIP is an exact member reference and is validated by the
        # adapter before any child is decompressed.
        archive_entry_allowlist = (
            (selection_refs or None)
            if _is_zip_source(content, item.file_name or item.title)
            else None
        )
        parsed = ingest_file(
            content,
            item.file_name or item.title or "upload",
            limits=limits,
            archive_entry_allowlist=archive_entry_allowlist,
        )
        parsed_manifest = parsed.get("manifest") or {}
        available_refs = {
            str(record.get("selection_ref"))
            for record in _table_catalog(
                source_id,
                item.file_name or item.title or source_id,
                parsed.get("tables") or {},
                parsed_manifest,
            )
            if record.get("selection_ref")
        }
        unknown_refs = [reference for reference in selection_refs if reference not in available_refs]
        if unknown_refs:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "unknown_table_selection",
                    "message": "One or more selected table references are no longer available. Refresh the table catalog before retrying.",
                    "unknown_references": unknown_refs[:10],
                    "available_tables": _table_catalog(
                        source_id,
                        item.file_name or item.title or source_id,
                        parsed.get("tables") or {},
                        parsed_manifest,
                    ),
                },
            )
        tables = _selected_tables(
            parsed.get("tables") or {},
            parsed_manifest,
            selection_refs,
        )
        manifests.append({
            "source_id": source_id,
            "file_name": item.file_name,
            "status": parsed.get("status"),
            "manifest": parsed_manifest,
            "warnings": parsed.get("warnings") or [],
            "errors": parsed.get("errors") or [],
            "selected_table_refs": selection_refs,
            "selected_table_count": len(tables),
        })
        if tables:
            sources.append({
                "source_id": source_id,
                "source_name": item.file_name or item.title,
                "tables": tables,
                "manifest": parsed_manifest,
            })
        if report:
            await report(
                stage="ingesting_source",
                progress=round(10.0 + (30.0 * index / max(1, len(items))), 1),
                processed=index,
                total=len(items),
            )

    readable_table_count = _readable_table_count(sources)
    if readable_table_count < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": (
                    "At least two readable structured tables are required. Select two files, "
                    "or select one workbook/archive with at least two readable sheets or tables. "
                    "Inspect ingestion_manifests for parser capability warnings."
                ),
                "ingestion_manifests": manifests,
                "selected_intake_count": len(intake_ids),
                "readable_source_count": len(sources),
                "readable_table_count": readable_table_count,
            },
        )
    return sources, manifests


async def _catalog_intake_tables(
    db: AsyncSession,
    intake_ids: Sequence[UUID],
    current_user: User,
) -> List[Dict[str, Any]]:
    """Return selectable table/archive-member references with one-row sampling.

    This intentionally has a much smaller row budget than an evidence run.
    It lets an operator pick a ZIP child (such as the FY2024 workbook) before
    the full row-level parser is asked to process it.
    """

    items = await _owned_intake_items(db, intake_ids, current_user)
    limits = _ingestion_limits(asynchronous=False, source_count=len(items))
    catalog_limits = replace(
        limits,
        max_rows_per_table=1,
        max_total_rows=max(1, limits.max_tables),
    )
    catalog_sources: List[Dict[str, Any]] = []
    for item in items:
        source_id = str(item.id)
        try:
            content = await load_intake_content(item)
        except ValueError as exc:
            catalog_sources.append({
                "source_id": source_id,
                "file_name": item.file_name,
                "status": "unavailable",
                "tables": [],
                "warnings": [],
                "errors": [{
                    "code": "source_artifact_unavailable",
                    "message": str(exc),
                }],
            })
            continue
        parsed = ingest_file(
            content,
            item.file_name or item.title or "upload",
            limits=catalog_limits,
        )
        manifest = parsed.get("manifest") or {}
        tables = parsed.get("tables") or {}
        catalog_sources.append({
            "source_id": source_id,
            "file_name": item.file_name or item.title,
            "status": parsed.get("status"),
            "tables": _table_catalog(
                source_id,
                item.file_name or item.title or source_id,
                tables,
                manifest,
            ),
            "table_limit": manifest.get("table_limit") or {},
            "warnings": parsed.get("warnings") or [],
            "errors": parsed.get("errors") or [],
        })
    return catalog_sources


def _compact_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Keep API/job responses useful without returning an unbounded row blob."""
    compact = dict(result)
    evidence_sets = compact.get("evidence_sets")
    nested_truncated = False
    if evidence_sets is not None:
        compact["evidence_sets"] = [
            _compact_result(dict(edge)) for edge in list(evidence_sets)
        ]
        nested_truncated = any(
            bool(edge.get("response_truncated"))
            for edge in compact["evidence_sets"]
        )

    row_keys = (
        "evidence_rows",
        "matched_rows",
        "unmatched_left_rows",
        "unmatched_right_rows",
    )
    response_truncated = nested_truncated
    for key in row_keys:
        rows = list(compact.get(key) or [])
        if len(rows) > MAX_PREVIEW_ROWS:
            compact[key] = rows[:MAX_PREVIEW_ROWS]
            response_truncated = True
    compact["response_truncated"] = response_truncated
    compact["response_row_limit"] = MAX_PREVIEW_ROWS
    candidates = list(compact.get("candidate_join_plans") or [])
    if len(candidates) > 100:
        compact["candidate_join_plans"] = candidates[:100]
        compact["candidate_join_plans_truncated"] = True
    return compact


def _evaluation_candidates_from_evidence(result: Dict[str, Any]) -> List[CorrelationCandidate]:
    """Translate deterministic evidence rows into evaluation-pair contracts."""
    if result.get("evidence_sets") is not None:
        candidates: List[CorrelationCandidate] = []
        for evidence_set in result.get("evidence_sets") or []:
            candidates.extend(_evaluation_candidates_from_evidence(evidence_set))
        return candidates

    confidence = float((result.get("quality") or {}).get("evidence_quality_score") or 0.0)
    join_plan = result.get("join_plan") or {}
    candidates: List[CorrelationCandidate] = []
    for row in result.get("matched_rows") or []:
        lineage = row.get("lineage") or []
        if len(lineage) != 2:
            continue
        left, right = lineage
        try:
            candidates.append(CorrelationCandidate(
                left=EvidenceReference(
                    source_id=str(left["source_id"]),
                    table_id=str(left.get("table_key") or left.get("table_name")),
                    row_id=str(left["row_id"]),
                    sheet_name=left.get("table_name"),
                    source_label=left.get("source_name"),
                ),
                right=EvidenceReference(
                    source_id=str(right["source_id"]),
                    table_id=str(right.get("table_key") or right.get("table_name")),
                    row_id=str(right["row_id"]),
                    sheet_name=right.get("table_name"),
                    source_label=right.get("source_name"),
                ),
                confidence=confidence,
                join_keys={str(key): str(value) for key, value in (row.get("join_key") or {}).items()},
                evidence=[f"join_plan:{join_plan.get('plan_id', 'unknown')}", row.get("evidence_id", "")],
                correlation_id=row.get("evidence_id"),
            ))
        except (KeyError, TypeError, ValueError):
            # A malformed persisted preview must be visible in its own quality
            # report, but cannot fabricate an evaluation candidate.
            logger.warning("evidence_row_missing_lineage", evidence_id=row.get("evidence_id"))
    return candidates


def _attach_operational_analytics(result: Dict[str, Any]) -> None:
    """Attach bounded statistical diagnostics to already-matched evidence.

    The analytics service explicitly labels every result observational.  It is
    kept separate from joining so a statistical coefficient can never create a
    row match that the deterministic evidence engine did not establish.
    """
    from app.services.operational_analytics import (
        OperationalAnalyticsLimits,
        analyze_evidence_rows,
    )

    limits = OperationalAnalyticsLimits(max_rows=MAX_PREVIEW_ROWS)
    if result.get("evidence_sets") is not None:
        graph_analytics: List[Dict[str, Any]] = []
        for evidence_set in result.get("evidence_sets") or []:
            analysis = analyze_evidence_rows(
                evidence_set.get("matched_rows") or [], limits=limits
            )
            evidence_set["operational_analytics"] = analysis
            graph_analytics.append({
                "plan_id": (evidence_set.get("join_plan") or {}).get("plan_id"),
                "analysis": analysis,
            })
        result["operational_analytics"] = {
            "analysis_type": "pairwise_evidence_graph",
            "edges": graph_analytics,
            "causation": {
                "status": "not_established",
                "causal_confidence": 0.0,
                "safe_interpretation": "Pairwise evidence statistics identify associations for review; they do not establish causation.",
            },
        }
        return
    result["operational_analytics"] = analyze_evidence_rows(
        result.get("matched_rows") or [], limits=limits
    )


async def _execute_evidence_request(
    db: AsyncSession,
    request: EvidencePreviewRequest,
    current_user: User,
    *,
    asynchronous: bool,
    include_operations_source_rows: bool = False,
    report=None,
) -> Dict[str, Any]:
    if report:
        await report(stage="loading_sources", progress=10.0, processed=0, total=len(request.intake_ids))
    sources, manifests = await _load_evidence_sources(
        db,
        request.intake_ids,
        current_user,
        asynchronous=asynchronous,
        table_selection=request.table_selection,
        report=report,
    )
    readable_table_count = _readable_table_count(sources)
    if readable_table_count > settings.CORRELATION_MAX_EVIDENCE_TABLES:
        selection_code = (
            "table_selection_required"
            if not request.table_selection
            else "table_selection_too_broad"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": selection_code,
                "message": (
                    "This request contains %d readable tables, above the %d-table evidence-graph limit. "
                    "Select the operational tables relevant to the question before correlating them."
                    % (readable_table_count, settings.CORRELATION_MAX_EVIDENCE_TABLES)
                ),
                "max_evidence_tables": settings.CORRELATION_MAX_EVIDENCE_TABLES,
                "available_tables": _catalog_from_sources(sources),
                "ingestion_manifests": manifests,
            },
        )
    value_aliases, approved_column_aliases, vocabulary_feedback_ids = _approved_vocabulary_mappings(
        str(current_user.organization_id)
    )
    sources, normalization_summary = _prepare_normalized_sources(
        sources,
        assumed_timezone=request.assumed_timezone,
        requested_mappings=request.schema_mappings,
        approved_column_aliases=approved_column_aliases,
        apply_long_form_normalization=request.apply_long_form_normalization,
    )
    operations_source_rows: List[Dict[str, Any]] = []
    operations_source_scope: Dict[str, Any] = {}
    if include_operations_source_rows:
        operations_source_rows, operations_source_scope = _operations_answer_source_rows(sources)
    if report:
        await report(stage="profiling_join_candidates", progress=45.0, processed=len(sources), total=len(request.intake_ids))

    if request.join_plan and request.join_plans is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either join_plan or join_plans, not both.",
        )
    if request.join_plans is not None and not request.confirm_join_plan:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="join_plans require confirm_join_plan=true.",
        )

    # A user may inspect one selected plan without approving it.  A graph of
    # multiple supplied plans is only treated as confirmed after the explicit
    # confirmation flag; the default multi-source path stays a read-only set of
    # proposed deterministic joins.
    if request.join_plans is not None:
        result = build_evidence_graph(
            sources,
            join_plans=request.join_plans,
            time_bucket_minutes=request.time_bucket_minutes,
            include_weak_keys=request.include_weak_keys,
            max_match_pairs=request.max_match_pairs,
            max_evidence_sets=settings.CORRELATION_MAX_EVIDENCE_RELATIONSHIPS,
            value_aliases=value_aliases,
        )
    elif not request.join_plan and (
        readable_table_count > 2
        # A single workbook/archive is logically a graph of its sheets, even
        # when it contains only one safe pair.  Returning the graph envelope
        # gives the UI a consistent, auditable view of in-workbook links.
        or (len(sources) == 1 and readable_table_count >= 2)
    ):
        result = build_evidence_graph(
            sources,
            time_bucket_minutes=request.time_bucket_minutes,
            include_weak_keys=request.include_weak_keys,
            max_match_pairs=request.max_match_pairs,
            max_evidence_sets=settings.CORRELATION_MAX_EVIDENCE_RELATIONSHIPS,
            value_aliases=value_aliases,
        )
    else:
        selected_plan = dict(request.join_plan) if request.join_plan else None
        if selected_plan is not None and str(selected_plan.get("approval_state") or "").casefold() != "rejected":
            selected_plan["approval_state"] = (
                "confirmed" if request.confirm_join_plan else "proposed"
            )
        result = build_evidence_table(
            sources,
            join_plan=selected_plan,
            time_bucket_minutes=request.time_bucket_minutes,
            include_weak_keys=request.include_weak_keys,
            max_match_pairs=request.max_match_pairs,
            value_aliases=value_aliases,
        )
    result["ingestion_manifests"] = manifests
    result["input_scope"] = {
        "selected_intake_count": len(request.intake_ids),
        "readable_source_count": len(sources),
        "readable_table_count": readable_table_count,
        "selected_table_ref_count": sum(len(refs) for refs in request.table_selection.values()),
        "single_source_multi_table": len(sources) == 1 and readable_table_count >= 2,
        "operations_source_record_count": operations_source_scope.get("retained_source_record_count"),
        "operations_source_records_truncated": bool(operations_source_scope.get("truncated")),
    }
    if include_operations_source_rows:
        # Private, single-request material for the deterministic Operations
        # Lead service. The operations router returns its cited findings rather
        # than this raw row packet.
        result["_operations_source_rows"] = operations_source_rows
        result["_operations_source_scope"] = operations_source_scope
    result["normalization"] = normalization_summary
    result["vocabulary_provenance"] = {
        "approved_feedback_ids": vocabulary_feedback_ids,
        "approved_value_alias_fields": sorted(value_aliases),
        "approved_column_alias_count": len(approved_column_aliases),
    }
    result["candidate_join_plans"] = result.get("candidate_join_plans") or profile_join_candidates(
        sources,
        time_bucket_minutes=request.time_bucket_minutes,
        include_weak_keys=request.include_weak_keys,
        value_aliases=value_aliases,
    )
    # Rollups are generated from normalized source rows rather than pairwise
    # evidence rows. That preserves the source-table metric boundary and keeps
    # a company/file total from being reused as an asset or line total.
    result["entity_rollups"] = build_entity_rollups(sources)
    if request.include_operational_analytics:
        if report:
            await report(stage="computing_operational_statistics", progress=92.0)
        _attach_operational_analytics(result)
    if report:
        await report(stage="building_evidence_table", progress=85.0)
    return _compact_result(result)


@router.get("/capabilities", response_model=EvidenceCapabilitiesResponse)
async def correlation_evidence_capabilities(
    current_user: User = Depends(get_current_active_user),
):
    """Expose the parser and operational contract to the upload UI."""
    return {
        "capabilities": capability_manifest(),
        "limits": {
            "max_upload_bytes": settings.CORRELATION_MAX_UPLOAD_BYTES,
            "sync_max_rows": settings.CORRELATION_SYNC_MAX_ROWS,
            "sync_max_match_pairs": MAX_PREVIEW_MATCH_PAIRS,
            "async_max_rows_per_table": settings.CORRELATION_MAX_ROWS_PER_TABLE,
            "max_evidence_tables_per_request": settings.CORRELATION_MAX_EVIDENCE_TABLES,
            "max_preview_relationships": settings.CORRELATION_MAX_EVIDENCE_RELATIONSHIPS,
        },
        "normalization": {
            "long_form_fields": ["metric_name", "value", "unit"],
            "canonical_dimensions": ["temperature", "length", "mass", "energy", "pressure"],
            "timezone_behavior": "Naive timestamps require an explicit assumed_timezone and are recorded for review.",
        },
        "approval": "Every automatic join preview is proposed; human confirmation is required before it is an operational conclusion.",
    }


@router.post("/connectors/{connector}/plan", response_model=ConnectorPlanResponse)
async def plan_evidence_connector(
    connector: str,
    request: ConnectorPlanRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Create a sanitized, non-networked ingestion plan for an external source.

    This endpoint never opens a database/ERP/historian/stream connection or
    returns a supplied secret.  A deployed worker must later consume the plan
    with an approved credential reference and its own least-privilege policy.
    """
    try:
        return plan_connector_ingestion(
            connector,
            request.configuration,
            entities=request.entities,
            cursor=request.cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/intake/catalog", response_model=EvidenceCatalogResponse)
async def catalog_intake_evidence_tables(
    request: EvidenceCatalogRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """List exact table/archive-child refs for a bounded evidence selection."""

    sources = await _catalog_intake_tables(db, request.intake_ids, current_user)
    return {
        "sources": sources,
        "selection_contract": {
            "field": "table_selection",
            "max_tables_per_source": MAX_TABLE_SELECTIONS_PER_SOURCE,
            "max_tables_per_evidence_graph": settings.CORRELATION_MAX_EVIDENCE_TABLES,
            "guidance": (
                "For a ZIP, choose an archive child path returned as selection_ref. "
                "For a workbook, choose a returned table name."
            ),
        },
    }


@router.post("/intake/preview", response_model=EvidenceResultResponse)
async def preview_intake_evidence(
    request: EvidencePreviewRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a synchronous, bounded common-evidence-table preview."""
    return await _execute_evidence_request(
        db,
        request,
        current_user,
        asynchronous=False,
    )


@router.post("/intake/analytics", response_model=EvidenceResultResponse)
async def analyze_intake_evidence(
    request: EvidencePreviewRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create evidence and deterministic association/lag/anomaly diagnostics."""
    return await _execute_evidence_request(
        db,
        request.model_copy(update={"include_operational_analytics": True}),
        current_user,
        asynchronous=False,
    )


@router.post("/intake/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=EvidenceJobAcceptedResponse)
async def create_intake_evidence_job(
    request: EvidenceJobRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
):
    """Schedule parsing/profile/join work and return a progress URL."""
    job = await correlation_jobs.create(
        "evidence_correlation",
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
        input_summary={"intake_count": len(request.intake_ids)},
    )
    user_id = str(current_user.id)
    org_id = str(current_user.organization_id)

    async def run(report):
        # A BackgroundTask outlives the request-scoped session.  Rehydrate the
        # actor identity only after scoping every DB query explicitly.
        async with AsyncSessionLocal() as job_db:
            actor = type("EvidenceJobActor", (), {
                "id": user_id,
                "organization_id": org_id,
            })()
            return await _execute_evidence_request(
                job_db,
                request,
                actor,
                asynchronous=True,
                report=report,
            )

    background_tasks.add_task(correlation_jobs.run, job["job_id"], run)
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "status_url": f"/api/v1/correlation/evidence/jobs/{job['job_id']}",
        "cancel_url": f"/api/v1/correlation/evidence/jobs/{job['job_id']}",
    }


@router.get("/jobs/{job_id}", response_model=EvidenceJobResponse)
async def get_intake_evidence_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
):
    job = await correlation_jobs.get(str(job_id))
    if (
        job is None
        or job.get("organization_id") != str(current_user.organization_id)
        or job.get("actor_id") != str(current_user.id)
    ):
        raise HTTPException(status_code=404, detail="Correlation job not found")
    return job


@router.delete("/jobs/{job_id}", response_model=EvidenceJobResponse)
async def cancel_intake_evidence_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
):
    job = await correlation_jobs.cancel(
        str(job_id),
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Correlation job not found")
    return job


@router.post("/evaluations/run", response_model=CorrelationEvaluationResponse)
async def run_correlation_evaluation(
    request: EvaluationRunRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Evaluate a known-good fixture and record an observable quality report."""
    case_result = evaluate_correlation_case(
        request.fixture.case,
        request.fixture.observed_matches,
    )
    suite = evaluate_correlation_suite(
        "ad_hoc_evidence_fixture",
        [request.fixture.case],
        {request.fixture.case.case_id: request.fixture.observed_matches},
    )
    report = build_quality_report(
        suite,
        input_quality=request.input_quality,
        thresholds=request.thresholds,
    )
    _quality_monitor.record(report, organization_id=str(current_user.organization_id))
    return {
        "case_result": case_result,
        "suite_report": suite,
        "quality_report": report,
    }


@router.post("/evaluations/evidence", response_model=FreshEvidenceEvaluationResponse)
async def evaluate_fresh_evidence(
    request: EvidenceEvaluationRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Build a current evidence preview, then compare it with a gold fixture.

    This is the operational evaluation loop: a customer-approved case catches
    a new false match or missing match before a changed parser/join policy is
    promoted into automated workflows.
    """
    evidence = await _execute_evidence_request(
        db,
        request.evidence,
        current_user,
        asynchronous=False,
    )
    candidates = _evaluation_candidates_from_evidence(evidence)
    case_result = evaluate_correlation_case(request.case, candidates)
    suite = evaluate_correlation_suite(
        "fresh_evidence_fixture",
        [request.case],
        {request.case.case_id: candidates},
    )
    report = build_quality_report(
        suite,
        input_quality=request.input_quality,
        thresholds=request.thresholds,
    )
    _quality_monitor.record(report, organization_id=str(current_user.organization_id))
    return {
        "evidence": evidence,
        "observed_candidates": candidates,
        "case_result": case_result,
        "suite_report": suite,
        "quality_report": report,
    }


@router.get("/quality/latest", response_model=CorrelationQualityResponse)
async def latest_correlation_quality(
    current_user: User = Depends(get_current_active_user),
):
    return {
        "quality_report": _quality_monitor.latest(
            organization_id=str(current_user.organization_id)
        )
    }


@router.post("/vocabulary", response_model=CustomerVocabularyFeedback)
async def submit_customer_vocabulary(
    feedback: CustomerVocabularyFeedback,
    current_user: User = Depends(get_current_active_user),
):
    """Submit a tenant-scoped mapping that is inert until a reviewer approves it."""
    scoped = feedback.model_copy(update={
        "organization_id": str(current_user.organization_id),
        "submitted_by": str(current_user.id),
        "status": VocabularyFeedbackStatus.PENDING,
        "reviewed_by": None,
        "reviewed_at": None,
    })
    try:
        return _vocabulary.submit(scoped)
    except VocabularyFeedbackError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/vocabulary", response_model=VocabularyListResponse)
async def list_customer_vocabulary(
    review_status: Optional[VocabularyFeedbackStatus] = None,
    current_user: User = Depends(get_current_active_user),
):
    return {
        "items": _vocabulary.list_feedback(
            str(current_user.organization_id),
            status=review_status,
        )
    }


@router.post("/vocabulary/{feedback_id}/review", response_model=CustomerVocabularyFeedback)
async def review_customer_vocabulary(
    feedback_id: str,
    request: VocabularyReviewRequest,
    current_user: User = Depends(get_current_active_user),
):
    existing = _vocabulary.get_feedback(feedback_id)
    if existing is None or existing.organization_id != str(current_user.organization_id):
        raise HTTPException(status_code=404, detail="Vocabulary feedback not found")
    try:
        feedback = _vocabulary.review(
            feedback_id,
            approved=request.approved,
            reviewer_id=str(current_user.id),
            review_note=request.review_note,
        )
    except VocabularyFeedbackNotFound:
        raise HTTPException(status_code=404, detail="Vocabulary feedback not found")
    except VocabularyFeedbackError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return feedback


@router.post("/actions/assess", response_model=ApprovalResult)
async def assess_operational_action(
    request: ActionAssessmentRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Fail closed: assess a proposal only; never execute a side effect."""
    return _approval_policy.assess(request.action, request.policy)


@router.post("/actions/decide", response_model=ApprovalResult)
async def decide_operational_action(
    request: ActionDecisionRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Apply an accountable human decision to a freshly assessed proposal.

    No endpoint in this router dispatches the resulting action.  An integration
    must consume an approved result and still enforce its own domain-specific
    authorization and idempotency checks.
    """
    if request.decision.reviewer_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Reviewer identity must match the authenticated user")
    assessed = _approval_policy.assess(request.action, request.policy)
    try:
        return _approval_policy.apply_human_decision(assessed, request.decision)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
