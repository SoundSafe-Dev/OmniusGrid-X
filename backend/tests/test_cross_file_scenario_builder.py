"""
Unit tests for cross_file_scenario_builder.
"""

import pytest
from app.models.domain_interaction import DomainType
from app.services.cross_file_scenario_builder import (
    build_cross_file_scenarios,
    CrossFileScenarioBuilder,
)


def test_build_cross_file_scenarios_auto():
    descriptors = [
        {
            "source_id": "A",
            "file_name": "PO-123-report.pdf",
            "data_type": "pdf",
            "domains": [DomainType.PROD],
            "keys": ["PO-123", "ASSET-456"],
        },
        {
            "source_id": "B",
            "file_name": "ASSET-456-maintenance.docx",
            "data_type": "docx",
            "domains": [DomainType.MNT],
            "keys": ["ASSET-456"],
        },
    ]
    scenarios = build_cross_file_scenarios(descriptors, manual_keys=None, source_id="test")
    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "test-group-0"
    assert set(scenarios[0].source_ids) == {"A", "B"}
    assert "ASSET-456" in scenarios[0].shared_keys


def test_build_cross_file_scenarios_manual():
    descriptors = [
        {
            "source_id": "A",
            "file_name": "file1.pdf",
            "data_type": "pdf",
            "domains": [DomainType.PROD],
            "keys": ["KEY1"],
        },
        {
            "source_id": "B",
            "file_name": "file2.docx",
            "data_type": "docx",
            "domains": [DomainType.LOG],
            "keys": ["KEY2"],
        },
    ]
    scenarios = build_cross_file_scenarios(
        descriptors, manual_keys=["MANUAL"], source_id="test"
    )
    # Manual key not in source keys, so no scenarios
    assert len(scenarios) == 0

    # Add manual key to sources
    descriptors[0]["keys"].append("MANUAL")
    descriptors[1]["keys"].append("MANUAL")
    scenarios = build_cross_file_scenarios(
        descriptors, manual_keys=["MANUAL"], source_id="test"
    )
    assert len(scenarios) == 1
    assert "MANUAL" in scenarios[0].shared_keys


def test_build_cross_file_scenarios_no_overlap():
    descriptors = [
        {
            "source_id": "A",
            "file_name": "file1.pdf",
            "data_type": "pdf",
            "domains": [DomainType.PROD],
            "keys": ["KEY1"],
        },
        {
            "source_id": "B",
            "file_name": "file2.docx",
            "data_type": "docx",
            "domains": [DomainType.LOG],
            "keys": ["KEY2"],
        },
    ]
    scenarios = build_cross_file_scenarios(descriptors, manual_keys=None, source_id="test")
    assert len(scenarios) == 0


def test_cross_file_scenario_builder_class():
    builder = CrossFileScenarioBuilder()
    descriptors = [
        {
            "source_id": "A",
            "file_name": "file1.pdf",
            "data_type": "pdf",
            "domains": [DomainType.PROD],
            "keys": ["KEY1"],
        },
        {
            "source_id": "B",
            "file_name": "file2.docx",
            "data_type": "docx",
            "domains": [DomainType.LOG],
            "keys": ["KEY1"],
        },
    ]
    scenarios = builder.build(descriptors, manual_keys=None, source_id="test")
    assert len(scenarios) == 1
