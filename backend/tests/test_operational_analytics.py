"""Focused dependency-free checks for deterministic operational analytics.

Run directly with:
    PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python tests/test_operational_analytics.py
"""

from app.services.operational_analytics import (
    OperationalAnalyticsLimits,
    analyze_evidence_rows,
    analyze_operational_relationships,
    detect_anomalies,
    detect_change_points,
    lagged_correlation,
    pearson_correlation,
    spearman_correlation,
)


def test_rank_and_linear_relationships_are_deterministic():
    assert pearson_correlation([1, 2, 3, 4], [3, 6, 9, 12]) == 1.0
    assert pearson_correlation([1, 2, 3, 4], [12, 9, 6, 3]) == -1.0
    assert spearman_correlation([10, 10, 20, 30], [1, 1, 2, 3]) == 1.0
    assert pearson_correlation([1, 1, 1], [3, 4, 5]) is None


def test_lag_analysis_identifies_a_right_side_delay_without_claiming_causation():
    left = [0, 2, 1, 5, 3, 9, 4, 8, 0, 7, 6, 2]
    # The right sequence repeats left two observations later.  Deliberately
    # non-linear values prevent every lag from looking perfectly correlated.
    right = [91, 92] + left
    result = lagged_correlation(left, right, max_lag_steps=4, min_observations=6)

    assert result["status"] == "ok"
    assert result["best_lag"]["right_lag_steps"] == 2
    assert result["best_lag"]["pearson_r"] == 1.0
    assert "does not establish" in result["causation_guardrail"].lower()


def test_anomaly_and_change_point_detection_emit_review_signals():
    anomaly = detect_anomalies([10] * 10 + [99])
    assert anomaly["status"] == "ok"
    assert anomaly["anomalies"] == [
        {
            "index": 10,
            "value": 99.0,
            "score": anomaly["anomalies"][0]["score"],
            "direction": "high",
        }
    ]

    change = detect_change_points(
        [10, 11, 9, 10, 11, 9, 50, 51, 49, 50, 51, 49],
        min_segment_size=4,
        score_threshold=2.5,
    )
    assert change["status"] == "ok"
    assert change["change_point"] is not None
    assert change["change_point"]["index"] == 6
    assert change["change_point"]["mean_delta"] > 30
    assert "not an identified" in change["interpretation"].lower()


def test_evidence_rows_preserve_time_order_and_never_promote_causation():
    evidence_rows = [
        {
            "fields": {
                "left.event_time": f"2026-05-{day:02d}T00:00:00Z",
                "left.units": day * 10,
                "right.defects": day * 2,
            }
        }
        for day in range(1, 11)
    ]
    result = analyze_evidence_rows(
        evidence_rows,
        time_field="left.event_time",
        limits=OperationalAnalyticsLimits(min_observations=6, max_lag_steps=3),
    )

    assert result["status"] == "ok"
    assert result["time_ordered"] is True
    assert len(result["relationships"]) == 1
    relationship = result["relationships"][0]
    assert relationship["pearson_r"] == 1.0
    assert relationship["causation"]["status"] == "not_established"
    assert relationship["causation"]["causal_confidence"] == 0.0
    assert result["causation"]["status"] == "not_established"


def test_analysis_stays_within_declared_row_and_pair_bounds():
    rows = [
        {
            "event_time": f"2026-06-{(index % 28) + 1:02d}T00:00:00Z",
            "a": index,
            "b": index * 2,
            "c": index * 3,
            "d": index * 4,
        }
        for index in range(30)
    ]
    result = analyze_operational_relationships(
        rows,
        limits=OperationalAnalyticsLimits(
            max_rows=10,
            max_numeric_fields=4,
            max_pair_analyses=2,
            min_observations=4,
        ),
    )

    assert result["row_count"] == 10
    assert result["bounded"]["input_truncated"] is True
    assert len(result["relationships"]) == 2
    assert result["bounded"]["pair_limit_reached"] is True


def run_all_tests():
    test_rank_and_linear_relationships_are_deterministic()
    test_lag_analysis_identifies_a_right_side_delay_without_claiming_causation()
    test_anomaly_and_change_point_detection_emit_review_signals()
    test_evidence_rows_preserve_time_order_and_never_promote_causation()
    test_analysis_stays_within_declared_row_and_pair_bounds()
    print("All operational analytics tests passed.")


if __name__ == "__main__":
    run_all_tests()
