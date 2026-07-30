"""
Unit tests for image_scenario_builder.

The contract under test is the one the module docstring states: "image" mode
emits one scenario per mapped image, and "batch" mode emits a single scenario
spanning every mapped image, with a CrossDomainLink for each key that two
images share.

These tests were rewritten on 2026-07-30. The originals were written against a
class-based API (ImageScenarioBuilder().build(extractions, domains, ...)) that
the converged merge 42ed66d8 replaced with a generator taking an
ImageDomainMapping. Nothing updated them, so the file failed to import and
took the whole default pytest run down with it at collection.
"""

from app.models.domain_interaction import DomainType
from app.services.image_domain_mapper import ImageDomainMapping
from app.services.image_scenario_builder import build_scenarios


def _extraction(image_id, text, **extra):
    return {"image_id": image_id, "extracted_text": text, "metadata": {}, **extra}


def test_image_mode_emits_one_scenario_per_mapped_image():
    extractions = [_extraction(0, "Safety hazard"), _extraction(1, "Maintenance required")]
    mapping = ImageDomainMapping({0: DomainType.SAF, 1: DomainType.MNT}, [])

    scenarios = list(build_scenarios(extractions, mapping, mode="image", source_id="img1"))

    assert [s.scenario_id for s in scenarios] == ["img1-img-000000", "img1-img-000001"]
    assert scenarios[0].active_domains == [DomainType.SAF]
    assert scenarios[1].active_domains == [DomainType.MNT]


def test_batch_mode_emits_a_single_scenario_spanning_every_image():
    extractions = [_extraction(0, "Safety hazard"), _extraction(1, "Maintenance required")]
    mapping = ImageDomainMapping({0: DomainType.SAF, 1: DomainType.MNT}, [])

    scenarios = list(build_scenarios(extractions, mapping, mode="batch", source_id="img1"))

    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "img1-imgbatch-000000"
    assert set(scenarios[0].active_domains) == {DomainType.SAF, DomainType.MNT}
    # One metric per image, not one per scenario.
    assert len(scenarios[0].ingested_metrics) == 2


def test_batch_mode_links_images_that_share_a_key():
    extractions = [
        _extraction(0, "Asset ASSET-001 safety", shared_keys=["ASSET-001"]),
        _extraction(1, "Asset ASSET-001 maintenance", shared_keys=["ASSET-001"]),
    ]
    mapping = ImageDomainMapping({0: DomainType.SAF, 1: DomainType.MNT}, [])

    scenario = next(iter(build_scenarios(extractions, mapping, mode="batch", source_id="img1")))

    assert [link.interaction_key for link in scenario.domain_links] == ["ASSET-001"]
    assert scenario.domain_links[0].correlation_type == "image_reference"
    assert scenario.domain_links[0].source_domain == DomainType.SAF
    assert scenario.domain_links[0].target_domain == DomainType.MNT


def test_unmapped_images_are_skipped_not_emitted_undomained():
    extractions = [_extraction(0, "Safety hazard"), _extraction(1, "Unclassifiable")]
    mapping = ImageDomainMapping({0: DomainType.SAF}, unmapped_images=[1])

    scenarios = list(build_scenarios(extractions, mapping, mode="image", source_id="img1"))

    assert len(scenarios) == 1
    assert scenarios[0].ingested_metrics[0].payload_snapshot["image_id"] == 0


def test_an_empty_mapping_yields_nothing():
    extractions = [_extraction(0, "Safety hazard")]

    scenarios = list(build_scenarios(extractions, ImageDomainMapping({}, [0]), source_id="img1"))

    assert scenarios == []


def test_missing_image_ids_are_assigned_by_position():
    # Callers may hand over extractions with no image_id; the builder assigns
    # one per position so the mapping keys line up.
    extractions = [{"extracted_text": "Safety hazard", "metadata": {}}]
    mapping = ImageDomainMapping({0: DomainType.SAF}, [])

    scenarios = list(build_scenarios(extractions, mapping, source_id="img1"))

    assert len(scenarios) == 1
    assert extractions[0]["image_id"] == 0
