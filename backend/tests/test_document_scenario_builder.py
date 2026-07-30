"""
Unit tests for document_scenario_builder.

The contract under test: "section" mode groups sections that share a key into
one scenario each and emits the remaining sections standalone, "document" mode
emits a single scenario spanning the document, and "table" mode emits one
scenario per table it can map to a domain.

These tests were rewritten on 2026-07-30. The originals were written against a
class-based API (DocumentScenarioBuilder().build(...)) that the converged merge
42ed66d8 replaced with a generator taking a DocumentDomainMapping instead of a
bare {section_id: domain} dict, and they asserted on ``scenario.shared_keys``,
which now lives in each metric's payload_snapshot. The original intent (the
three modes, and shared-key grouping) is kept.
"""

from app.models.domain_interaction import DomainType
from app.services.document_domain_mapper import DocumentDomainMapping
from app.services.document_scenario_builder import build_scenarios


def _section(section_id, heading, paragraphs=None, tables=None):
    return {
        "section_id": section_id,
        "heading": heading,
        "paragraphs": paragraphs or [],
        "tables": tables or [],
    }


def _shared_keys(scenario):
    keys = set()
    for metric in scenario.ingested_metrics:
        keys.update(metric.payload_snapshot.get("shared_keys") or [])
    return keys


def test_section_mode_emits_sections_with_no_shared_key_standalone():
    structure = {"sections": [
        _section(0, "Maintenance Report", ["Routine inspection"]),
        _section(1, "Quality Audit", ["Sampling complete"]),
    ]}
    mapping = DocumentDomainMapping({0: DomainType.MNT, 1: DomainType.QUA}, [])

    scenarios = list(build_scenarios(structure, mapping, mode="section", source_id="doc1"))

    assert [s.scenario_id for s in scenarios] == ["doc1-docsec-000000", "doc1-docsec-000001"]
    assert scenarios[0].active_domains == [DomainType.MNT]
    assert scenarios[1].active_domains == [DomainType.QUA]
    # Standalone sections have nothing to link to.
    assert all(s.domain_links == [] for s in scenarios)


def test_section_mode_groups_sections_that_share_a_key_into_one_scenario():
    structure = {"sections": [
        _section(0, "Production", ["Order PO-123 shipped"]),
        _section(1, "Logistics", ["Order PO-123 received"]),
    ]}
    mapping = DocumentDomainMapping({0: DomainType.PROD, 1: DomainType.LOG}, [])

    scenarios = list(build_scenarios(structure, mapping, mode="section", source_id="doc1"))

    assert len(scenarios) == 1
    assert set(scenarios[0].active_domains) == {DomainType.PROD, DomainType.LOG}
    assert "PO-123" in _shared_keys(scenarios[0])
    assert [link.interaction_key for link in scenarios[0].domain_links] == ["PO-123"]
    assert scenarios[0].domain_links[0].correlation_type == "document_reference"


def test_a_grouped_scenario_takes_the_severest_wording_in_the_group():
    structure = {"sections": [
        _section(0, "Production", ["Order PO-123 normal"]),
        _section(1, "Logistics", ["Order PO-123 critical failure"]),
    ]}
    mapping = DocumentDomainMapping({0: DomainType.PROD, 1: DomainType.LOG}, [])

    scenario = next(iter(build_scenarios(structure, mapping, mode="section", source_id="doc1")))

    assert scenario.domain_links[0].severity_impact == 0.9


def test_document_mode_emits_a_single_scenario_spanning_the_document():
    structure = {"sections": [
        _section(0, "Maintenance", ["Inspection"]),
        _section(1, "Quality", ["Audit"]),
    ]}
    mapping = DocumentDomainMapping({0: DomainType.MNT, 1: DomainType.QUA}, [])

    scenarios = list(build_scenarios(structure, mapping, mode="document", source_id="doc1"))

    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "doc1-doc-000000"
    assert set(scenarios[0].active_domains) == {DomainType.MNT, DomainType.QUA}
    assert len(scenarios[0].ingested_metrics) == 2


def test_table_mode_emits_one_scenario_per_mapped_table():
    structure = {"sections": [
        _section(0, "Maintenance Data",
                 tables=[[["asset_id", "status"], ["ASSET-001", "failed"]]]),
    ]}
    mapping = DocumentDomainMapping({0: DomainType.MNT}, [])

    scenarios = list(build_scenarios(structure, mapping, mode="table", source_id="doc1"))

    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "doc1-doctbl-000000"
    assert scenarios[0].ingested_metrics[0].payload_snapshot["table_index"] == 0


def test_max_scenarios_caps_the_output():
    structure = {"sections": [
        _section(i, f"Maintenance {i}", [f"Inspection {i}"]) for i in range(5)
    ]}
    mapping = DocumentDomainMapping({i: DomainType.MNT for i in range(5)}, [])

    scenarios = list(build_scenarios(structure, mapping, mode="section",
                                     source_id="doc1", max_scenarios=2))

    assert len(scenarios) == 2


def test_pages_are_read_when_a_structure_has_no_sections_key():
    structure = {"pages": [{"page_num": 0, "heading": "Maintenance",
                            "paragraphs": ["Inspection"], "tables": []}]}
    mapping = DocumentDomainMapping({0: DomainType.MNT}, [])

    scenarios = list(build_scenarios(structure, mapping, mode="section", source_id="doc1"))

    assert len(scenarios) == 1


def test_an_empty_mapping_yields_nothing():
    structure = {"sections": [_section(0, "Maintenance", ["Inspection"])]}

    scenarios = list(build_scenarios(structure, DocumentDomainMapping({}, []), source_id="doc1"))

    assert scenarios == []
