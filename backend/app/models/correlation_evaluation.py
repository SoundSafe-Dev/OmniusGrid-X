"""Typed contracts for correlation evaluation, quality, and approval.

The correlation engine must be able to explain *why* two records were linked
and prove that the link is correct.  These models intentionally do not depend
on a database table or a particular file format: a CSV row, an Excel cell
range, a document section, and a historian event can all be represented by an
``EvidenceReference``.

Keeping the contracts here makes the deterministic evaluator usable in local
tests, asynchronous workers, and future API endpoints without duplicating the
definitions of a match, a gold-standard assertion, or an approval decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    """Return an aware UTC timestamp (kept as a factory for easy testing)."""
    return datetime.now(timezone.utc)


class EvidenceReference(BaseModel):
    """Stable lineage for one normalized source record.

    ``source_id`` should identify the uploaded file, connector run, or stream;
    ``table_id`` identifies its sheet/table/topic; and ``row_id`` identifies a
    stable source row.  Together they are deliberately enough to reproduce a
    correlation without retaining every raw value in an evaluation fixture.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    table_id: str = Field(min_length=1)
    row_id: str = Field(min_length=1)
    sheet_name: Optional[str] = None
    source_label: Optional[str] = None

    @property
    def stable_id(self) -> str:
        """A delimiter-safe identity used to compare unordered match pairs."""
        # JSON-style escaping avoids collisions such as ("a:b", "c") and
        # ("a", "b:c") while remaining human-readable in evaluation reports.
        import json

        return json.dumps(
            [self.source_id, self.table_id, self.row_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )


def canonical_pair_key(left: EvidenceReference, right: EvidenceReference) -> str:
    """Create a deterministic, order-independent key for an evidence pair."""
    if left.stable_id == right.stable_id:
        raise ValueError("A correlation cannot link an evidence record to itself")
    import json

    # Encode the two already-stable references as an array rather than joining
    # them with a delimiter.  Source labels are user-controlled and could
    # otherwise contain a delimiter-looking sequence.
    return json.dumps(
        sorted((left.stable_id, right.stable_id)),
        ensure_ascii=False,
        separators=(",", ":"),
    )


class CorrelationCandidate(BaseModel):
    """One correlation-engine result together with the evidence that supports it."""

    model_config = ConfigDict(extra="forbid")

    left: EvidenceReference
    right: EvidenceReference
    confidence: float = Field(ge=0.0, le=1.0)
    is_match: bool = True
    join_keys: Dict[str, str] = Field(default_factory=dict)
    evidence: List[str] = Field(default_factory=list)
    correlation_id: Optional[str] = None

    @model_validator(mode="after")
    def _different_references(self) -> "CorrelationCandidate":
        canonical_pair_key(self.left, self.right)
        return self

    @property
    def pair_key(self) -> str:
        return canonical_pair_key(self.left, self.right)


class ExpectedMatch(BaseModel):
    """A gold-standard match that the engine must return above a confidence floor."""

    model_config = ConfigDict(extra="forbid")

    left: EvidenceReference
    right: EvidenceReference
    minimum_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    note: Optional[str] = None

    @model_validator(mode="after")
    def _different_references(self) -> "ExpectedMatch":
        canonical_pair_key(self.left, self.right)
        return self

    @property
    def pair_key(self) -> str:
        return canonical_pair_key(self.left, self.right)


class ExpectedNonMatch(BaseModel):
    """A pair which must not be treated as a correlation.

    ``maximum_confidence`` permits evaluation fixtures to include low-score
    candidate pairs for calibration testing while still flagging any candidate
    the engine promotes above the stated threshold.
    """

    model_config = ConfigDict(extra="forbid")

    left: EvidenceReference
    right: EvidenceReference
    maximum_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    note: Optional[str] = None

    @model_validator(mode="after")
    def _different_references(self) -> "ExpectedNonMatch":
        canonical_pair_key(self.left, self.right)
        return self

    @property
    def pair_key(self) -> str:
        return canonical_pair_key(self.left, self.right)


class CorrelationEvaluationCase(BaseModel):
    """Versioned known-good assertions for one multi-source correlation case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: Optional[str] = None
    expected_matches: List[ExpectedMatch] = Field(default_factory=list)
    expected_non_matches: List[ExpectedNonMatch] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    version: str = "1"

    @model_validator(mode="after")
    def _assertions_are_unambiguous(self) -> "CorrelationEvaluationCase":
        match_keys = [item.pair_key for item in self.expected_matches]
        non_match_keys = [item.pair_key for item in self.expected_non_matches]
        if len(set(match_keys)) != len(match_keys):
            raise ValueError("expected_matches cannot contain duplicate evidence pairs")
        if len(set(non_match_keys)) != len(non_match_keys):
            raise ValueError("expected_non_matches cannot contain duplicate evidence pairs")
        overlap = set(match_keys).intersection(non_match_keys)
        if overlap:
            raise ValueError(
                "An evidence pair cannot be both an expected match and an expected non-match"
            )
        return self


class CorrelationEvaluationFixture(BaseModel):
    """Portable fixture format containing gold assertions and engine output."""

    model_config = ConfigDict(extra="forbid")

    case: CorrelationEvaluationCase
    observed_matches: List[CorrelationCandidate] = Field(default_factory=list)


class EvaluationIssueType(str, Enum):
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"
    FALSE_MATCH = "false_match"
    BELOW_CONFIDENCE = "below_confidence"
    DUPLICATE_CANDIDATE = "duplicate_candidate"


class EvaluationIssue(BaseModel):
    """A machine-readable finding emitted by deterministic evaluation."""

    model_config = ConfigDict(extra="forbid")

    issue_type: EvaluationIssueType
    pair_key: str
    message: str
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class CorrelationEvaluationResult(BaseModel):
    """Per-case precision/recall result, including concrete failures to inspect."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    expected_match_count: int = Field(ge=0)
    expected_non_match_count: int = Field(ge=0)
    observed_match_count: int = Field(ge=0)
    true_positive_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    verified_non_match_count: int = Field(ge=0)
    false_match_count: int = Field(ge=0)
    duplicate_candidate_count: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1_score: float = Field(ge=0.0, le=1.0)
    passed: bool
    issues: List[EvaluationIssue] = Field(default_factory=list)


class CorrelationEvaluationSuiteReport(BaseModel):
    """Aggregate result for a versioned set of known-good evaluation cases."""

    model_config = ConfigDict(extra="forbid")

    suite_name: str = Field(min_length=1)
    generated_at: datetime = Field(default_factory=utc_now)
    case_results: List[CorrelationEvaluationResult] = Field(default_factory=list)
    expected_match_count: int = Field(ge=0)
    expected_non_match_count: int = Field(ge=0)
    observed_match_count: int = Field(ge=0)
    true_positive_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    verified_non_match_count: int = Field(ge=0)
    false_match_count: int = Field(ge=0)
    duplicate_candidate_count: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1_score: float = Field(ge=0.0, le=1.0)
    passed: bool


class InputDataQualitySnapshot(BaseModel):
    """Format-neutral data-quality counters collected during ingestion.

    A caller can increment these while parsing rows/chunks without holding all
    data in memory.  The quality monitor derives a conservative score from the
    counters and makes lineage coverage visible alongside match quality.
    """

    model_config = ConfigDict(extra="forbid")

    total_records: int = Field(ge=0)
    lineage_complete_records: int = Field(ge=0)
    records_missing_join_key: int = Field(default=0, ge=0)
    type_validation_failures: int = Field(default=0, ge=0)
    timestamp_normalization_failures: int = Field(default=0, ge=0)
    unit_normalization_failures: int = Field(default=0, ge=0)
    duplicate_record_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _counts_do_not_exceed_total(self) -> "InputDataQualitySnapshot":
        if self.lineage_complete_records > self.total_records:
            raise ValueError("lineage_complete_records cannot exceed total_records")
        for name in (
            "records_missing_join_key",
            "type_validation_failures",
            "timestamp_normalization_failures",
            "unit_normalization_failures",
            "duplicate_record_count",
        ):
            if getattr(self, name) > self.total_records:
                raise ValueError(f"{name} cannot exceed total_records")
        return self

    @property
    def lineage_coverage(self) -> float:
        return self.lineage_complete_records / self.total_records if self.total_records else 0.0

    @property
    def data_quality_score(self) -> float:
        """A conservative 0..1 score that penalizes each observed issue type."""
        if not self.total_records:
            return 0.0
        defect_rate = (
            self.records_missing_join_key
            + self.type_validation_failures
            + self.timestamp_normalization_failures
            + self.unit_normalization_failures
            + self.duplicate_record_count
        ) / (5 * self.total_records)
        # Half of the score is lineage quality, which makes it impossible for a
        # perfectly typed but untraceable input to appear healthy.
        return max(0.0, min(1.0, 0.5 * self.lineage_coverage + 0.5 * (1 - defect_rate)))


class QualityGateThresholds(BaseModel):
    """Explicit gates used for quality monitoring and automated-action policy."""

    model_config = ConfigDict(extra="forbid")

    minimum_precision: float = Field(default=0.95, ge=0.0, le=1.0)
    minimum_recall: float = Field(default=0.95, ge=0.0, le=1.0)
    minimum_f1_score: float = Field(default=0.95, ge=0.0, le=1.0)
    minimum_input_quality_score: float = Field(default=0.85, ge=0.0, le=1.0)
    minimum_lineage_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    maximum_false_match_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    maximum_duplicate_candidate_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class QualityStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    FAILING = "failing"


class QualityMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    passed: bool
    detail: Optional[str] = None


class CorrelationQualityReport(BaseModel):
    """Quality gate report suitable for dashboards, audit logs, and CI."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime = Field(default_factory=utc_now)
    status: QualityStatus
    passed: bool
    metrics: List[QualityMetric]
    false_match_rate: float = Field(ge=0.0, le=1.0)
    duplicate_candidate_rate: float = Field(ge=0.0, le=1.0)
    evaluation_case_count: int = Field(ge=0)
    input_quality: Optional[InputDataQualitySnapshot] = None
    failures: List[str] = Field(default_factory=list)


class VocabularyFeedbackStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class VocabularyFeedbackKind(str, Enum):
    ENTITY_ALIAS = "entity_alias"
    COLUMN_ALIAS = "column_alias"
    UNIT_ALIAS = "unit_alias"
    VALUE_ALIAS = "value_alias"


class CustomerVocabularyFeedback(BaseModel):
    """A customer-proposed mapping that remains inactive until human review."""

    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(default_factory=lambda: str(uuid4()))
    organization_id: str = Field(min_length=1)
    raw_term: str = Field(min_length=1)
    canonical_term: str = Field(min_length=1)
    kind: VocabularyFeedbackKind
    field_name: Optional[str] = None
    submitted_by: Optional[str] = None
    note: Optional[str] = None
    status: VocabularyFeedbackStatus = VocabularyFeedbackStatus.PENDING
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    reviewed_at: Optional[datetime] = None


class VocabularyResolution(BaseModel):
    """An approved, traceable vocabulary mapping returned to a mapper."""

    model_config = ConfigDict(extra="forbid")

    raw_term: str
    canonical_term: str
    kind: VocabularyFeedbackKind
    field_name: Optional[str] = None
    feedback_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ApprovalStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    AUTO_APPROVED = "auto_approved"


class AutomatedAction(BaseModel):
    """A proposed operational action; it is never an execution command itself."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(default_factory=lambda: str(uuid4()))
    action_type: str = Field(min_length=1)
    correlation_id: Optional[str] = None
    correlation_confidence: float = Field(ge=0.0, le=1.0)
    data_quality_score: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=100.0)
    idempotent: bool = False
    requires_human_approval: bool = True
    payload: Dict[str, Any] = Field(default_factory=dict)


