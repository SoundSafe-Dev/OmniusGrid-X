"""Focused unit tests for the deterministic common evidence-table engine."""

import app.services.evidence_engine as evidence_engine
from app.services.evidence_engine import (
    build_entity_rollups,
    build_evidence_graph,
    build_evidence_table,
    infer_typed_schema,
    profile_join_candidates,
)


def _same_shift_sources():
    """Two unrelated assets intentionally share the same date and shift."""
    return [
        {
            "source_id": "production.xlsx",
            "tables": {
                "Production": [
                    {"Asset ID": "MX-101", "Date": "2026-04-12", "Shift": "Day", "Actual Units": 920},
                    {"Asset ID": "MX-202", "Date": "2026-04-12", "Shift": "Day", "Actual Units": 875},
                ],
            },
        },
        {
            "source_id": "maintenance.xlsx",
            "tables": {
                "Maintenance": [
                    {"Machine ID": "MX-101", "Date": "2026-04-12", "Shift": "Day", "Vibration": 6.2},
                    {"Machine ID": "MX-303", "Date": "2026-04-12", "Shift": "Day", "Vibration": 8.9},
                ],
            },
        },
    ]


def test_common_evidence_table_does_not_cross_match_assets_on_same_shift():
    sources = _same_shift_sources()
    candidates = profile_join_candidates(sources)

    assert candidates
    best = candidates[0]
    assert [key["canonical_name"] for key in best["keys"]] == ["asset_id", "event_time", "shift"]
    assert best["safety"]["safe_for_auto_preview"] is True

    result = build_evidence_table(sources)

    assert result["selection_mode"] == "auto_preview"
    assert len(result["matched_rows"]) == 1
    assert len(result["unmatched_left_rows"]) == 1
    assert len(result["unmatched_right_rows"]) == 1
    assert len(result["evidence_rows"]) == 3

    matched = result["matched_rows"][0]
    assert matched["join_key"] == {
        "asset_id": "MX-101",
        "event_time": "2026-04-12",
        "shift": "DAY",
    }
    assert matched["fields"]["left.actual_units"] == 920
    assert matched["fields"]["right.vibration"] == 6.2
    assert [row["lineage"]["row_id"] for row in matched["source_rows"]] == [
        "production_xlsx:production:1",
        "maintenance_xlsx:maintenance:1",
    ]

    # This is the regression guard: shared shift/date must never turn MX-202
    # and MX-303 into an invented relationship.
    assert all(
        not (
            row["fields"].get("left.asset_id") == "MX-202"
            and row["fields"].get("right.asset_id") == "MX-303"
        )
        for row in result["matched_rows"]
    )
    assert result["quality"]["many_to_many_key_count"] == 0
    assert "causation" in result["quality"]["interpretation"].lower()


def test_weak_date_shift_plan_is_exposed_for_review_but_not_auto_executed():
    sources = [
        {"source_id": "one.csv", "tables": {"one": [{"Date": "2026-04-12", "Shift": "Night", "Units": 20}]}},
        {"source_id": "two.csv", "tables": {"two": [{"Date": "2026-04-12", "Shift": "Night", "Defects": 4}]}},
    ]

    weak_candidates = profile_join_candidates(sources, include_weak_keys=True)
    assert weak_candidates
    assert all(candidate["safety"]["safe_for_auto_preview"] is False for candidate in weak_candidates)

    result = build_evidence_table(sources, include_weak_keys=True)
    assert result["join_plan"] is None
    assert result["matched_rows"] == []
    assert result["quality"]["review_required"] is True


