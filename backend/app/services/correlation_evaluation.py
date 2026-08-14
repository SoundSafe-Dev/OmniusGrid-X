"""Deterministic evaluation, quality monitoring, vocabulary review, and approval.

This module intentionally keeps the evidence engine honest: it does not use an
LLM to decide whether a correlation is correct.  Instead it compares emitted
record pairs against versioned human-curated assertions, records concrete false
matches, and fails closed before an operational action can be executed.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from app.models.correlation_evaluation import (
    ApprovalPolicy,
    ApprovalResult,
    ApprovalStatus,
    AutomatedAction,
    CorrelationCandidate,
    CorrelationEvaluationCase,
    CorrelationEvaluationResult,
    CorrelationEvaluationSuiteReport,
    CorrelationQualityReport,
    CustomerVocabularyFeedback,
    EvaluationIssue,
    EvaluationIssueType,
    HumanApprovalDecision,
    InputDataQualitySnapshot,
    QualityGateThresholds,
    QualityMetric,
    QualityStatus,
    VocabularyFeedbackKind,
    VocabularyFeedbackStatus,
    VocabularyResolution,
)


def _safe_divide(numerator: float, denominator: float, *, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _f1_score(precision: float, recall: float) -> float:
    return _safe_divide(2 * precision * recall, precision + recall)


class DeterministicCorrelationEvaluator:
    """Evaluate emitted evidence pairs without heuristic or model inference.

    Repeated candidate pairs are collapsed deterministically to their greatest
    confidence.  This gives an evaluator a stable result even when a worker
    emits the same correlation more than once while processing chunks.
    """

    def evaluate(
        self,
        case: CorrelationEvaluationCase,
        observed_matches: Iterable[CorrelationCandidate],
    ) -> CorrelationEvaluationResult:
        observed, duplicate_count = self._collapse_candidates(observed_matches)
        expected_matches = {match.pair_key: match for match in case.expected_matches}
        expected_non_matches = {
            non_match.pair_key: non_match for non_match in case.expected_non_matches
        }

        issues: List[EvaluationIssue] = []
        true_positive_count = 0
        false_negative_count = 0
        false_positive_count = 0
        verified_non_match_count = 0
        false_match_count = 0

        for _ in range(duplicate_count):
            issues.append(
                EvaluationIssue(
                    issue_type=EvaluationIssueType.DUPLICATE_CANDIDATE,
                    pair_key="duplicate-candidate",
                    message="The engine emitted the same evidence pair more than once.",
                )
            )

        # Expected positives are assessed against their individual confidence
        # floor.  A low-score hit is a recall failure rather than a false
        # positive: it is the correct pair but not a useful promoted match.
        for pair_key, expected in expected_matches.items():
            candidate = observed.get(pair_key)
            if candidate and candidate.confidence >= expected.minimum_confidence:
                true_positive_count += 1
                continue

            false_negative_count += 1
            if candidate is None:
                issues.append(
                    EvaluationIssue(
                        issue_type=EvaluationIssueType.FALSE_NEGATIVE,
                        pair_key=pair_key,
                        message="Expected evidence pair was not emitted as a match.",
                    )
                )
            else:
                issues.append(
                    EvaluationIssue(
                        issue_type=EvaluationIssueType.BELOW_CONFIDENCE,
                        pair_key=pair_key,
                        confidence=candidate.confidence,
                        message=(
                            "Expected evidence pair was below its minimum confidence "
                            f"of {expected.minimum_confidence:.3f}."
                        ),
                    )
                )

        # Each explicit non-match is a regression guard.  It is particularly
        # important for assets/lines that share a label but belong to different
        # facilities, shifts, or time windows.
        for pair_key, expected in expected_non_matches.items():
            candidate = observed.get(pair_key)
            if candidate is None or candidate.confidence <= expected.maximum_confidence:
                verified_non_match_count += 1
                continue
            false_match_count += 1
            false_positive_count += 1
            issues.append(
                EvaluationIssue(
                    issue_type=EvaluationIssueType.FALSE_MATCH,
                    pair_key=pair_key,
                    confidence=candidate.confidence,
                    message=(
                        "Expected non-match was promoted above its maximum confidence "
                        f"of {expected.maximum_confidence:.3f}."
                    ),
                )
            )

        # A candidate outside the curated positive/negative assertions is also
        # a false positive.  This makes fixtures sensitive to accidental broad
        # joins, not only to known bad-pair regressions.
        for pair_key, candidate in observed.items():
            if pair_key in expected_matches or pair_key in expected_non_matches:
                continue
            false_positive_count += 1
            issues.append(
                EvaluationIssue(
                    issue_type=EvaluationIssueType.FALSE_POSITIVE,
                    pair_key=pair_key,
                    confidence=candidate.confidence,
                    message="Engine emitted an evidence pair absent from the gold standard.",
                )
            )

        observed_match_count = len(observed)
        precision = _safe_divide(
            true_positive_count,
            true_positive_count + false_positive_count,
            # A case with no positives and no predictions is precise by
            # convention; its recall is also 1.0 below. This makes negative-only
            # false-match regression cases usable as standalone tests.
            default=1.0,
        )
        recall = _safe_divide(
            true_positive_count,
            len(expected_matches),
            default=1.0,
        )
        f1_score = _f1_score(precision, recall)

        # Duplicate emissions are a quality finding but do not turn a valid
        # match into a failed gold-standard result. The quality report exposes
        # them separately so streaming/chunking paths can be fixed without
        # obscuring matching accuracy.
        passed = false_positive_count == 0 and false_negative_count == 0
        return CorrelationEvaluationResult(
            case_id=case.case_id,
            expected_match_count=len(expected_matches),
            expected_non_match_count=len(expected_non_matches),
            observed_match_count=observed_match_count,
            true_positive_count=true_positive_count,
            false_positive_count=false_positive_count,
            false_negative_count=false_negative_count,
            verified_non_match_count=verified_non_match_count,
            false_match_count=false_match_count,
            duplicate_candidate_count=duplicate_count,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            passed=passed,
            issues=issues,
        )

    @staticmethod
    def _collapse_candidates(
        observed_matches: Iterable[CorrelationCandidate],
    ) -> tuple[Dict[str, CorrelationCandidate], int]:
        collapsed: Dict[str, CorrelationCandidate] = {}
        duplicate_count = 0
        for candidate in observed_matches:
            # A candidate explicitly marked not-a-match is retained in a UI
            # preview but must not count as an emitted correlation in a quality
            # evaluation.
            if not candidate.is_match:
                continue
            pair_key = candidate.pair_key
            current = collapsed.get(pair_key)
            if current is None:
                collapsed[pair_key] = candidate
                continue
            duplicate_count += 1
            # Highest confidence wins; equal confidence keeps the first emitted
            # candidate, making the result stable without depending on object
            # IDs or timestamps.
            if candidate.confidence > current.confidence:
                collapsed[pair_key] = candidate
        return collapsed, duplicate_count


def evaluate_correlation_case(
    case: CorrelationEvaluationCase,
    observed_matches: Iterable[CorrelationCandidate],
) -> CorrelationEvaluationResult:
    """Convenience entry point for a single known-good case."""
    return DeterministicCorrelationEvaluator().evaluate(case, observed_matches)


def evaluate_correlation_suite(
    suite_name: str,
    cases: Sequence[CorrelationEvaluationCase],
    observations_by_case: Mapping[str, Iterable[CorrelationCandidate]],
) -> CorrelationEvaluationSuiteReport:
    """Run a stable set of gold-standard cases and aggregate its quality data."""
    evaluator = DeterministicCorrelationEvaluator()
    results = [
        evaluator.evaluate(case, observations_by_case.get(case.case_id, []))
        for case in cases
    ]
    expected_match_count = sum(result.expected_match_count for result in results)
    expected_non_match_count = sum(result.expected_non_match_count for result in results)
    observed_match_count = sum(result.observed_match_count for result in results)
    true_positive_count = sum(result.true_positive_count for result in results)
    false_positive_count = sum(result.false_positive_count for result in results)
    false_negative_count = sum(result.false_negative_count for result in results)
    verified_non_match_count = sum(result.verified_non_match_count for result in results)
    false_match_count = sum(result.false_match_count for result in results)
    duplicate_candidate_count = sum(result.duplicate_candidate_count for result in results)
    precision = _safe_divide(
        true_positive_count,
        true_positive_count + false_positive_count,
        default=1.0,
    )
    recall = _safe_divide(true_positive_count, expected_match_count, default=1.0)
    return CorrelationEvaluationSuiteReport(
        suite_name=suite_name,
        case_results=results,
        expected_match_count=expected_match_count,
        expected_non_match_count=expected_non_match_count,
        observed_match_count=observed_match_count,
        true_positive_count=true_positive_count,
        false_positive_count=false_positive_count,
        false_negative_count=false_negative_count,
        verified_non_match_count=verified_non_match_count,
        false_match_count=false_match_count,
        duplicate_candidate_count=duplicate_candidate_count,
        precision=precision,
        recall=recall,
        f1_score=_f1_score(precision, recall),
        passed=all(result.passed for result in results),
    )


class CorrelationQualityMonitor:
    """Build and retain bounded quality reports for dashboarding or alerting.

    This in-memory implementation is intentionally dependency-free. A worker
    can persist its ``CorrelationQualityReport.model_dump(mode='json')`` to the
    audit/event store without changing the deterministic scoring semantics.
    """

    def __init__(self, max_history: int = 100) -> None:
        if max_history < 1:
            raise ValueError("max_history must be at least 1")
        self._max_history = max_history
        self._history: Dict[str, List[CorrelationQualityReport]] = {}
        self._lock = threading.RLock()

    def build_report(
        self,
        suite_report: CorrelationEvaluationSuiteReport,
        *,
        input_quality: Optional[InputDataQualitySnapshot] = None,
        thresholds: Optional[QualityGateThresholds] = None,
    ) -> CorrelationQualityReport:
        thresholds = thresholds or QualityGateThresholds()
        false_match_denominator = (
            suite_report.false_match_count + suite_report.verified_non_match_count
        )
        # A suite with no declared negative checks has no demonstrated
        # false-match protection. Treat it as a failing rate rather than hiding
        # the gap behind a benign zero.
        false_match_rate = _safe_divide(
            suite_report.false_match_count,
            false_match_denominator,
            default=1.0,
        )
        duplicate_candidate_rate = _safe_divide(
            suite_report.duplicate_candidate_count,
            suite_report.observed_match_count + suite_report.duplicate_candidate_count,
            default=0.0,
        )

        metrics = [
            QualityMetric(
                name="precision",
                value=suite_report.precision,
                threshold=thresholds.minimum_precision,
                passed=suite_report.precision >= thresholds.minimum_precision,
            ),
            QualityMetric(
                name="recall",
                value=suite_report.recall,
                threshold=thresholds.minimum_recall,
                passed=suite_report.recall >= thresholds.minimum_recall,
            ),
            QualityMetric(
                name="f1_score",
                value=suite_report.f1_score,
                threshold=thresholds.minimum_f1_score,
                passed=suite_report.f1_score >= thresholds.minimum_f1_score,
            ),
            QualityMetric(
                name="false_match_rate",
                value=false_match_rate,
                threshold=thresholds.maximum_false_match_rate,
                passed=false_match_rate <= thresholds.maximum_false_match_rate,
                detail=(
                    "No expected non-match checks were supplied."
                    if false_match_denominator == 0
                    else None
                ),
            ),
            QualityMetric(
                name="duplicate_candidate_rate",
                value=duplicate_candidate_rate,
                threshold=thresholds.maximum_duplicate_candidate_rate,
                passed=(
                    duplicate_candidate_rate
                    <= thresholds.maximum_duplicate_candidate_rate
                ),
            ),
        ]
        if input_quality is not None:
            metrics.extend(
                [
                    QualityMetric(
                        name="input_quality_score",
                        value=input_quality.data_quality_score,
                        threshold=thresholds.minimum_input_quality_score,
                        passed=(
                            input_quality.data_quality_score
                            >= thresholds.minimum_input_quality_score
                        ),
                    ),
                    QualityMetric(
                        name="lineage_coverage",
                        value=input_quality.lineage_coverage,
                        threshold=thresholds.minimum_lineage_coverage,
                        passed=(
                            input_quality.lineage_coverage
                            >= thresholds.minimum_lineage_coverage
                        ),
                    ),
                ]
            )

        failures = [
            f"{metric.name}={metric.value:.3f} did not meet its quality gate "
            f"({metric.threshold:.3f})"
            for metric in metrics
            if not metric.passed
        ]
        if not suite_report.passed:
            failures.append("At least one known-good evaluation case failed.")

        passed = suite_report.passed and not failures
        status = QualityStatus.HEALTHY if passed else QualityStatus.FAILING
        return CorrelationQualityReport(
            status=status,
            passed=passed,
            metrics=metrics,
            false_match_rate=false_match_rate,
            duplicate_candidate_rate=duplicate_candidate_rate,
            evaluation_case_count=len(suite_report.case_results),
            input_quality=input_quality,
            failures=failures,
        )

    def record(
        self,
        report: CorrelationQualityReport,
        *,
        organization_id: Optional[str] = None,
    ) -> CorrelationQualityReport:
        """Append a report within one tenant's bounded in-process history."""
        scope = str(organization_id or "__global__")
        with self._lock:
            history = self._history.setdefault(scope, [])
            history.append(report)
            if len(history) > self._max_history:
                del history[: len(history) - self._max_history]
        return report

    def latest(self, *, organization_id: Optional[str] = None) -> Optional[CorrelationQualityReport]:
        scope = str(organization_id or "__global__")
        with self._lock:
            history = self._history.get(scope) or []
            return history[-1] if history else None

    def history(self, *, organization_id: Optional[str] = None) -> List[CorrelationQualityReport]:
        scope = str(organization_id or "__global__")
        with self._lock:
            return list(self._history.get(scope) or [])


