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
