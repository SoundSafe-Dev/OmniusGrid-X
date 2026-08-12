"""End-to-end deterministic pipeline check without API/auth dependencies."""

from app.services.evidence_engine import build_evidence_graph
from app.services.ingestion_adapters import ingest_file
from app.services.operational_analytics import analyze_evidence_rows
from app.services.operational_normalization import normalize_operational_evidence_row


def test_tsv_and_jsonl_flow_into_multi_source_lineage_evidence_and_statistics():
    production = ingest_file(
        (
            b"asset_id\tfacility\tdate\toutput\n"
            b"MX-01\tPlant-A\t2026-08-01\t80\n"
            b"MX-02\tPlant-A\t2026-08-01\t70\n"
        ),
        "production.tsv",
    )
    maintenance = ingest_file(
        (
            b'{"machine_id":"MX-01","plant":"Plant-A","event_date":"2026-08-01","downtime":12}\n'
            b'{"machine_id":"MX-03","plant":"Plant-A","event_date":"2026-08-01","downtime":9}\n'
        ),
        "maintenance.jsonl",
    )
    quality = ingest_file(
        (
            b"asset,site,production_date,defects\n"
            b"MX-01,Plant-A,2026-08-01,2\n"
            b"MX-02,Plant-A,2026-08-01,4\n"
        ),
        "quality.csv",
    )

    graph = build_evidence_graph([
        {"source_id": "production", "tables": production["tables"]},
        {"source_id": "maintenance", "tables": maintenance["tables"]},
        {"source_id": "quality", "tables": quality["tables"]},
    ])

    assert graph["relationship_count"] == 3
    assert graph["matched_pair_count"] == 4
    maintenance_edge = next(
        edge for edge in graph["evidence_sets"]
        if {edge["join_plan"]["left"]["source_id"], edge["join_plan"]["right"]["source_id"]}
        == {"production", "maintenance"}
    )
    assert len(maintenance_edge["matched_rows"]) == 1
    assert maintenance_edge["matched_rows"][0]["fields"]["left.asset_id"] == "MX-01"
    assert maintenance_edge["quality"]["review_required"] is False

    # A separate small time series proves the analytics layer works over the
    # same lineage-shaped evidence rows and does not make a causal claim.
    analytics = analyze_evidence_rows([
        {
            "fields": {
                "left.event_time": f"2026-08-01T0{index}:00:00Z",
                "left.output": index * 10,
                "right.downtime": index * 2,
            },
            "lineage": [{"source_id": "production", "row_id": str(index)}],
        }
        for index in range(8)
    ])
    assert analytics["relationships"]
    assert analytics["causation"]["causal_confidence"] == 0.0


def test_long_form_unit_and_timezone_normalization_is_auditable_before_joining():
    normalized = normalize_operational_evidence_row(
        {
            "Machine": "MX-01",
            "Timestamp": "2026-08-01T07:00:00-07:00",
            "Metric": "Bearing temperature",
            "Value": "86",
            "Unit": "F",
        }
    )

    assert normalized.normalized_row["asset_id"] == "MX-01"
    assert normalized.normalized_row["unit"] == "degC"
    assert round(float(normalized.normalized_row["value"]), 1) == 30.0
    assert normalized.timestamp.canonical_timestamp.endswith("Z")


if __name__ == "__main__":
    test_tsv_and_jsonl_flow_into_multi_source_lineage_evidence_and_statistics()
    test_long_form_unit_and_timezone_normalization_is_auditable_before_joining()
    print("evidence pipeline integration tests passed")
