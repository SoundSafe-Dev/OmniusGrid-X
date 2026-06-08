"""
Unit tests for document_scenario_builder.
"""

import pytest
from app.models.domain_interaction import DomainType
from app.services.document_scenario_builder import (
    build_document_scenarios,
    DocumentScenarioBuilder,
)


def test_build_document_scenarios_section_mode():
    structure = {
        "sections": [
            {
                "section_id": 0,
                "heading": "Maintenance Report",
                "paragraphs": ["Asset ASSET-001 failed"],
                "tables": [],
            },
            {
                "section_id": 1,
                "heading": "Quality Audit",
                "paragraphs": ["Defects found in production"],
                "tables": [],
            },
        ]
    }
    domains = {0: DomainType.MNT, 1: DomainType.QUA}
    scenarios = build_document_scenarios(
        structure, domains, mode="section", source_id="doc1"
    )
    assert len(scenarios) == 2
    assert scenarios[0].scenario_id == "doc1-section-0"
    assert scenarios[0].active_domains == [DomainType.MNT]
    assert scenarios[1].scenario_id == "doc1-section-1"
    assert scenarios[1].active_domains == [DomainType.QUA]


def test_build_document_scenarios_document_mode():
    structure = {
        "sections": [
            {
                "section_id": 0,
                "heading": "Maintenance",
                "paragraphs": [],
                "tables": [],
            },
            {
                "section_id": 1,
                "heading": "Quality",
                "paragraphs": [],
                "tables": [],
            },
        ]
    }
    domains = {0: DomainType.MNT, 1: DomainType.QUA}
    scenarios = build_document_scenarios(
        structure, domains, mode="document", source_id="doc1"
    )
    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "doc1-document"
    assert set(scenarios[0].active_domains) == {DomainType.MNT, DomainType.QUA}


def test_build_document_scenarios_table_mode():
    structure = {
        "sections": [
            {
                "section_id": 0,
                "heading": "Data",
                "paragraphs": [],
                "tables": [[["asset_id", "status"], ["ASSET-001", "failed"]]],
            }
        ]
    }
    domains = {0: DomainType.MNT}
    scenarios = build_document_scenarios(
        structure, domains, mode="table", source_id="doc1"
    )
    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "doc1-table-0"


def test_build_document_scenarios_with_shared_keys():
    structure = {
        "sections": [
            {
                "section_id": 0,
                "heading": "Section A",
                "paragraphs": ["PO-123"],
                "tables": [],
            },
            {
                "section_id": 1,
                "heading": "Section B",
                "paragraphs": ["PO-123"],
                "tables": [],
            },
        ]
    }
    domains = {0: DomainType.PROD, 1: DomainType.LOG}
    scenarios = build_document_scenarios(
        structure, domains, mode="section", source_id="doc1", shared_keys=["PO-123"]
    )
    assert len(scenarios) == 2
    # Both scenarios should have the shared key
    assert all("PO-123" in s.shared_keys for s in scenarios)
