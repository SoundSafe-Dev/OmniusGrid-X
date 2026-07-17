"""
Image Scenario Builder

Converts image text extractions + ImageDomainMapping into CorrelationScenario
objects, mirroring the document/spreadsheet scenario builders.

Modes:
- "image" (default): one scenario per image.
- "batch": a single scenario across all images, with cross-image links for
  images sharing a key.
"""

from typing import Dict, List, Iterator, Optional, Any
from datetime import datetime, timezone

from app.models.domain_interaction import (
    DomainType,
    OperationalMetric,
    CrossDomainLink,
    CorrelationScenario,
)
from app.services.image_domain_mapper import map_image_domains, ImageDomainMapping
from app.services.shared_key_detector import extract_keys_from_text


def _payload(ext: Dict[str, Any], domain: DomainType) -> Dict[str, Any]:
    text = ext.get("extracted_text", "") or ""
    return {
        "image_id": ext.get("image_id"),
        "domain": domain.value,
        "text_excerpt": text[:4000],
        "confidence": ext.get("confidence"),
        "metadata": ext.get("metadata", {}),
        "shared_keys": ext.get("shared_keys") or extract_keys_from_text(text),
        "extraction_method": ext.get("extraction_method"),
    }


def _endpoint(domain: DomainType, source_id: str, image_id: Any) -> str:
    return f"/intake/image/{domain.value.lower()}/{source_id}/img-{image_id}"


def build_scenarios(
    extractions: List[Dict[str, Any]],
    mapping: Optional[ImageDomainMapping] = None,
    mode: str = "image",
    source_id: str = "intake",
) -> Iterator[CorrelationScenario]:
    """Build CorrelationScenario objects from image extractions."""
    # Ensure each extraction has a stable image_id.
    for idx, ext in enumerate(extractions):
        ext.setdefault("image_id", idx)

    if mapping is None:
        mapping = map_image_domains(extractions)
    if not mapping.image_domains:
        return

    if mode == "batch":
        yield from _build_batch_mode(extractions, mapping, source_id)
    else:
        yield from _build_image_mode(extractions, mapping, source_id)


def _build_image_mode(extractions, mapping: ImageDomainMapping,
                      source_id: str) -> Iterator[CorrelationScenario]:
    count = 0
    for ext in extractions:
        image_id = ext["image_id"]
        if image_id not in mapping.image_domains:
            continue
        domain = mapping.image_domains[image_id]
        yield CorrelationScenario(
            scenario_id=f"{source_id}-img-{count:06d}",
            active_domains=[domain],
            domain_links=[],
            ingested_metrics=[OperationalMetric(
                endpoint=_endpoint(domain, source_id, image_id),
                payload_snapshot=_payload(ext, domain),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )],
        )
        count += 1


def _build_batch_mode(extractions, mapping: ImageDomainMapping,
                      source_id: str) -> Iterator[CorrelationScenario]:
    domains: List[DomainType] = []
    metrics: List[OperationalMetric] = []
    # Track keys to build cross-image links.
    key_to_domains: Dict[str, List[DomainType]] = {}

    for ext in extractions:
        image_id = ext["image_id"]
        if image_id not in mapping.image_domains:
            continue
        domain = mapping.image_domains[image_id]
        if domain not in domains:
            domains.append(domain)
        metrics.append(OperationalMetric(
            endpoint=_endpoint(domain, source_id, image_id),
            payload_snapshot=_payload(ext, domain),
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))
        for key in (ext.get("shared_keys") or []):
            key_to_domains.setdefault(key, [])
            if domain not in key_to_domains[key]:
                key_to_domains[key].append(domain)

    links: List[CrossDomainLink] = []
    for key, doms in key_to_domains.items():
        for i in range(len(doms) - 1):
            links.append(CrossDomainLink(
                source_domain=doms[i],
                target_domain=doms[i + 1],
                interaction_key=str(key),
                severity_impact=0.4,
                correlation_type="image_reference",
            ))

    yield CorrelationScenario(
        scenario_id=f"{source_id}-imgbatch-000000",
        active_domains=domains,
        domain_links=links,
        ingested_metrics=metrics,
    )