def test_configurable_time_bucket_joins_nearby_events_and_preserves_unmatched_rows():
    sources = [
        {
            "source_id": "operations.jsonl",
            "tables": {
                "Ops": [
                    {"asset": "PK-04", "timestamp": "2026-04-12T10:04:00Z", "units": 80},
                    {"asset": "PK-05", "timestamp": "2026-04-12T10:04:00Z", "units": 65},
                ],
            },
        },
        {
            "source_id": "condition.csv",
            "tables": {
                "Condition": [
                    {"equipment_id": "PK-04", "event_time": "2026-04-12T10:55:00+00:00", "temperature_c": 37.2},
                    {"equipment_id": "PK-06", "event_time": "2026-04-12T10:30:00+00:00", "temperature_c": 39.1},
                ],
            },
        },
    ]
    candidates = profile_join_candidates(sources, time_bucket_minutes=60)
    bucket_plan = next(candidate for candidate in candidates if candidate["strategy"] == "time_bucket")

    result = build_evidence_table(sources, join_plan=bucket_plan, time_bucket_minutes=60)

    assert result["join_plan"]["approval_state"] == "proposed"
    assert len(result["matched_rows"]) == 1
    assert len(result["unmatched_left_rows"]) == 1
    assert len(result["unmatched_right_rows"]) == 1
    assert result["matched_rows"][0]["join_key"]["event_time"].startswith("bucket:60m:2026-04-12T10:00:00")
    assert result["quality"]["selectivity"] == 1.0


def test_schema_inference_keeps_identifiers_as_text_and_tracks_lineage_schema():
    schema = infer_typed_schema([
        {"Asset ID": "0017", "Date": "2026-04-12", "Downtime Minutes": 12.5, "Approved": "yes"},
        {"Asset ID": "0018", "Date": "2026-04-13", "Downtime Minutes": 8, "Approved": "no"},
    ])
    columns = {column["canonical_name"]: column for column in schema["columns"]}

    assert columns["asset_id"]["logical_type"] == "string"
    assert columns["event_time"]["logical_type"] == "date"
    assert columns["downtime_minutes"]["logical_type"] == "number"
    assert columns["approved"]["logical_type"] == "boolean"
    assert schema["timezone_assumption"].startswith("Naive timestamps")


def test_multi_source_graph_keeps_pairwise_lineage_without_inventing_mega_rows():
    sources = [
        {
            "source_id": "production.xlsx",
            "tables": {"Production": [
                {"asset": "MX-101", "facility": "A", "date": "2026-04-12", "units": 100},
            ]},
        },
        {
            "source_id": "maintenance.jsonl",
            "tables": {"Maintenance": [
                {"equipment_id": "MX-101", "plant": "A", "event_date": "2026-04-12", "downtime": 12},
            ]},
        },
        {
            "source_id": "quality.tsv",
            "tables": {"Quality": [
                {"machine_id": "MX-101", "site": "A", "production_date": "2026-04-12", "defects": 2},
            ]},
        },
    ]

    graph = build_evidence_graph(sources, max_match_pairs=12)

    assert graph["selection_mode"] == "auto_preview_graph"
    assert graph["relationship_count"] == 3
    assert graph["matched_pair_count"] == 3
    assert all(edge["join_plan"]["approval_state"] == "proposed" for edge in graph["evidence_sets"])
    assert all(len(edge["matched_rows"][0]["lineage"]) == 2 for edge in graph["evidence_sets"])
    assert "causal" in graph["quality"]["interpretation"].lower()


def test_single_multisheet_workbook_builds_a_pairwise_evidence_graph():
    """One uploaded workbook may supply the whole operational evidence graph."""
    sources = [
        {
            "source_id": "company_operations.xlsx",
            "source_name": "Company Operations FY2024",
            "tables": {
                "Production": [
                    {"asset_id": "MX-101", "facility": "North", "date": "2026-04-12", "units": 100},
                ],
                "Maintenance": [
                    {"machine_id": "MX-101", "plant": "North", "event_date": "2026-04-12", "downtime_minutes": 12},
                ],
                "Quality": [
                    {"equipment_id": "MX-101", "site": "North", "production_date": "2026-04-12", "defects": 2},
                ],
            },
        },
    ]

    graph = build_evidence_graph(sources, max_match_pairs=12)

    assert graph["selection_mode"] == "auto_preview_graph"
    assert graph["relationship_count"] == 3
    assert graph["matched_pair_count"] == 3
    assert all(
        edge["join_plan"]["left"]["source_id"] == "company_operations.xlsx"
        and edge["join_plan"]["right"]["source_id"] == "company_operations.xlsx"
        for edge in graph["evidence_sets"]
    )
    assert all(
        edge["join_plan"]["left"]["table_name"]
        != edge["join_plan"]["right"]["table_name"]
        for edge in graph["evidence_sets"]
    )


