"""Focused checks for deterministic operations-lead evidence answers.

Run directly with:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python tests/test_operations_question_service.py
"""

from datetime import date

from app.services.operations_question_service import (
    QUESTION_CHANGED,
    QUESTION_CHECKLIST,
    QUESTION_DOWNTIME,
    QUESTION_MAINTENANCE,
    QUESTION_OVERVIEW,
    QUESTION_PERFORMANCE,
    QUESTION_PRIORITY,
    QUESTION_QUALITY,
    QUESTION_SAFETY,
    answer_operations_question,
    classify_operations_question,
    suggested_operations_questions,
)


def _row(index, asset, downtime, vibration, scrap_left, scrap_right, event_time):
    return {
        "evidence_id": "evidence-%02d" % index,
        "match_status": "matched",
        "join_key": {"asset_id": asset, "event_time": event_time[:10]},
        "lineage": [
            {"source_id": "production", "source_name": "FY2024.xlsx", "table_name": "Production", "row_number": index, "row_id": "p:%d" % index},
            {"source_id": "maintenance", "source_name": "FY2024.xlsx", "table_name": "Maintenance", "row_number": index, "row_id": "m:%d" % index},
        ],
        "fields": {
            "left.asset_id": asset,
            "right.asset_id": asset,
            "left.event_time": event_time,
            "left.downtime_minutes": downtime,
            "right.vibration": vibration,
            "left.scrap_units": scrap_left,
            "right.scrap_units": scrap_right,
        },
    }


def _evidence_result():
    rows = [
        _row(1, "EX-01", 10, 2.0, 1, 1, "2024-03-01T08:00:00Z"),
        _row(2, "EX-02", 40, 8.0, 2, 5, "2024-03-02T08:00:00Z"),
        _row(3, "EX-02", 30, 7.0, 2, 4, "2024-03-03T08:00:00Z"),
    ]
    return {
        "evidence_rows": rows,
        "source_profile": {"source_count": 1, "table_count": 3},
        "quality": {"evidence_quality_score": 0.93, "evidence_quality_label": "high", "review_required": False},
        "analytics": {
            "relationships": [
                {
                    "status": "ok",
                    "left_field": "left.downtime_minutes",
                    "right_field": "right.vibration",
                    "pearson_r": 0.86,
                    "strength": "very_strong",
                    "observation_count": 3,
                    "association_confidence": 0.72,
                },
            ],
            "field_signals": {
                "left.downtime_minutes": {
                    "change_point": {
                        "status": "ok",
                        "interpretation": "A mean-shift candidate is a review signal, not an identified operational cause.",
                        "change_point": {"index": 1, "left_mean": 10, "right_mean": 35, "mean_delta": 25, "source_index": 1},
                    },
                    "anomalies": {"anomalies": []},
                },
            },
        },
    }


def _graph_row(evidence_id, production_row_id, related_source_id, related_row_id):
    """Return one graph edge containing the same production observation.

    The two edges in :func:`_duplicated_source_row_graph` intentionally share
    a production source row while differing on the related source.  This
    models the normal production-to-quality / production-to-maintenance graph
    shape and guards against treating the source observation as two separate
    downtime records during an operations priority calculation.
    """
    return {
        "evidence_id": evidence_id,
        "match_status": "matched",
        "join_key": {"asset_id": "EX-01", "event_time": "2024-03-01", "shift": "Day"},
        "lineage": [
            {
                "source_id": "production",
                "source_name": "FY2024.xlsx",
                "table_name": "Production",
                "row_number": 1,
                "row_id": production_row_id,
            },
            {
                "source_id": related_source_id,
                "source_name": "FY2024.xlsx",
                "table_name": related_source_id.title(),
                "row_number": 1,
                "row_id": related_row_id,
            },
        ],
        "fields": {
            "left.asset_id": "EX-01",
            "left.shift": "Day",
            "left.downtime_minutes": 10,
            "right.asset_id": "EX-01",
            "right.shift": "Day",
        },
    }


def _duplicated_source_row_graph():
    return {
        "evidence_sets": [
            {
                "matched_rows": [
                    _graph_row("production-quality-1", "production:1", "quality", "quality:1")
                ]
            },
            {
                "matched_rows": [
                    _graph_row("production-maintenance-1", "production:1", "maintenance", "maintenance:1")
                ]
            },
        ],
        "source_profile": {"source_count": 3, "table_count": 3},
        "quality": {"evidence_quality_score": 1.0, "evidence_quality_label": "high", "review_required": False},
    }