def build_quality_report(
    suite_report: CorrelationEvaluationSuiteReport,
    *,
    input_quality: Optional[InputDataQualitySnapshot] = None,
    thresholds: Optional[QualityGateThresholds] = None,
) -> CorrelationQualityReport:
    """Create a one-off quality report without retaining process-local history."""
    return CorrelationQualityMonitor().build_report(
        suite_report,
        input_quality=input_quality,
        thresholds=thresholds,
    )


def normalize_vocabulary_term(value: str) -> str:
    """Normalize customer terms so harmless spelling differences map reliably."""
    normalized = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    normalized = re.sub(r"[\s_\-]+", " ", normalized)
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _vocabulary_scope_key(
    organization_id: str,
    kind: VocabularyFeedbackKind,
    raw_term: str,
    field_name: Optional[str],
) -> tuple[str, VocabularyFeedbackKind, str, str]:
    return (
        organization_id,
        kind,
        normalize_vocabulary_term(raw_term),
        normalize_vocabulary_term(field_name or ""),
    )


class VocabularyFeedbackError(ValueError):
    """Base error for explicit customer-vocabulary review failures."""


class VocabularyFeedbackNotFound(VocabularyFeedbackError):
    pass


class VocabularyConflictError(VocabularyFeedbackError):
    pass


