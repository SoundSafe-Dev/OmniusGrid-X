"""
Unit tests for image_scenario_builder.
"""

import pytest
from app.models.domain_interaction import DomainType
from app.services.image_scenario_builder import (
    build_image_scenarios,
    ImageScenarioBuilder,
)


def test_build_image_scenarios_image_mode():
    extractions = [
        {"image_id": 0, "text": "Safety hazard", "metadata": {}},
        {"image_id": 1, "text": "Maintenance required", "metadata": {}},
    ]
    domains = [DomainType.SAF, DomainType.MNT]
    scenarios = build_image_scenarios(
        extractions, domains, mode="image", source_id="img1"
    )
    assert len(scenarios) == 2
    assert scenarios[0].scenario_id == "img1-image-0"
    assert scenarios[0].active_domains == [DomainType.SAF]
    assert scenarios[1].scenario_id == "img1-image-1"
    assert scenarios[1].active_domains == [DomainType.MNT]


def test_build_image_scenarios_batch_mode():
    extractions = [
        {"image_id": 0, "text": "Safety hazard", "metadata": {}},
        {"image_id": 1, "text": "Maintenance required", "metadata": {}},
    ]
    domains = [DomainType.SAF, DomainType.MNT]
    scenarios = build_image_scenarios(
        extractions, domains, mode="batch", source_id="img1"
    )
    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "img1-batch"
    assert set(scenarios[0].active_domains) == {DomainType.SAF, DomainType.MNT}


def test_build_image_scenarios_with_shared_keys():
    extractions = [
        {"image_id": 0, "text": "Asset ASSET-001", "metadata": {}},
        {"image_id": 1, "text": "Asset ASSET-001", "metadata": {}},
    ]
    domains = [DomainType.MNT, DomainType.MNT]
    scenarios = build_image_scenarios(
        extractions, domains, mode="image", source_id="img1", shared_keys=["ASSET-001"]
    )
    assert len(scenarios) == 2
    assert all("ASSET-001" in s.shared_keys for s in scenarios)


def test_image_scenario_builder_class():
    builder = ImageScenarioBuilder()
    extractions = [{"image_id": 0, "text": "Safety", "metadata": {}}]
    domains = [DomainType.SAF]
    scenarios = builder.build(extractions, domains, mode="image", source_id="img1")
    assert len(scenarios) == 1
