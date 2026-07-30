"""
Unit tests for image_domain_mapper.
"""

import pytest
from app.models.domain_interaction import DomainType
from app.services.image_domain_mapper import (
    map_image_to_domain,
    map_image_domains,
)


def test_map_image_to_domain_safety():
    text = "Safety inspection found a hazard in the facility"
    domain = map_image_to_domain(text, metadata={"category": "safety"})
    assert domain == DomainType.SAF


def test_map_image_to_domain_maintenance():
    text = "Asset ASSET-001 requires maintenance due to wear"
    domain = map_image_to_domain(text, metadata={})
    assert domain == DomainType.MNT


def test_map_image_to_domain_quality():
    text = "Quality control inspection shows defects in the product"
    domain = map_image_to_domain(text, metadata={})
    assert domain == DomainType.QUA


def test_map_image_to_domain_none():
    text = "Random text with no domain keywords"
    domain = map_image_to_domain(text, metadata={})
    assert domain is None


def test_map_image_domains():
    # Rewritten 2026-07-30. This asserted `domains[0]` against a plain dict and
    # passed the text under "text". map_image_domains now returns an
    # ImageDomainMapping and reads "extracted_text"; an image it cannot classify
    # is absent from .image_domains and listed in .unmapped_images rather than
    # mapping to None.
    extractions = [
        {"image_id": 0, "extracted_text": "Safety hazard detected", "metadata": {}},
        {"image_id": 1, "extracted_text": "Maintenance required", "metadata": {}},
        {"image_id": 2, "extracted_text": "No keywords", "metadata": {}},
    ]
    mapping = map_image_domains(extractions)
    assert mapping.image_domains == {0: DomainType.SAF, 1: DomainType.MNT}
    assert mapping.unmapped_images == [2]
    assert mapping.active_domains == [DomainType.SAF, DomainType.MNT]
