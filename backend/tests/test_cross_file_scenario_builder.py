"""
Unit tests for cross_file_scenario_builder.

The contract under test: each connected group of sources linked by at least one
shared key becomes one scenario, domains are aggregated across the group, and
pairwise CrossDomainLinks are keyed on the group's shared keys.

These tests were rewritten on 2026-07-30. The originals were written against a
class-based API (CrossFileScenarioBuilder().build(...)) that the converged
merge 42ed66d8 replaced with a generator, and they asserted on
``scenario.source_ids`` / ``scenario.shared_keys`` — fields that no longer live
on CorrelationScenario. Both moved into each metric's payload_snapshot as
"source_id" and "matched_keys", so the assertions below read them from there.
The original intent (auto-grouping, manual-key override, no-overlap) is kept.
"""

from app.models.domain_interaction import DomainType
from app.services.cross_file_scenario_builder import build_cross_file_scenarios


def _source(source_id, domains, keys, **extra):
    return {
        "source_id": source_id,
        "file_name": f"{source_id}.pdf",
        "data_type": "document",
        "domains": domains,
        "keys": keys,
        **extra,
    }


def _source_ids(scenario):
    return {m.payload_snapshot["source_id"] for m in scenario.ingested_metrics}


def _matched_keys(scenario):
    keys = set()
    for metric in scenario.ingested_metrics:
        keys.update(metric.payload_snapshot["matched_keys"])
    return keys


def test_sources_sharing_a_key_become_one_scenario():
    sources = [
        _source("A", [DomainType.PROD], ["PO-123", "ASSET-456"]),
        _source("B", [DomainType.MNT], ["ASSET-456"]),
    ]

    scenarios = list(build_cross_file_scenarios(sources, manual_keys=None, source_id="test"))

    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "test-grp-000000"
    assert _source_ids(scenarios[0]) == {"A", "B"}
    assert "ASSET-456" in _matched_keys(scenarios[0])


def test_sources_with_no_key_in_common_do_not_group():
    sources = [
        _source("A", [DomainType.PROD], ["KEY1"]),
        _source("B", [DomainType.LOG], ["KEY2"]),
    ]

    scenarios = list(build_cross_file_scenarios(sources, manual_keys=None, source_id="test"))

    assert scenarios == []


def test_a_manual_key_absent_from_every_source_groups_nothing():
    sources = [
        _source("A", [DomainType.PROD], ["KEY1"]),
        _source("B", [DomainType.LOG], ["KEY2"]),
    ]

    scenarios = list(
        build_cross_file_scenarios(sources, manual_keys=["MANUAL"], source_id="test")
    )

    assert scenarios == []


def test_a_manual_key_present_in_both_sources_groups_them():
    sources = [
        _source("A", [DomainType.PROD], ["KEY1", "MANUAL"]),
        _source("B", [DomainType.LOG], ["KEY2", "MANUAL"]),
    ]

    scenarios = list(
        build_cross_file_scenarios(sources, manual_keys=["MANUAL"], source_id="test")
    )

    assert len(scenarios) == 1
    assert "MANUAL" in _matched_keys(scenarios[0])


def test_a_group_links_its_domains_pairwise_on_the_shared_key():
    sources = [
        _source("A", [DomainType.PROD], ["ASSET-456"]),
        _source("B", [DomainType.MNT], ["ASSET-456"]),
    ]

    scenario = next(iter(build_cross_file_scenarios(sources, source_id="test")))

    assert [link.correlation_type for link in scenario.domain_links] == ["cross_file"]
    assert scenario.domain_links[0].interaction_key == "ASSET-456"
    assert scenario.domain_links[0].source_domain == DomainType.PROD
    assert scenario.domain_links[0].target_domain == DomainType.MNT


def test_domain_strings_are_accepted_not_only_enum_members():
    # Callers upstream hand over DomainType.value strings from JSON.
    sources = [
        _source("A", ["PRODUCTION_OEE"], ["ASSET-456"]),
        _source("B", ["MAINTENANCE"], ["ASSET-456"]),
    ]

    scenarios = list(build_cross_file_scenarios(sources, source_id="test"))

    assert len(scenarios) == 1
    assert set(scenarios[0].active_domains) == {DomainType.PROD, DomainType.MNT}


def test_a_source_with_no_recognisable_domain_contributes_no_metric():
    sources = [
        _source("A", [DomainType.PROD], ["ASSET-456"]),
        _source("B", ["NOT_A_DOMAIN"], ["ASSET-456"]),
    ]

    scenarios = list(build_cross_file_scenarios(sources, source_id="test"))

    assert len(scenarios) == 1
    assert _source_ids(scenarios[0]) == {"A"}
