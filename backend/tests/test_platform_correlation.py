"""Tests for platform correlation-source shaping (correlation foundation).

The DB-bound providers/endpoint are exercised via make up; here we test the pure
shaping (ProviderResult -> engine-compatible processed_data) and the registry.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.platform_correlation import (
    ProviderResult,
    available_source_types,
    get_provider,
    telemetry_rows_to_records,
)


def test_processed_data_is_engine_shaped():
    result = ProviderResult(
        file_name="telemetry-a1",
        records=[{"asset_id": "a1", "metric_name": "audio_rms", "value": 0.3, "time": "t"}],
        columns=["asset_id", "metric_name", "value", "time"],
        shared_keys=["asset_id", "metric_name", "time"],
    )
    pd = result.to_processed_data()
    # Matches build_source_descriptor's spreadsheet path: shared_keys + tabs[].column_names/sample_data
    assert pd["shared_keys"] == ["asset_id", "metric_name", "time"]
    assert len(pd["tabs"]) == 1
    assert pd["tabs"][0]["column_names"] == ["asset_id", "metric_name", "value", "time"]
    assert pd["tabs"][0]["sample_data"][0]["metric_name"] == "audio_rms"


def test_sample_data_is_capped():
    records = [{"asset_id": "a", "i": i} for i in range(500)]
    pd = ProviderResult("x", records, ["asset_id", "i"], ["asset_id"]).to_processed_data()
    assert len(pd["tabs"][0]["sample_data"]) == 200
    assert pd["tabs"][0]["row_count"] == 500


def test_registry_lists_three_domains():
    types = {s["source_type"] for s in available_source_types()}
    assert types == {"asset_telemetry", "yard", "transportation", "erp"}


def test_flatten_erp_entity_keeps_scalars_only():
    from app.services.platform_correlation import flatten_erp_entity

    e = SimpleNamespace(
        entity_type="PurchaseOrder", entity_id="PO-1", source_system="netsuite",
        entity_data={"amount": 120.5, "vendor": "ACME", "lines": [{"x": 1}], "meta": {"y": 2}},
    )
    rec = flatten_erp_entity(e)
    assert rec["entity_id"] == "PO-1" and rec["amount"] == 120.5 and rec["vendor"] == "ACME"
    assert "lines" not in rec and "meta" not in rec  # nested structures dropped


def test_get_provider_resolves_and_rejects():
    assert get_provider("asset_telemetry") is not None
    assert get_provider("erp") is not None
    assert get_provider("nope") is None


def test_telemetry_records_carry_sensor_class_context():
    # (task B16) audio/video/machinery modality becomes a correlation dimension.
    row = SimpleNamespace(
        asset_id="asset-6", metric_name="audio_rms", value=0.3, unit=None,
        packml_state="Execute", time=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )
    asset = SimpleNamespace(name="Acoustic Monitor", sensor_class="audio", asset_type=None)
    records = telemetry_rows_to_records([row], asset)
    assert records[0]["asset_name"] == "Acoustic Monitor"
    assert records[0]["sensor_class"] == "audio"
    assert records[0]["metric_name"] == "audio_rms"


def test_sensor_class_falls_back_to_asset_type():
    row = SimpleNamespace(
        asset_id="a", metric_name="vibration_rms", value=2.0, unit="mm/s",
        packml_state=None, time=None,
    )
    asset = SimpleNamespace(
        name="Vib", sensor_class=None,
        asset_type=SimpleNamespace(sensor_class="machinery"),
    )
    records = telemetry_rows_to_records([row], asset)
    assert records[0]["sensor_class"] == "machinery"
