"""Tests for cross-file YoY trends and asset direction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.multi_spreadsheet_correlator import correlate_spreadsheet_sources, compute_yoy_trends
from app.services.correlation_ai_engine import CorrelationAIEngine


def _processed(attainment, shortfall, downtime, assets=None):
    return {
        "type": "spreadsheet",
        "rows": 100,
        "linking_metadata": {
            "date_range": {"min": "2015-01-01", "max": "2015-12-31"},
            "distinct_assets": assets or ["AST-001-62"],
            "distinct_lines": ["LINE-6"],
            "year_labels": [2015],
        },
        "full_sheet_profile": {
            "operational_summary": {
                "planned_vs_actual": {
                    "average_attainment_pct": attainment,
                    "shortfall_total": shortfall,
                },
                "downtime": {"total": downtime},
            }
        },
    }


def test_yoy_trends_improving_attainment():
    sources = [
        {"source_id": "1", "file_name": "fy2015.xlsx", "processed_data": _processed(76.6, 236264, 42686)},
        {"source_id": "2", "file_name": "fy2016.xlsx", "processed_data": {
            **_processed(76.7, 231614, 44318),
            "linking_metadata": {
                "date_range": {"min": "2016-01-01", "max": "2016-12-31"},
                "distinct_assets": ["AST-001-62"],
                "year_labels": [2016],
            },
        }},
        {"source_id": "3", "file_name": "fy2017.xlsx", "processed_data": {
            **_processed(77.0, 227534, 40761),
            "linking_metadata": {
                "date_range": {"min": "2017-01-01", "max": "2017-12-31"},
                "distinct_assets": ["AST-001-62"],
                "year_labels": [2017],
            },
        }},
    ]
    for src in sources:
        src["processed_data"]["linking_metadata"]["date_range"] = {
            "min": src["processed_data"]["linking_metadata"]["date_range"]["min"],
            "max": src["processed_data"]["linking_metadata"]["date_range"]["max"],
        }

    analysis = correlate_spreadsheet_sources(sources)
    yoy = analysis["yoy_trends"]
    assert yoy["years"] == ["2015", "2016", "2017"]
    attainment = next(m for m in yoy["metrics"] if m["metric"] == "attainment_pct")
    shortfall = next(m for m in yoy["metrics"] if m["metric"] == "shortfall_total")
    assert attainment["direction"] == "improving"
    assert shortfall["direction"] == "improving"
    assert analysis["file_rollups"][0]["total_loss"] is None
    assert analysis["file_rollups"][0]["total_downtime"] == 42686


def test_trends_response_handler():
    engine = CorrelationAIEngine()
    context = {
        "multi_spreadsheet_analysis": correlate_spreadsheet_sources([
            {"source_id": "1", "file_name": "fy2015.xlsx", "processed_data": _processed(76.6, 236264, 42686)},
            {"source_id": "2", "file_name": "fy2017.xlsx", "processed_data": {
                **_processed(77.0, 227534, 40761),
                "linking_metadata": {
                    "date_range": {"min": "2017-01-01", "max": "2017-12-31"},
                    "distinct_assets": ["AST-001-62"],
                    "year_labels": [2017],
                },
            }},
        ])
    }
    text = engine._format_cross_file_trends_response("What trends do you see across all files?", context)
    assert text is not None
    assert "improving" in text.lower()
    assert "Attainment" in text


def test_invalid_group_value_rejected():
    from app.api.nlp_correlation import _is_valid_operational_group_value

    assert not _is_valid_operational_group_value("Paid")
    assert _is_valid_operational_group_value("Material shortage")


if __name__ == "__main__":
    test_yoy_trends_improving_attainment()
    test_trends_response_handler()
    test_invalid_group_value_rejected()
    print("All multi-file trend tests passed.")