class ApprovalPolicy(BaseModel):
    """Fail-closed policy for promotion of a proposed automated action."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = "default-human-review"
    require_human_approval: bool = True
    # Automatic execution is opt-in and has no allow-list by default.
    auto_execute_enabled: bool = False
    allowed_auto_action_types: List[str] = Field(default_factory=list)
    minimum_correlation_confidence: float = Field(default=0.98, ge=0.0, le=1.0)
    minimum_data_quality_score: float = Field(default=0.90, ge=0.0, le=1.0)
    maximum_auto_risk_score: float = Field(default=10.0, ge=0.0, le=100.0)
    require_idempotent_action: bool = True


class HumanApprovalDecision(BaseModel):
    """Immutable input from the accountable human reviewer."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    approved: bool
    reviewer_id: str = Field(min_length=1)
    reason: Optional[str] = None
    decided_at: datetime = Field(default_factory=utc_now)


class ApprovalResult(BaseModel):
    """Policy outcome. Only ``APPROVED``/``AUTO_APPROVED`` may be executed."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    policy_id: str
    status: ApprovalStatus
    may_execute: bool
    requires_human_approval: bool
    reasons: List[str] = Field(default_factory=list)
    reviewer_id: Optional[str] = None
    decided_at: Optional[datetime] = None


# Semantic aliases make the public contract easy to discover without
# duplicating model definitions.  Existing callers can use either terminology.
KnownGoodEvaluationCase = CorrelationEvaluationCase
ExpectedFalseMatch = ExpectedNonMatch
HumanApprovalPolicy = ApprovalPolicy
