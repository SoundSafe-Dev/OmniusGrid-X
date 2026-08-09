"""
Unit tests for document_domain_mapper.
"""

import pytest
from app.models.domain_interaction import DomainType
from app.services.document_domain_mapper import (
    map_section_to_domain,
    map_document_domains,
    DocumentDomainMapping,
)


def test_map_section_to_domain_header():
    section = {"heading": "Maintenance Report", "paragraphs": ["Some text"], "tables": []}
    domain = map_section_to_domain(section)
    assert domain == DomainType.MNT


def test_map_section_to_domain_table_content():
    section = {
        "heading": "General",
        "paragraphs": [],
        "tables": [[["asset_id", "status"], ["ASSET-001", "failed"]]],
    }
    domain = map_section_to_domain(section)
    assert domain == DomainType.MNT


def test_map_section_to_domain_body_text():
    section = {
        "heading": "Overview",
        "paragraphs": ["Quality inspection found defects in the production line"],
        "tables": [],
    }
    domain = map_section_to_domain(section)
    assert domain == DomainType.QUA


def test_map_section_to_domain_none():
    section = {"heading": "Random", "paragraphs": ["No keywords"], "tables": []}
    domain = map_section_to_domain(section)
    assert domain is None


def test_map_document_domains():
    structure = {
        "sections": [
            {"section_id": 0, "heading": "Maintenance Report", "paragraphs": [], "tables": []},
            {"section_id": 1, "heading": "Quality Audit", "paragraphs": [], "tables": []},
            {"section_id": 2, "heading": "Random", "paragraphs": [], "tables": []},
        ]
    }
    mapping = map_document_domains(structure)
    assert isinstance(mapping, DocumentDomainMapping)
    assert mapping.section_domains[0] == DomainType.MNT
    assert mapping.section_domains[1] == DomainType.QUA
    assert 2 in mapping.context_only_sections
    assert DomainType.MNT in mapping.active_domains
    assert DomainType.QUA in mapping.active_domains


def test_map_document_domains_pdf_pages():
    structure = {
        "pages": [
            {"page_num": 1, "headers": ["Safety Report"], "text": "Incident details", "tables": []},
            {"page_num": 2, "headers": ["Production"], "text": "Output metrics", "tables": []},
        ]
    }
    mapping = map_document_domains(structure)
    assert mapping.section_domains[1] == DomainType.SAF
    assert mapping.section_domains[2] == DomainType.PROD


# ------------------------------------------------------------------------------------
# FS-415. `test_map_section_to_domain_table_content` had NEVER PASSED — it was written on
# 2026-06-08 in the same commit as the mapper, expecting an `asset_id` / `failed` table to
# resolve to maintenance, against a keyword map that contained no asset or failure word at
# all. It sat red for two months, read as another lane's problem.
#
# The test's expectation was right and the vocabulary was incomplete, and the consequence
# was not a red test: `document_scenario_builder` does `if domain is None: continue`, so a
# table keyed on asset_id produced no correlation scenario while the page still reported
# as processed. Silent omission, which is the shape this repository keeps finding.
#
# Widening a keyword list can misroute, so these pin the property that makes it safe.

def test_a_stronger_signal_still_wins_over_the_new_asset_words():
    """Scoring takes the HIGHEST-scoring domain, not the first hit.

    Without this, adding `asset_id` to maintenance would quietly pull quality, production
    and energy sheets into MNT — trading a silent omission for a silent misroute, which is
    worse because it produces a confident wrong answer instead of nothing.
    """
    section = {
        "heading": "General",
        "paragraphs": [],
        "tables": [[["asset_id", "defect", "inspection", "scrap"],
                    ["ASSET-001", "3", "failed", "2"]]],
    }
    assert map_section_to_domain(section) == DomainType.QUA


def test_an_asset_keyed_table_no_longer_resolves_to_nothing():
    """The case the builder was skipping."""
    section = {
        "heading": "General",
        "paragraphs": [],
        "tables": [[["asset_id", "status"], ["ASSET-001", "failed"]]],
    }
    assert map_section_to_domain(section) is not None


def test_an_unrelated_table_still_resolves_to_nothing():
    """The widening must not turn the mapper into one that always answers. A table with no
    operational vocabulary has no domain, and saying so is the correct answer."""
    section = {
        "heading": "General",
        "paragraphs": [],
        "tables": [[["colour", "notes"], ["blue", "see attached"]]],
    }
    assert map_section_to_domain(section) is None
