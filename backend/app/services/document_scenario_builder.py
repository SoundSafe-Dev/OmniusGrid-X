"""
Document Scenario Builder

Converts a parsed PDF/DOCX structure + DocumentDomainMapping into
CorrelationScenario objects for the correlation AI engine, mirroring
``spreadsheet_scenario_builder`` for workbooks.

Modes:
- "section" (default): one scenario per section/page; cross-section
  CrossDomainLinks are created between sections sharing a key.
- "document": a single scenario for the whole document (all mapped domains).
- "table": one scenario per extracted table.
"""

from typing import Dict, List, Iterator, Optional, Any
from datetime import datetime, timezone

from app.models.domain_interaction import (
    DomainType,
    OperationalMetric,
    CrossDomainLink,
    CorrelationScenario,
)
from app.services.document_domain_mapper import (
    map_document_domains,
    map_section_to_domain,
    DocumentDomainMapping,
)
from app.services.shared_key_detector import extract_keys_from_text


DEFAULT_MAX_DOCUMENT_SCENARIOS = 5000

_SEVERITY_TERMS = {
    "critical": 0.9, "severe": 0.9, "emergency": 0.95, "failure": 0.85,
    "failed": 0.85, "non-conformance": 0.7, "noncompliance": 0.7,
    "warning": 0.5, "delayed": 0.5, "degraded": 0.5, "overdue": 0.6,
    "violation": 0.75, "incident": 0.7, "defect": 0.6,
    "normal": 0.15, "passed": 0.15, "ok": 0.15, "compliant": 0.15,
}


def _severity_from_text(text: str) -> float:
    if not text:
        return 0.2
    low = text.lower()
    sev = 0.2
    for term, value in _SEVERITY_TERMS.items():
        if term in low:
            sev = max(sev, value)
    return sev


def _section_text(section: Dict[str, Any]) -> str:
    parts: List[str] = []
    if section.get("text"):
        parts.append(str(section["text"]))
    parts.extend(section.get("paragraphs") or [])
    for table in section.get("tables") or []:
        for row in table:
            parts.append(" ".join(str(c) for c in row))
    return "\n".join(parts)


def _section_payload(section: Dict[str, Any], domain: DomainType,
                     max_chars: int = 4000) -> Dict[str, Any]:
    text = _section_text(section)
    return {
        "heading": section.get("heading") or (section.get("headers") or [None])[0],
        "section_id": section.get("section_id", section.get("page_num")),
        "domain": domain.value,
        "text_excerpt": text[:max_chars],
        "table_count": len(section.get("tables") or []),
        "shared_keys": section.get("shared_keys") or extract_keys_from_text(text),
    }


def _endpoint(domain: DomainType, source_id: str, sec_id: Any) -> str:
    return f"/intake/document/{domain.value.lower()}/{source_id}/sec-{sec_id}"


def _get_sections(structure: Dict[str, Any]) -> List[Dict[str, Any]]:
    sections = structure.get("sections")
    if sections is None:
        sections = structure.get("pages") or []
    return sections


def build_scenarios(
    structure: Dict[str, Any],
    mapping: Optional[DocumentDomainMapping] = None,
    mode: str = "section",
    source_id: str = "intake",
    max_scenarios: int = DEFAULT_MAX_DOCUMENT_SCENARIOS,
) -> Iterator[CorrelationScenario]:
    """Build CorrelationScenario objects from a parsed document structure."""
    if mapping is None:
        mapping = map_document_domains(structure)
    if not mapping.section_domains:
        return

    sections = _get_sections(structure)

    if mode == "document":
        yield from _build_document_mode(sections, mapping, source_id)
    elif mode == "table":
        yield from _build_table_mode(sections, source_id, max_scenarios)
    else:
        yield from _build_section_mode(sections, mapping, source_id, max_scenarios)


def _build_links(domains: List[DomainType], interaction_key: str,
                 severity: float) -> List[CrossDomainLink]:
    links: List[CrossDomainLink] = []
    for i in range(len(domains) - 1):
        links.append(CrossDomainLink(
            source_domain=domains[i],
            target_domain=domains[i + 1],
            interaction_key=interaction_key,
            severity_impact=round(min(max(severity, 0.0), 1.0), 2),
            correlation_type="document_reference",
        ))
    return links


