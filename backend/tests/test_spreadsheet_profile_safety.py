"""
Regression tests for spreadsheet profiling on messy / multi-sheet workbooks.

Run:
    cd backend && python -m pytest tests/test_spreadsheet_profile_safety.py -v
"""

import asyncio
import io
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.nlp_correlation import _process_uploaded_file, _operational_profile


def test_defect_type_text_column_does_not_break_profiling():
    """Columns like defect_type must not be summed as numeric defect counts."""
    df = pd.DataFrame({
        "Defect_Type": ["Registration", "Crack", "Smudge", "Underbase"] * 50,
        "planned_units": [100, 200, 150, 180] * 50,
        "downtime_minutes": [5, 10, 3, 8] * 50,
    })
    profile = _operational_profile(df)
    assert "defects" not in profile
    assert profile.get("downtime", {}).get("total") == 1300.0


def test_multisheet_workbook_profiles_all_tabs():
    tabs = {
        "Quality": pd.DataFrame({
            "Defect_Type": ["Registration", "Crack", "Smudge"],
            "line": ["L1", "L1", "L2"],
        }),
        "Production": pd.DataFrame({
            "planned_units": [100, 200],
            "actual_units": [95, 180],
            "asset_id": ["A-1", "A-2"],
        }),
    }
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, frame in tabs.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    buf.seek(0)

    # asyncio.run (not get_event_loop().run_until_complete): the deprecated
    # form grabs whatever loop earlier tests left behind, making this test
    # order-dependent — it failed in full-suite runs but passed in isolation.
    result = asyncio.run(
        _process_uploaded_file(buf.read(), "spreadsheet", "quality_ops.xlsx")
    )
    assert result.get("type") == "spreadsheet"
    assert result.get("tab_count") == 2
    assert set(result.get("tab_names") or []) == {"Quality", "Production"}
    assert len(result.get("tabs") or []) == 2
    assert not result.get("error")
    merged = result.get("full_sheet_profile") or {}
    assert merged.get("workbook_tab_count") == 2
    assert len(merged.get("per_tab_summaries") or []) == 2


def test_zip_intake_uses_the_configured_archive_table_capacity():
    """A normal 101-file batch must not fall back to the 100-table default."""

    payload = io.BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        for index in range(101):
            archive.writestr(
                "exports/operations_%03d.csv" % index,
                "asset_id,downtime_minutes\nMX-%03d,1\n" % index,
            )

    result = asyncio.run(
        _process_uploaded_file(payload.getvalue(), "spreadsheet", "operations_batch.zip")
    )

    assert result.get("tab_count") == 101
    assert result.get("truncated") is False
    assert len(result.get("tabs") or []) == 101
