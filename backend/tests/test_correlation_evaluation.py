"""Unit coverage for deterministic correlation evaluation and safety controls."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.correlation_evaluation import (
    ApprovalPolicy,
    ApprovalStatus,
    AutomatedAction,
    CorrelationCandidate,
    CorrelationEvaluationFixture,
    CustomerVocabularyFeedback,
    EvidenceReference,
    ExpectedNonMatch,
    HumanApprovalDecision,
    InputDataQualitySnapshot,
    QualityGateThresholds,
    VocabularyFeedbackKind,
    VocabularyFeedbackStatus,
)
from app.services.correlation_evaluation import (
    ApprovalPolicyService,
    CorrelationQualityMonitor,
    CustomerVocabularyService,
    VocabularyConflictError,
    evaluate_correlation_case,
    evaluate_correlation_suite,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "correlation_evaluation"
    / "known_good_asset_facility.json"
)


def _load_fixture() -> CorrelationEvaluationFixture:
    return CorrelationEvaluationFixture.model_validate_json(FIXTURE_PATH.read_text())


def _reference(source: str, row: str) -> EvidenceReference:
    return EvidenceReference(source_id=source, table_id="Sheet1", row_id=row)


def test_known_good_multi_file_fixture_passes_and_keeps_lineage():
    fixture = _load_fixture()

    result = evaluate_correlation_case(fixture.case, fixture.observed_matches)

    assert result.passed is True
    assert result.true_positive_count == 1
    assert result.verified_non_match_count == 1
    assert result.false_match_count == 0
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert fixture.observed_matches[0].left.source_id == "production-january.xlsx"
    assert fixture.observed_matches[0].left.table_id == "Production"
    assert fixture.observed_matches[0].left.row_id == "12"


def test_evaluator_flags_promoted_expected_non_match_as_false_match():
    fixture = _load_fixture()
    bad_candidate = fixture.observed_matches[1].model_copy(update={"confidence": 0.88})

    result = evaluate_correlation_case(
        fixture.case,
        [fixture.observed_matches[0], bad_candidate],
    )

    assert result.passed is False
    assert result.false_match_count == 1
    assert result.false_positive_count == 1
    assert any(issue.issue_type.value == "false_match" for issue in result.issues)


def test_evaluator_flags_unexpected_pair_and_collapses_duplicate_to_highest_score():
    fixture = _load_fixture()
    extra = CorrelationCandidate(
        left=_reference("other.xlsx", "3"),
        right=_reference("maintenance-january.xlsx", "5"),
        confidence=0.98,
    )
    duplicate_low = fixture.observed_matches[0].model_copy(update={"confidence": 0.82})

    result = evaluate_correlation_case(
        fixture.case,
        [fixture.observed_matches[0], duplicate_low, extra],
    )

    assert result.passed is False
    assert result.duplicate_candidate_count == 1
    assert result.true_positive_count == 1
    assert result.false_positive_count == 1
    assert any(issue.issue_type.value == "false_positive" for issue in result.issues)


def test_suite_and_quality_report_pass_known_good_fixture():
    fixture = _load_fixture()
    suite = evaluate_correlation_suite(
        "known-good-excel-correlation",
        [fixture.case],
        {fixture.case.case_id: fixture.observed_matches},
    )
    monitor = CorrelationQualityMonitor(max_history=2)
    report = monitor.build_report(
        suite,
        input_quality=InputDataQualitySnapshot(
            total_records=10,
            lineage_complete_records=10,
        ),
    )
    monitor.record(report)

    assert suite.passed is True
    assert report.passed is True
    assert report.status.value == "healthy"
    assert report.false_match_rate == 0.0
    assert monitor.latest() == report


def test_quality_monitor_keeps_tenant_histories_isolated():
    fixture = _load_fixture()
    suite = evaluate_correlation_suite(
        "tenant-isolation",
        [fixture.case],
        {fixture.case.case_id: fixture.observed_matches},
    )
    report = CorrelationQualityMonitor().build_report(suite)
    monitor = CorrelationQualityMonitor()

    monitor.record(report, organization_id="tenant-a")

    assert monitor.latest(organization_id="tenant-a") == report
    assert monitor.latest(organization_id="tenant-b") is None


def test_quality_report_fails_closed_without_negative_regression_checks():
    fixture = _load_fixture()
    case_without_non_match = fixture.case.model_copy(update={"expected_non_matches": []})
    suite = evaluate_correlation_suite(
        "missing-negative-coverage",
        [case_without_non_match],
        {case_without_non_match.case_id: [fixture.observed_matches[0]]},
    )
    report = CorrelationQualityMonitor().build_report(
        suite,
        thresholds=QualityGateThresholds(maximum_false_match_rate=0.01),
    )

    assert suite.passed is True
    assert report.passed is False
    assert report.false_match_rate == 1.0
    assert "false_match_rate" in report.failures[0]


def test_input_quality_is_conservative_when_lineage_or_normalization_is_bad():
    quality = InputDataQualitySnapshot(
        total_records=100,
        lineage_complete_records=80,
        records_missing_join_key=10,
        timestamp_normalization_failures=5,
        unit_normalization_failures=5,
    )

    assert quality.lineage_coverage == 0.8
    assert quality.data_quality_score < 0.9
    with pytest.raises(ValueError, match="cannot exceed total_records"):
        InputDataQualitySnapshot(total_records=2, lineage_complete_records=3)


def test_customer_vocabulary_only_resolves_after_human_approval_and_is_tenant_scoped():
    service = CustomerVocabularyService()
    feedback = CustomerVocabularyFeedback(
        organization_id="acme",
        raw_term="Mixer_01",
        canonical_term="MIX-01",
        kind=VocabularyFeedbackKind.ENTITY_ALIAS,
        field_name="Asset ID",
        submitted_by="operator-1",
    )
    service.submit(feedback)

    assert (
        service.resolve(
            "acme",
            "mixer-01",
            kind=VocabularyFeedbackKind.ENTITY_ALIAS,
            field_name="asset_id",
        )
        is None
    )

    reviewed = service.review(feedback.feedback_id, approved=True, reviewer_id="data-steward")
    resolution = service.resolve(
        "acme",
        "mixer-01",
        kind=VocabularyFeedbackKind.ENTITY_ALIAS,
        field_name="asset id",
    )

    assert reviewed.status is VocabularyFeedbackStatus.APPROVED
    assert resolution is not None
    assert resolution.canonical_term == "MIX-01"
    assert (
        service.resolve(
            "another-tenant",
            "mixer-01",
            kind=VocabularyFeedbackKind.ENTITY_ALIAS,
            field_name="asset id",
        )
        is None
    )


def test_customer_vocabulary_rejects_conflicting_approved_alias():
    service = CustomerVocabularyService()
    first = CustomerVocabularyFeedback(
        organization_id="acme",
        raw_term="press one",
        canonical_term="PRESS-01",
        kind=VocabularyFeedbackKind.ENTITY_ALIAS,
    )
    second = CustomerVocabularyFeedback(
        organization_id="acme",
        raw_term="Press_One",
        canonical_term="PRESS-99",
        kind=VocabularyFeedbackKind.ENTITY_ALIAS,
    )
    service.submit(first)
    service.review(first.feedback_id, approved=True, reviewer_id="steward")
    service.submit(second)

    with pytest.raises(VocabularyConflictError):
        service.review(second.feedback_id, approved=True, reviewer_id="steward")


def test_default_policy_requires_human_approval_and_human_decision_is_auditable():
    action = AutomatedAction(
        action_type="create_maintenance_task",
        correlation_confidence=0.999,
        data_quality_score=1.0,
        risk_score=0.0,
        idempotent=True,
        # Even when a proposed action does not request review itself, the
        # default policy still requires an accountable human decision.
        requires_human_approval=False,
    )
    approvals = ApprovalPolicyService()

    pending = approvals.assess(action)
    approved = approvals.apply_human_decision(
        pending,
        HumanApprovalDecision(
            action_id=action.action_id,
            approved=True,
            reviewer_id="maintenance-lead",
            reason="Verified against source rows.",
        ),
    )

    assert pending.status is ApprovalStatus.PENDING_APPROVAL
    assert pending.may_execute is False
    assert approved.status is ApprovalStatus.APPROVED
    assert approved.may_execute is True
    assert approved.reviewer_id == "maintenance-lead"


def test_auto_execution_needs_explicit_opt_in_and_every_safety_gate():
    action = AutomatedAction(
        action_type="append_annotation",
        correlation_confidence=0.99,
        data_quality_score=0.95,
        risk_score=5,
        idempotent=True,
        requires_human_approval=False,
    )
    policy = ApprovalPolicy(
        require_human_approval=False,
        auto_execute_enabled=True,
        allowed_auto_action_types=["append_annotation"],
        minimum_correlation_confidence=0.98,
        minimum_data_quality_score=0.90,
        maximum_auto_risk_score=10,
    )
    result = ApprovalPolicyService().assess(action, policy)

    assert result.status is ApprovalStatus.AUTO_APPROVED
    assert result.may_execute is True

    low_quality = action.model_copy(update={"data_quality_score": 0.4})
    pending = ApprovalPolicyService().assess(low_quality, policy)
    assert pending.status is ApprovalStatus.PENDING_APPROVAL
    assert pending.may_execute is False


def test_case_rejects_a_pair_asserted_as_both_match_and_non_match():
    left = _reference("a.xlsx", "1")
    right = _reference("b.xlsx", "1")
    with pytest.raises(ValueError, match="both an expected match and an expected non-match"):
        _load_fixture().case.__class__(
            case_id="invalid",
            name="invalid",
            expected_matches=[
                {"left": left, "right": right, "minimum_confidence": 0.5}
            ],
            expected_non_matches=[ExpectedNonMatch(left=left, right=right)],
        )