def test_graph_reuses_its_table_profile_and_candidate_catalog_for_each_edge(monkeypatch):
    """A graph profiles all table pairs once, not once again per emitted edge."""
    sources = [{
        "source_id": "company_operations.xlsx",
        "tables": {
            "Production": [{"asset_id": "MX-101", "date": "2026-04-12", "units": 100}],
            "Maintenance": [{"machine_id": "MX-101", "event_date": "2026-04-12", "downtime": 12}],
            "Quality": [{"equipment_id": "MX-101", "production_date": "2026-04-12", "defects": 2}],
        },
    }]
    calls = 0
    original = evidence_engine._profile_join_candidates_for_tables

    def counted_profile(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(evidence_engine, "_profile_join_candidates_for_tables", counted_profile)

    graph = build_evidence_graph(sources, max_match_pairs=12)

    assert graph["relationship_count"] == 3
    assert calls == 1
    assert all("candidate_join_plans" not in edge for edge in graph["evidence_sets"])
    assert all("source_profile" not in edge for edge in graph["evidence_sets"])


def test_graph_discloses_when_relationship_limit_excludes_eligible_pairs():
    sources = [{
        "source_id": "operations.xlsx",
        "tables": {
            name: [{"asset_id": "MX-101", "date": "2026-04-12", metric: value}]
            for name, metric, value in (
                ("Production", "actual_units", 100),
                ("Quality", "defect_count", 2),
                ("Maintenance", "vibration", 6.2),
                ("Safety", "incident_count", 1),
            )
        },
    }]

    graph = build_evidence_graph(sources, max_evidence_sets=3, max_match_pairs=12)

    assert graph["relationship_count"] == 3
    assert graph["graph_scope"]["eligible_safe_pair_count"] == 6
    assert graph["graph_scope"]["partial_graph"] is True
    assert graph["review_required"] is True
    assert "Only 3 of 6 eligible table pairs" in graph["quality"]["warnings"][-1]


def test_reviewed_entity_aliases_are_deterministic_and_recorded_in_join_plan():
    sources = [
        {"source_id": "ops.csv", "tables": {"ops": [{"asset": "PUMP-01", "units": 80}]}},
        {"source_id": "cmms.csv", "tables": {"cmms": [{"machine_id": "P-1", "downtime": 12}]}},
    ]

    result = build_evidence_table(
        sources,
        value_aliases={"asset_id": {"P-1": "PUMP-01"}},
    )

    assert len(result["matched_rows"]) == 1
    assert result["join_plan"]["value_aliases"] == {"asset_id": {"P-1": "PUMP-01"}}
    assert "-a" in result["join_plan"]["plan_id"]


def test_entity_rollups_keep_company_asset_line_and_shift_grains_separate():
    """A file total must never be reused as an asset total."""
    sources = [{
        "source_id": "production.xlsx",
        "tables": {"Production": [
            {
                "Asset ID": "AST-014-72", "Facility": "North", "Line": "LINE-1", "Shift": "Day",
                "Date": "2024-01-01", "Downtime Minutes": 2,
            },
            {
                "Asset ID": "AST-014-72", "Facility": "South", "Line": "LINE-1", "Shift": "Day",
                "Date": "2024-01-02", "Downtime Minutes": 3,
            },
            {
                "Asset ID": "AST-099", "Facility": "North", "Line": "LINE-2", "Shift": "Night",
                "Date": "2024-01-03", "Downtime Minutes": 40,
            },
        ]},
    }]

    result = build_entity_rollups(sources)
    assert result["source_table_scoped"] is True
    assert result["cross_table_pooling"] is False
    assert "one source table" in result["scope_contract"]["company"].lower()

    def rollup(level):
        return next(
            item for item in result["rollups"]
            if item["source"]["table_name"] == "Production"
            and item["metric"]["canonical_name"] == "downtime_minutes"
            and item["entity_level"] == level
        )

    company = rollup("company")
    asset = rollup("asset")
    assert company["source"]["source_id"] == "production.xlsx"
    assert company["groups"][0]["value"] == 45
    assert company["groups"][0]["entity"] == {}

    asset_values = {
        (group["entity"].get("facility"), group["entity"].get("asset_id")): group["value"]
        for group in asset["groups"]
    }
    assert asset_values[("North", "AST-014-72")] == 2
    assert asset_values[("South", "AST-014-72")] == 3
    assert asset_values[("North", "AST-099")] == 40
    assert all(group["value"] != 45 for group in asset["groups"])
    assert all(group["lineage_sample"][0]["table_name"] == "Production" for group in asset["groups"])


def test_entity_rollups_keep_long_form_units_in_separate_metric_boundaries():
    sources = [{
        "source_id": "condition.csv",
        "tables": {"Condition": [
            {"asset_id": "MX-01", "metric_name": "Temperature", "value": 20, "unit": "degC"},
            {"asset_id": "MX-01", "metric_name": "Temperature", "value": 68, "unit": "degF"},
        ]},
    }]

    result = build_entity_rollups(sources)
    company_rollups = [
        item for item in result["rollups"]
        if item["source"]["table_name"] == "Condition" and item["entity_level"] == "company"
    ]
    values_by_unit = {
        item["metric"]["unit"]: item["groups"][0]["value"]
        for item in company_rollups
        if item["metric"]["metric_name"] == "Temperature"
    }
    assert values_by_unit == {"degC": 20, "degF": 68}
    assert 88 not in values_by_unit.values()


def test_edited_join_plan_recomputes_plan_id_and_rejected_plan_is_not_run():
    sources = _same_shift_sources()
    candidate = profile_join_candidates(sources)[0]
    edited = dict(candidate)
    edited["plan_id"] = "stale-plan-id"
    edited["keys"] = [dict(candidate["keys"][0])]

    result = build_evidence_table(sources, join_plan=edited)
    assert result["join_plan"]["plan_id"] != "stale-plan-id"
    assert result["join_plan"]["plan_id"] != candidate["plan_id"]
    assert len(result["join_plan"]["keys"]) == 1

    rejected = dict(candidate)
    rejected["approval_state"] = "rejected"
    rejected_result = build_evidence_table(sources, join_plan=rejected)
    assert rejected_result["selection_mode"] == "rejected"
    assert rejected_result["matched_rows"] == []
    assert "rejected" in rejected_result["quality"]["interpretation"].lower()


def test_confirmed_graph_skips_rejected_and_duplicate_table_pairs():
    sources = _same_shift_sources()
    candidate = profile_join_candidates(sources)[0]
    duplicate = dict(candidate)
    duplicate["plan_id"] = "old-id-that-must-not-create-a-second-edge"

    graph = build_evidence_graph(sources, join_plans=[candidate, duplicate])
    assert graph["relationship_count"] == 1
    assert graph["graph_scope"]["duplicate_plan_count"] == 1
    assert graph["evidence_sets"][0]["join_plan"]["plan_id"] != duplicate["plan_id"]

    rejected = dict(candidate)
    rejected["approval_state"] = "rejected"
    rejected_graph = build_evidence_graph(sources, join_plans=[rejected])
    assert rejected_graph["relationship_count"] == 0
    assert rejected_graph["graph_scope"]["rejected_plan_count"] == 1
    assert rejected_graph["graph_scope"]["explicit_plan_selection"] is True

    empty_selection_graph = build_evidence_graph(sources, join_plans=[])
    assert empty_selection_graph["relationship_count"] == 0
    assert empty_selection_graph["graph_scope"]["explicit_plan_selection"] is True