def _scoped_quality_row(evidence_id, shift, left_scrap, right_scrap):
    return {
        "evidence_id": evidence_id,
        "match_status": "matched",
        "join_key": {"asset_id": "EX-01", "event_time": "2024-03-01", "shift": shift},
        "lineage": [],
        "fields": {
            "left.asset_id": "EX-01",
            "right.asset_id": "EX-01",
            "left.shift": shift,
            "right.shift": shift,
            "left.scrap_units": left_scrap,
            "right.scrap_units": right_scrap,
        },
    }


def _explicit_filter_caveat(answer):
    """Return whether an answer clearly says the requested scope was not used.

    A deterministic assistant may initially choose to reject an unsupported
    filter rather than execute it.  That is acceptable, but silently using all
    records for a "night shift" question is not.  Keep this check textual so
    the service remains free to expose a richer structured scope contract.
    """
    text_parts = [str(answer.get("summary") or "")]
    for finding in answer.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        text_parts.append(str(finding.get("statement") or ""))
        text_parts.extend(str(item) for item in finding.get("uncertainty") or [])
    text = " ".join(text_parts).casefold()
    scope_word = "filter" in text or "scope" in text
    non_application = any(
        phrase in text
        for phrase in (
            "not applied",
            "not understood",
            "not supported",
            "cannot apply",
            "confirm the filter",
            "all records",
            "full evidence",
        )
    )
    return scope_word and non_application


def test_classifies_multiple_operations_lead_styles():
    assert classify_operations_question("Give me an overview of operations") ["intent"] == QUESTION_OVERVIEW
    assert classify_operations_question("What's hurting us? Why are we losing time?") ["intent"] == QUESTION_DOWNTIME
    assert classify_operations_question("What needs attention?") ["intent"] == QUESTION_PRIORITY
    assert classify_operations_question("Where are the quality issues?") ["intent"] == QUESTION_QUALITY
    assert classify_operations_question("What do I check next shift?") ["intent"] == QUESTION_CHECKLIST
    assert classify_operations_question("Which assets show vibration maintenance risk?") ["intent"] == QUESTION_MAINTENANCE


def test_classifies_common_operations_lead_variants_without_an_llm():
    """Operational language should map to a deterministic supported intent."""
    assert classify_operations_question("Why did Line 6 stop?")["intent"] == QUESTION_DOWNTIME
    assert classify_operations_question("Where is the bottleneck?")["intent"] == QUESTION_PERFORMANCE
    assert classify_operations_question("Which machine needs service?")["intent"] == QUESTION_MAINTENANCE
    assert classify_operations_question("Find anomalies in production.")["intent"] == QUESTION_CHANGED
    assert classify_operations_question("Are we on plan for this shift?")["intent"] == QUESTION_PERFORMANCE


def test_downtime_answer_has_lineage_citations_and_blocks_causal_claims():
    answer = answer_operations_question(
        "Why are we losing time?",
        _evidence_result(),
        company_name="Example Co",
        as_of=date(2024, 3, 5),
    )

    assert answer["classification"]["intent"] == QUESTION_DOWNTIME
    assert answer["findings"]
    association = next(finding for finding in answer["findings"] if finding["id"].startswith("downtime_association"))
    assert association["citations"][0]["lineage"][0]["table_name"] == "Production"
    assert "not" in association["uncertainty"][0].lower()
    assert answer["causation_guardrail"]["causal_confidence"] == 0.0
    assert answer["human_approval"]["required"] is True


def test_quality_reconciliation_and_priority_are_transparent_and_cited():
    evidence = _evidence_result()
    quality = answer_operations_question("Where are the quality issues?", evidence, as_of=date(2024, 3, 5))
    reconciliation = next(finding for finding in quality["findings"] if finding["id"].startswith("quality_reconciliation"))
    assert reconciliation["evidence"]["mismatch_count"] == 2
    assert reconciliation["citations"]

    priority = answer_operations_question("Which asset should we prioritize?", evidence, as_of=date(2024, 3, 5))
    assert priority["classification"]["intent"] == QUESTION_PRIORITY
    assert priority["findings"][0]["evidence"]["entity"] == "EX-02"
    assert priority["findings"][0]["evidence"]["metric"] == "left.downtime_minutes"


def test_graph_priority_deduplicates_a_reused_source_row():
    """A production row linked to two related tables must be counted once."""
    answer = answer_operations_question(
        "Which shift needs attention first?",
        _duplicated_source_row_graph(),
        as_of=date(2024, 3, 5),
    )

    finding = next(item for item in answer["findings"] if item["id"] == "priority_shift_1")
    assert finding["evidence"]["metric"] == "left.downtime_minutes"
    assert finding["evidence"]["value"] == 10
    assert finding["evidence"]["row_count"] == 1


