"""
Tests for multi-tab spreadsheet intake -> correlation scenario building.

Run:
    cd backend && python -m pytest tests/test_spreadsheet_intake.py -v
or standalone:
    cd backend && python tests/test_spreadsheet_intake.py
"""

import sys
from pathlib import Path

# Ensure backend root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from app.models.domain_interaction import DomainType, CorrelationScenario
from app.services.spreadsheet_domain_mapper import (
    map_tab_to_domain,
    map_workbook_domains,
)
from app.services.spreadsheet_scenario_builder import build_scenarios


def _sample_tabs():
    """Three tabs sharing date/shift/asset_id for cross-tab linkage."""
    production = pd.DataFrame([
        {"date": "2015-01-01", "shift": "Day", "asset_id": "A-001",
         "planned_units": 1000, "actual_units": 950, "oee_score": 82.0, "status": "normal"},
        {"date": "2015-01-02", "shift": "Day", "asset_id": "A-001",
         "planned_units": 1000, "actual_units": 300, "oee_score": 41.0, "status": "critical"},
    ])
    maintenance = pd.DataFrame([
        {"date": "2015-01-01", "shift": "Day", "asset_id": "A-001",
         "vibration_mm_s": 1.2, "maintenance_status": "ok"},
        {"date": "2015-01-02", "shift": "Day", "asset_id": "A-001",
         "vibration_mm_s": 4.6, "maintenance_status": "critical"},
    ])
    quality = pd.DataFrame([
        {"date": "2015-01-01", "shift": "Day", "asset_id": "A-001",
         "defect_count": 3, "first_pass_yield_percent": 98.0},
        {"date": "2015-01-02", "shift": "Day", "asset_id": "A-001",
         "defect_count": 80, "first_pass_yield_percent": 70.0},
    ])
    return {
        "Production_Operations": production,
        "Maintenance_Assets": maintenance,
        "Quality_Control": quality,
    }


def test_tab_to_domain_mapping():
    assert map_tab_to_domain("Production_Operations", []) == DomainType.PROD
    assert map_tab_to_domain("Maintenance_Assets", []) == DomainType.MNT
    assert map_tab_to_domain("Quality_Control", []) == DomainType.QUA
    # Column-keyword fallback when tab name is unknown
    assert map_tab_to_domain("MysteryTab", ["trailer_id", "dock_door_id"]) == DomainType.LOG


def test_workbook_domain_mapping():
    tabs = _sample_tabs()
    mapping = map_workbook_domains({n: list(df.columns) for n, df in tabs.items()})
    assert set(d.value for d in mapping.active_domains) == {
        "PRODUCTION_OEE", "MAINTENANCE", "QUALITY_CONTROL"
    }
    assert mapping.context_only_tabs == []


def test_window_mode_cross_tab_links():
    tabs = _sample_tabs()
    scenarios = list(build_scenarios(tabs, mode="window", source_id="t"))
    # Two windows (2015-01-01|Day and 2015-01-02|Day)
    assert len(scenarios) == 2
    for sc in scenarios:
        assert isinstance(sc, CorrelationScenario)
        # all three domains present per window -> cross-tab
        assert len(sc.active_domains) == 3
        # every domain pair receives an evidence link
        assert len(sc.domain_links) == 3
        # interaction key is the shared asset
        assert all(link.interaction_key == "A-001" for link in sc.domain_links)
        # every metric validates and carries a payload
        assert len(sc.ingested_metrics) == 3
        for m in sc.ingested_metrics:
            assert m.endpoint
            assert isinstance(m.payload_snapshot, dict)

    # The anomalous window (Jan 2) should carry higher severity
    sev_by_window = {
        sc.scenario_id: max(l.severity_impact for l in sc.domain_links)
        for sc in scenarios
    }
    assert max(sev_by_window.values()) >= 0.7  # critical mapped high


def test_tab_mode_single_scenario():
    tabs = _sample_tabs()
    scenarios = list(build_scenarios(tabs, mode="tab", source_id="t"))
    assert len(scenarios) == 1
    assert len(scenarios[0].active_domains) == 3


def test_row_mode_counts():
    tabs = _sample_tabs()
    scenarios = list(build_scenarios(tabs, mode="row", source_id="t"))
    # 2 rows x 3 tabs = 6 scenarios
    assert len(scenarios) == 6
    assert all(len(sc.active_domains) == 1 for sc in scenarios)


def test_window_mode_never_cross_links_different_assets_on_same_shift():
    """Asset identity is part of the temporal correlation grain.

    This prevents a maintenance event for B-999 from being attributed to
    production rows for A-001 just because both happened on the day shift.
    """
    tabs = {
        "Production": pd.DataFrame([
            {"date": "2025-01-01", "shift": "Day", "asset_id": "A-001", "status": "critical"},
        ]),
        "Maintenance": pd.DataFrame([
            {"date": "2025-01-01", "shift": "Day", "asset_id": "B-999", "maintenance_status": "critical"},
        ]),
    }
    scenarios = list(build_scenarios(tabs, mode="window", source_id="t"))
    assert len(scenarios) == 2
    assert all(len(scenario.active_domains) == 1 for scenario in scenarios)
    assert all(not scenario.domain_links for scenario in scenarios)


def test_xlsx_roundtrip_multisheet():
    """Confirm an .xlsx with multiple sheets parses all tabs (not just first)."""
    import io
    tabs = _sample_tabs()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in tabs.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    buf.seek(0)
    sheets = pd.read_excel(buf, sheet_name=None)
    assert len(sheets) == 3
    scenarios = list(build_scenarios(sheets, mode="window", source_id="t"))
    assert len(scenarios) == 2


if __name__ == "__main__":
    test_tab_to_domain_mapping()
    test_workbook_domain_mapping()
    test_window_mode_cross_tab_links()
    test_tab_mode_single_scenario()
    test_row_mode_counts()
    test_window_mode_never_cross_links_different_assets_on_same_shift()
    test_xlsx_roundtrip_multisheet()
    print("All spreadsheet intake tests passed.")