class CustomerVocabularyService:
    """Human-reviewed customer vocabulary mappings.

    Pending mappings are deliberately invisible to ``resolve``.  This avoids a
    single typo or a model suggestion silently altering the entity-resolution
    behavior for an entire customer.
    """

    def __init__(self) -> None:
        self._feedback_by_id: Dict[str, CustomerVocabularyFeedback] = {}
        self._approved_by_scope: Dict[
            tuple[str, VocabularyFeedbackKind, str, str], CustomerVocabularyFeedback
        ] = {}
        self._lock = threading.RLock()

    def submit(self, feedback: CustomerVocabularyFeedback) -> CustomerVocabularyFeedback:
        """Store proposed feedback in the pending state.

        Callers may not inject an already-approved mapping; approval needs a
        separate accountable reviewer action.
        """
        if feedback.status is not VocabularyFeedbackStatus.PENDING:
            raise VocabularyFeedbackError("New vocabulary feedback must start as pending")
        with self._lock:
            if feedback.feedback_id in self._feedback_by_id:
                raise VocabularyFeedbackError(
                    f"Vocabulary feedback '{feedback.feedback_id}' already exists"
                )
            self._feedback_by_id[feedback.feedback_id] = feedback
        return feedback

    def get_feedback(self, feedback_id: str) -> Optional[CustomerVocabularyFeedback]:
        """Return a feedback record for an authorization check before review."""
        with self._lock:
            return self._feedback_by_id.get(feedback_id)

    def review(
        self,
        feedback_id: str,
        *,
        approved: bool,
        reviewer_id: str,
        review_note: Optional[str] = None,
    ) -> CustomerVocabularyFeedback:
        """Approve/reject a mapping and guard against ambiguous approved aliases."""
        if not reviewer_id or not reviewer_id.strip():
            raise VocabularyFeedbackError("reviewer_id is required for vocabulary review")
        with self._lock:
            feedback = self._feedback_by_id.get(feedback_id)
            if feedback is None:
                raise VocabularyFeedbackNotFound(
                    f"Vocabulary feedback '{feedback_id}' was not found"
                )
            if feedback.status is not VocabularyFeedbackStatus.PENDING:
                raise VocabularyFeedbackError(
                    f"Vocabulary feedback '{feedback_id}' has already been reviewed"
                )

            if approved:
                scope_key = _vocabulary_scope_key(
                    feedback.organization_id,
                    feedback.kind,
                    feedback.raw_term,
                    feedback.field_name,
                )
                existing = self._approved_by_scope.get(scope_key)
                if existing and (
                    normalize_vocabulary_term(existing.canonical_term)
                    != normalize_vocabulary_term(feedback.canonical_term)
                ):
                    raise VocabularyConflictError(
                        "An approved mapping already exists for this organization, term, "
                        "kind, and field. Reject or retire it before changing the canonical term."
                    )

            updated = feedback.model_copy(
                update={
                    "status": (
                        VocabularyFeedbackStatus.APPROVED
                        if approved
                        else VocabularyFeedbackStatus.REJECTED
                    ),
                    "reviewed_by": reviewer_id,
                    "review_note": review_note,
                    "reviewed_at": datetime.now(timezone.utc),
                }
            )
            self._feedback_by_id[feedback_id] = updated
            if approved:
                self._approved_by_scope[
                    _vocabulary_scope_key(
                        updated.organization_id,
                        updated.kind,
                        updated.raw_term,
                        updated.field_name,
                    )
                ] = updated
            return updated

    def resolve(
        self,
        organization_id: str,
        raw_term: str,
        *,
        kind: VocabularyFeedbackKind,
        field_name: Optional[str] = None,
    ) -> Optional[VocabularyResolution]:
        """Return only an approved mapping that exactly matches this customer scope."""
        scope_key = _vocabulary_scope_key(organization_id, kind, raw_term, field_name)
        with self._lock:
            feedback = self._approved_by_scope.get(scope_key)
        if feedback is None:
            return None
        return VocabularyResolution(
            raw_term=raw_term,
            canonical_term=feedback.canonical_term,
            kind=feedback.kind,
            field_name=feedback.field_name,
            feedback_id=feedback.feedback_id,
        )

    def list_feedback(
        self,
        organization_id: str,
        *,
        status: Optional[VocabularyFeedbackStatus] = None,
    ) -> List[CustomerVocabularyFeedback]:
        with self._lock:
            records = [
                record
                for record in self._feedback_by_id.values()
                if record.organization_id == organization_id
                and (status is None or record.status is status)
            ]
        return sorted(records, key=lambda record: (record.created_at, record.feedback_id))


