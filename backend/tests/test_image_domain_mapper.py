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
    extractions = [
        {"image_id": 0, "text": "Safety hazard detected", "metadata": {}},
        {"image_id": 1, "text": "Maintenance required", "metadata": {}},
        {"image_id": 2, "text": "No keywords", "metadata": {}},
    ]
    domains = map_image_domains(extractions)
    assert domains[0] == DomainType.SAF
    assert domains[1] == DomainType.MNT
    assert domains[2] is None