def _build_section_mode(sections, mapping: DocumentDomainMapping, source_id: str,
                        max_scenarios: int) -> Iterator[CorrelationScenario]:
    # Group sections by shared key to build cross-section links.
    key_groups: Dict[str, List[Dict[str, Any]]] = {}
    standalone: List[Dict[str, Any]] = []

    for idx, section in enumerate(sections):
        sec_id = section.get("section_id", section.get("page_num", idx))
        if sec_id not in mapping.section_domains:
            continue
        keys = section.get("shared_keys") or extract_keys_from_text(_section_text(section))
        section["_resolved_id"] = sec_id
        if keys:
            for k in keys:
                key_groups.setdefault(k, []).append(section)
        else:
            standalone.append(section)

    count = 0
    emitted_section_ids = set()

    # Cross-section scenarios linked by a shared key.
    for key, grp in key_groups.items():
        if count >= max_scenarios:
            return
        # Deduplicate sections within group.
        uniq = {s["_resolved_id"]: s for s in grp}.values()
        domains: List[DomainType] = []
        metrics: List[OperationalMetric] = []
        max_sev = 0.2
        for section in uniq:
            sec_id = section["_resolved_id"]
            domain = mapping.section_domains[sec_id]
            if domain not in domains:
                domains.append(domain)
            text = _section_text(section)
            max_sev = max(max_sev, _severity_from_text(text))
            metrics.append(OperationalMetric(
                endpoint=_endpoint(domain, source_id, sec_id),
                payload_snapshot=_section_payload(section, domain),
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            emitted_section_ids.add(sec_id)
        links = _build_links(domains, str(key), max_sev) if len(domains) >= 2 else []
        yield CorrelationScenario(
            scenario_id=f"{source_id}-docsec-{count:06d}",
            active_domains=domains,
            domain_links=links,
            ingested_metrics=metrics,
        )
        count += 1

    # Standalone sections (no shared key) for full coverage.
    for section in standalone:
        if count >= max_scenarios:
            return
        sec_id = section["_resolved_id"]
        domain = mapping.section_domains[sec_id]
        text = _section_text(section)
        yield CorrelationScenario(
            scenario_id=f"{source_id}-docsec-{count:06d}",
            active_domains=[domain],
            domain_links=[],
            ingested_metrics=[OperationalMetric(
                endpoint=_endpoint(domain, source_id, sec_id),
                payload_snapshot=_section_payload(section, domain),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )],
        )
        count += 1


def _build_document_mode(sections, mapping: DocumentDomainMapping,
                         source_id: str) -> Iterator[CorrelationScenario]:
    domains: List[DomainType] = []
    metrics: List[OperationalMetric] = []
    max_sev = 0.2
    for idx, section in enumerate(sections):
        sec_id = section.get("section_id", section.get("page_num", idx))
        if sec_id not in mapping.section_domains:
            continue
        domain = mapping.section_domains[sec_id]
        if domain not in domains:
            domains.append(domain)
        text = _section_text(section)
        max_sev = max(max_sev, _severity_from_text(text))
        metrics.append(OperationalMetric(
            endpoint=_endpoint(domain, source_id, sec_id),
            payload_snapshot=_section_payload(section, domain),
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))
    links = _build_links(domains, source_id, max_sev)
    yield CorrelationScenario(
        scenario_id=f"{source_id}-doc-000000",
        active_domains=domains,
        domain_links=links,
        ingested_metrics=metrics,
    )


def _build_table_mode(sections, source_id: str,
                      max_scenarios: int) -> Iterator[CorrelationScenario]:
    count = 0
    for idx, section in enumerate(sections):
        sec_id = section.get("section_id", section.get("page_num", idx))
        for t_idx, table in enumerate(section.get("tables") or []):
            if count >= max_scenarios:
                return
            domain = map_section_to_domain({"tables": [table],
                                            "heading": section.get("heading")})
            if domain is None:
                continue
            blob = " ".join(" ".join(str(c) for c in row) for row in table)
            yield CorrelationScenario(
                scenario_id=f"{source_id}-doctbl-{count:06d}",
                active_domains=[domain],
                domain_links=[],
                ingested_metrics=[OperationalMetric(
                    endpoint=_endpoint(domain, source_id, f"{sec_id}-t{t_idx}"),
                    payload_snapshot={
                        "section_id": sec_id,
                        "table_index": t_idx,
                        "domain": domain.value,
                        "rows": table[:50],
                        "shared_keys": extract_keys_from_text(blob),
                    },
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )],
            )
            count += 1
