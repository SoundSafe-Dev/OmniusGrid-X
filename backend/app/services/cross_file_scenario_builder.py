"""
Cross-File Scenario Builder

Builds CorrelationScenario objects that link MULTIPLE intake files/data sources
by their shared keys. This is the cross-file analogue of the spreadsheet
cross-tab builder: instead of linking tabs within one workbook, it links whole
documents/spreadsheets/images that reference the same asset_id, order number,
date, etc.

A "data source" descriptor is a normalized dict:
    {
      "source_id": str,
      "data_type": "spreadsheet"|"report"|"image"|"document",
      "file_name": str,
      "domains": [DomainType.value, ...],   # domains present in the source
      "keys": [str, ...],                   # normalized shared keys
      "summary": {...},                     # small payload snapshot
    }

The builder reuses ``shared_key_detector.auto_detect_correlation_groups`` and
supports manual key overrides.
"""

from typing import Dict, List, Iterator, Optional, Any
from datetime import datetime, timezone

from app.models.domain_interaction import (
    DomainType,
    OperationalMetric,
    CrossDomainLink,
    CorrelationScenario,
)
from app.services.shared_key_detector import (
    auto_detect_correlation_groups,
    normalize_key,
)


def _coerce_domain(value: Any) -> Optional[DomainType]:
    if isinstance(value, DomainType):
        return value
    try:
        return DomainType(value)
    except Exception:
        return None


def _source_metric(source: Dict[str, Any], domain: DomainType,
                   shared_keys: List[str]) -> OperationalMetric:
    return OperationalMetric(
        endpoint=f"/intake/crossfile/{domain.value.lower()}/{source.get('source_id')}",
        payload_snapshot={
            "source_id": source.get("source_id"),
            "file_name": source.get("file_name"),
            "data_type": source.get("data_type"),
            "domain": domain.value,
            "matched_keys": shared_keys,
            "summary": source.get("summary", {}),
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def build_cross_file_scenarios(
    data_sources: List[Dict[str, Any]],
    manual_keys: Optional[List[str]] = None,
    source_id: str = "cross-file",
) -> Iterator[CorrelationScenario]:
    """
    Build cross-file CorrelationScenarios.

    Each connected group of sources (linked by >=1 shared key) becomes one
    scenario. Domains are aggregated across all sources in the group, and
    pairwise CrossDomainLinks are created keyed on the group's shared keys.
    """
    # Normalize source descriptors.
    normalized_sources = []
    for s in data_sources:
        normalized_sources.append({
            **s,
            "source_id": str(s.get("source_id")),
            "keys": [normalize_key(k) for k in (s.get("keys") or []) if k],
            "domains": s.get("domains") or [],
        })

    groups = auto_detect_correlation_groups(normalized_sources, manual_keys=manual_keys)
    sources_by_id = {s["source_id"]: s for s in normalized_sources}

    count = 0
    for group in groups:
        shared_keys = group["shared_keys"]
        group_sources = [sources_by_id[sid] for sid in group["source_ids"]
                         if sid in sources_by_id]

        # Build domain list + metrics. Each source contributes its domains.
        domains: List[DomainType] = []
        metrics: List[OperationalMetric] = []
        for source in group_sources:
            source_domains = [d for d in (_coerce_domain(v) for v in source["domains"]) if d]
            if not source_domains:
                continue
            for domain in source_domains:
                if domain not in domains:
                    domains.append(domain)
                metrics.append(_source_metric(source, domain, shared_keys))

        if len(domains) < 1 or not metrics:
            continue

        interaction_key = shared_keys[0] if shared_keys else source_id
        links: List[CrossDomainLink] = []
        for i in range(len(domains) - 1):
            links.append(CrossDomainLink(
                source_domain=domains[i],
                target_domain=domains[i + 1],
                interaction_key=str(interaction_key),
                severity_impact=0.5,
                correlation_type="cross_file",
            ))

        yield CorrelationScenario(
            scenario_id=f"{source_id}-grp-{count:06d}",
            active_domains=domains,
            domain_links=links,
            ingested_metrics=metrics,
        )
        count += 1
