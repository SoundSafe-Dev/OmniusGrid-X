"""Tests for platform correlation-source shaping (correlation foundation).

The DB-bound providers/endpoint are exercised via make up; here we test the pure
shaping (ProviderResult -> engine-compatible processed_data) and the registry.
"""

from app.services.platform_correlation import (
    ProviderResult,
    available_source_types,
    get_provider,
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
    assert types == {"asset_telemetry", "yard", "transportation"}


def test_get_provider_resolves_and_rejects():
    assert get_provider("asset_telemetry") is not None
    assert get_provider("nope") is None
