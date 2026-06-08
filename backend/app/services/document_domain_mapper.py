"""
Document Domain Mapper

Maps PDF/DOCX document sections (pages, headings, tables) to OmniusGrid
DomainType values so documents can be converted into CorrelationScenarios,
mirroring ``spreadsheet_domain_mapper`` for workbooks.

Resolution order per section:
1. Header/heading keyword match (analogous to spreadsheet tab names).
2. Table column/cell keyword match.
3. Section body-text keyword match.
Sections that cannot be mapped are flagged context-only.
"""

from typing import Dict, List, Any, Optional

from app.models.domain_interaction import DomainType
from app.services.spreadsheet_domain_mapper import (
    TAB_NAME_DOMAIN_MAP,
    COLUMN_KEYWORD_DOMAIN_MAP,
    _normalize,
)


# Header phrase hints that strongly imply a domain (checked as substrings of
# the normalized heading text). Reuses tab-name map plus document-specific ones.
HEADER_DOMAIN_HINTS: Dict[str, DomainType] = {
    "maintenancereport": DomainType.MNT,
    "workorder": DomainType.MNT,
    "qualityaudit": DomainType.QUA,
    "inspectionreport": DomainType.QUA,
    "incidentreport": DomainType.SAF,
    "safetyreport": DomainType.SAF,
    "complianceaudit": DomainType.COMP,
    "auditfindings": DomainType.RGA,
    "productionreport": DomainType.PROD,
    "shiftreport": DomainType.PROD,
    "logisticsreport": DomainType.LOG,
    "shipmentmanifest": DomainType.LOG,
    "inventoryreport": DomainType.WHS,
    "energyreport": DomainType.ENG,
    "financialsummary": DomainType.FIN,
    "supplierreport": DomainType.SUP,
}


def _match_header(heading: str) -> Optional[DomainType]:
    norm = _normalize(heading)
    if not norm:
        return None
    # Document-specific header hints first.
    for key, domain in HEADER_DOMAIN_HINTS.items():
        if key in norm:
            return domain
    # Reuse spreadsheet tab-name mapping (covers domain names appearing in headers).
    if norm in TAB_NAME_DOMAIN_MAP:
        return TAB_NAME_DOMAIN_MAP[norm]
    for key, domain in TAB_NAME_DOMAIN_MAP.items():
        if key in norm or norm in key:
            return domain
    return None


def _match_keywords(blob: str) -> Optional[DomainType]:
    text = _normalize(blob)
    if not text:
        return None
    best_domain: Optional[DomainType] = None
    best_score = 0
    for domain, keywords in COLUMN_KEYWORD_DOMAIN_MAP.items():
        score = sum(1 for kw in keywords if _normalize(kw) in text)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain if best_score > 0 else None


def map_section_to_domain(section: Dict[str, Any]) -> Optional[DomainType]:
    """
    Map a single document section to a DomainType.

    Section shape (PDF page or DOCX section):
      {"heading"|"headers", "paragraphs"|"text", "tables": [[...]], ...}
    """
    # 1. Header match.
    heading = section.get("heading")
    headers = section.get("headers") or ([heading] if heading else [])
    for h in headers:
        domain = _match_header(str(h))
        if domain:
            return domain

    # 2. Table content match.
    table_blob_parts: List[str] = []
    for table in section.get("tables") or []:
        for row in table:
            table_blob_parts.append(" ".join(str(c) for c in row))
    if table_blob_parts:
        domain = _match_keywords(" ".join(table_blob_parts))
        if domain:
            return domain

    # 3. Body text match.
    body = section.get("text")
    if not body:
        body = " ".join(section.get("paragraphs") or [])
    if body:
        domain = _match_keywords(str(body))
        if domain:
            return domain

    return None


def map_document_domains(structure: Dict[str, Any]) -> "DocumentDomainMapping":
    """
    Map all sections/pages of a parsed document to domains.

    Accepts the output of ``pdf_parser.parse_pdf_structure`` (uses "pages")
    or ``docx_parser.parse_docx_structure`` (uses "sections").
    """
    sections = structure.get("sections")
    if sections is None:
        sections = structure.get("pages") or []

    section_domains: Dict[int, DomainType] = {}
    context_only: List[int] = []

    for idx, section in enumerate(sections):
        sec_id = section.get("section_id", section.get("page_num", idx))
        domain = map_section_to_domain(section)
        if domain is not None:
            section_domains[sec_id] = domain
        else:
            context_only.append(sec_id)

    return DocumentDomainMapping(section_domains=section_domains,
                                 context_only_sections=context_only)


class DocumentDomainMapping:
    """Result of mapping a document's sections to domains."""

    def __init__(self, section_domains: Dict[int, DomainType],
                 context_only_sections: List[int]):
        self.section_domains = section_domains
        self.context_only_sections = context_only_sections

    @property
    def active_domains(self) -> List[DomainType]:
        seen: List[DomainType] = []
        for domain in self.section_domains.values():
            if domain not in seen:
                seen.append(domain)
        return seen

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_domains": {str(k): v.value for k, v in self.section_domains.items()},
            "context_only_sections": self.context_only_sections,
            "active_domains": [d.value for d in self.active_domains],
        }