class ApprovalPolicyService:
    """Apply a fail-closed approval policy before any external side effect.

    A result is a decision record, not an executor.  Calling code must only
    dispatch an action if ``result.may_execute`` is true and must persist the
    result alongside the action's evidence/provenance.
    """

    def assess(
        self,
        action: AutomatedAction,
        policy: Optional[ApprovalPolicy] = None,
    ) -> ApprovalResult:
        policy = policy or ApprovalPolicy()
        reasons: List[str] = []

        # The default and the action-level flag both force human review. This
        # remains true regardless of model confidence or severity.
        if policy.require_human_approval or action.requires_human_approval:
            reasons.append("Human approval is required by policy or by the proposed action.")
            return self._pending(action, policy, reasons)

        # Explicit automatic execution is rare and requires every safety gate.
        if not policy.auto_execute_enabled:
            reasons.append("Automatic execution is disabled by policy.")
            return self._pending(action, policy, reasons)
        if action.action_type not in set(policy.allowed_auto_action_types):
            reasons.append("Action type is not allow-listed for automatic execution.")
            return self._blocked(action, policy, reasons)
        if action.correlation_confidence < policy.minimum_correlation_confidence:
            reasons.append("Correlation confidence is below the automatic-action threshold.")
            return self._pending(action, policy, reasons)
        if action.data_quality_score < policy.minimum_data_quality_score:
            reasons.append("Data quality score is below the automatic-action threshold.")
            return self._pending(action, policy, reasons)
        if action.risk_score > policy.maximum_auto_risk_score:
            reasons.append("Action risk score exceeds the automatic-action threshold.")
            return self._pending(action, policy, reasons)
        if policy.require_idempotent_action and not action.idempotent:
            reasons.append("Only idempotent actions are eligible for automatic execution.")
            return self._pending(action, policy, reasons)

        return ApprovalResult(
            action_id=action.action_id,
            policy_id=policy.policy_id,
            status=ApprovalStatus.AUTO_APPROVED,
            may_execute=True,
            requires_human_approval=False,
            reasons=["All explicit automatic-action safety gates passed."],
        )

    def apply_human_decision(
        self,
        result: ApprovalResult,
        decision: HumanApprovalDecision,
    ) -> ApprovalResult:
        """Apply an accountable reviewer decision to a pending result only."""
        if result.action_id != decision.action_id:
            raise ValueError("Human approval decision does not match the proposed action")
        if result.status is not ApprovalStatus.PENDING_APPROVAL:
            raise ValueError("Only pending approval results can receive a human decision")
        if not decision.reviewer_id.strip():
            raise ValueError("Human approval requires a non-blank reviewer_id")
        if decision.approved:
            return result.model_copy(
                update={
                    "status": ApprovalStatus.APPROVED,
                    "may_execute": True,
                    "requires_human_approval": False,
                    "reviewer_id": decision.reviewer_id,
                    "decided_at": decision.decided_at,
                    "reasons": [*result.reasons, decision.reason or "Approved by human reviewer."],
                }
            )
        return result.model_copy(
            update={
                "status": ApprovalStatus.REJECTED,
                "may_execute": False,
                "requires_human_approval": False,
                "reviewer_id": decision.reviewer_id,
                "decided_at": decision.decided_at,
                "reasons": [*result.reasons, decision.reason or "Rejected by human reviewer."],
            }
        )

    @staticmethod
    def _pending(
        action: AutomatedAction,
        policy: ApprovalPolicy,
        reasons: List[str],
    ) -> ApprovalResult:
        return ApprovalResult(
            action_id=action.action_id,
            policy_id=policy.policy_id,
            status=ApprovalStatus.PENDING_APPROVAL,
            may_execute=False,
            requires_human_approval=True,
            reasons=reasons,
        )

    @staticmethod
    def _blocked(
        action: AutomatedAction,
        policy: ApprovalPolicy,
        reasons: List[str],
    ) -> ApprovalResult:
        return ApprovalResult(
            action_id=action.action_id,
            policy_id=policy.policy_id,
            status=ApprovalStatus.BLOCKED,
            may_execute=False,
            requires_human_approval=True,
            reasons=reasons,
        )


def assess_action_approval(
    action: AutomatedAction,
    policy: Optional[ApprovalPolicy] = None,
) -> ApprovalResult:
    """Convenience entry point for policy assessment."""
    return ApprovalPolicyService().assess(action, policy)