def test_question_filter_is_applied_or_explicitly_caveated():
    """Never report all shifts as if they answered a requested night-shift view."""
    evidence = {
        "evidence_rows": [
            _scoped_quality_row("day", "Day", 5, 4),
            _scoped_quality_row("night", "Night", 5, 1),
        ],
        "source_profile": {"source_count": 2, "table_count": 2},
    }
    answer = answer_operations_question(
        "Where are the quality issues on night shift?",
        evidence,
        as_of=date(2024, 3, 5),
    )

    reconciliation = next(
        item for item in answer["findings"]
        if item["id"].startswith("quality_reconciliation")
    )
    assert (
        reconciliation["evidence"]["compared_row_count"] == 1
        or _explicit_filter_caveat(answer)
    ), "A requested filter must be applied or clearly called out as unapplied."


def test_next_shift_checklist_marks_historical_evidence_as_pattern_review():
    answer = answer_operations_question(
        "What do I check next shift?",
        _evidence_result(),
        as_of=date(2026, 8, 4),
    )

    assert answer["classification"]["intent"] == QUESTION_CHECKLIST
    assert answer["data_freshness"]["historical"] is True
    assert "pattern-review" in answer["data_freshness"]["caveat"]
    assert answer["next_shift_checklist"][0]["id"] == "verify_data_freshness"
    assert all(item["requires_human_approval"] for item in answer["next_shift_checklist"])


def test_freshness_ignores_future_next_pm_due_date():
    """Planned maintenance dates are not evidence of a newer operation event."""
    evidence = _evidence_result()
    for row in evidence["evidence_rows"]:
        row["fields"]["right.next_pm_due_date"] = "2030-01-01"

    answer = answer_operations_question(
        "Give me an overview of operations.",
        evidence,
        as_of=date(2024, 3, 5),
    )

    freshness = answer["data_freshness"]
    assert freshness["latest_event_time"] == "2024-03-03T08:00:00Z"
    assert freshness["age_days"] == 2
    assert "2030" not in freshness["caveat"]


def test_source_specific_operations_domain_is_available_without_a_pairwise_edge():
    """Safety facts can be cited even when no safe production join exists."""
    evidence = {
        "evidence_rows": [_row(1, "EX-01", 10, 2.0, 1, 1, "2024-03-01T08:00:00Z")],
        "_operations_source_rows": [
            {
                "evidence_id": "source:safety:1",
                "match_status": "source_row",
                "lineage": [{"source_id": "safety", "source_name": "FY2024.xlsx", "table_name": "Safety", "row_number": 1, "row_id": "s:1"}],
                "fields": {
                    "safety/Safety.date": "2024-03-02",
                    "safety/Safety.incident_count": 3,
                    "safety/Safety.near_miss_count": 5,
                },
            }
        ],
        "_operations_source_scope": {
            "available_source_record_count": 1,
            "retained_source_record_count": 1,
            "truncated": False,
        },
    }

    answer = answer_operations_question(
        "Are there safety or compliance issues to review?",
        evidence,
        as_of=date(2024, 3, 5),
    )

    assert answer["classification"]["intent"] == QUESTION_SAFETY
    assert answer["findings"][0]["id"] == "safety_metric_1"
    assert answer["findings"][0]["evidence"]["value"] == 3
    assert answer["findings"][0]["citations"][0]["lineage"][0]["table_name"] == "Safety"


def test_suggested_questions_cover_the_supported_workflow():
    intents = {item["intent"] for item in suggested_operations_questions()}
    assert {
        QUESTION_OVERVIEW,
        QUESTION_DOWNTIME,
        QUESTION_PRIORITY,
        QUESTION_QUALITY,
        QUESTION_MAINTENANCE,
        QUESTION_PERFORMANCE,
        QUESTION_CHECKLIST,
    } <= intents


def run_all_tests():
    test_classifies_multiple_operations_lead_styles()
    test_classifies_common_operations_lead_variants_without_an_llm()
    test_downtime_answer_has_lineage_citations_and_blocks_causal_claims()
    test_quality_reconciliation_and_priority_are_transparent_and_cited()
    test_graph_priority_deduplicates_a_reused_source_row()
    test_question_filter_is_applied_or_explicitly_caveated()
    test_next_shift_checklist_marks_historical_evidence_as_pattern_review()
    test_freshness_ignores_future_next_pm_due_date()
    test_source_specific_operations_domain_is_available_without_a_pairwise_edge()
    test_suggested_questions_cover_the_supported_workflow()
    print("All operations question service tests passed.")


if __name__ == "__main__":
    run_all_tests()
