"""Tests for multi_spreadsheet_correlator."""

from app.services.multi_spreadsheet_correlator import correlate_spreadsheet_sources


def _spreadsheet(file_name: str, assets, date_min, date_max, rows=100):
    return {
        "source_id": file_name,
        "file_name": file_name,
        "processed_data": {
            "type": "spreadsheet",
            "rows": rows,
            "filename": file_name,
            "linking_metadata": {
                "row_count": rows,
                "date_range": {"min": date_min, "max": date_max},
                "year_labels": [int(date_min[:4])],
                "distinct_assets": assets,
                "distinct_lines": ["Line A"],
            },
            "full_sheet_profile": {
                "operational_summary": {
                    "planned_vs_actual": {"average_attainment_pct": 92, "shortfall_total": 50},
                    "estimated_loss": {"total": 1000},
                    "downtime": {"total": 120},
                    "defects": {"total": 5},
                }
            },
        },
    }


def test_correlate_shared_assets_across_files():
    sources = [
        _spreadsheet("ops_2018.xlsx", ["MX-101", "PK-204"], "2018-01-01", "2018-12-31"),
        _spreadsheet("ops_2019.xlsx", ["MX-101", "CV-017"], "2019-01-01", "2019-12-31"),
        _spreadsheet("ops_2020.xlsx", ["MX-101"], "2020-01-01", "2020-12-31"),
    ]
    result = correlate_spreadsheet_sources(sources)
    assert result["file_count"] == 3
    assert "MX-101" in result["shared_assets"]
    assert len(result["shared_assets"]["MX-101"]) == 3
    assert result["years_span"] == 3
    assert result["linked"] is True


def test_correlate_requires_two_files():
    result = correlate_spreadsheet_sources([_spreadsheet("a.xlsx", ["X"], "2020-01-01", "2020-12-31")])
    assert result["file_count"] == 1
    assert result["linked"] is False
