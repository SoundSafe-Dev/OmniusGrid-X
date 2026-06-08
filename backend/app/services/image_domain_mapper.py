"""
Image Domain Mapper

Maps text extracted from images (via ``image_text_extractor``) plus image
metadata to OmniusGrid DomainType values, so images can participate in
correlation scenarios like other intake sources.
"""

from typing import Dict, List, Any, Optional

from app.models.domain_interaction import DomainType
from app.services.spreadsheet_domain_mapper import (
    COLUMN_KEYWORD_DOMAIN_MAP,
    _normalize,
)


# Visual/keyword hints common in operational photos and signage.
IMAGE_KEYWORD_DOMAIN_HINTS: Dict[DomainType, List[str]] = {
    DomainType.SAF: ["danger", "warning", "hazard", "ppe required", "caution",
                     "emergency", "evacuation", "no entry", "high voltage"],
    DomainType.QUA: ["inspection", "defect", "reject", "pass", "fail", "qc",
                     "tolerance", "out of spec"],
    DomainType.MNT: ["gauge", "psi", "rpm", "temperature", "vibration",
                     "lubrication", "work order", "maintenance"],
    DomainType.WHS: ["bin", "rack", "aisle", "pallet", "sku", "putaway", "slot"],
    DomainType.LOG: ["trailer", "dock", "bol", "manifest", "carrier", "seal"],
    DomainType.PROD: ["line", "oee", "cycle", "units", "batch", "run"],
}


def _match_image_keywords(text: str) -> Optional[DomainType]:
    norm = _normalize(text)
    if not norm:
        return None
    best_domain: Optional[DomainType] = None
    best_score = 0
    # Image-specific hints first.
    for domain, keywords in IMAGE_KEYWORD_DOMAIN_HINTS.items():
        score = sum(1 for kw in keywords if _normalize(kw) in norm)
        if score > best_score:
            best_score = score
            best_domain = domain
    if best_score > 0:
        return best_domain
    # Fall back to the shared spreadsheet column keyword map.
    for domain, keywords in COLUMN_KEYWORD_DOMAIN_MAP.items():
        score = sum(1 for kw in keywords if _normalize(kw) in norm)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain if best_score > 0 else None


def map_image_to_domain(extracted_text: str,
                        metadata: Optional[Dict[str, Any]] = None) -> Optional[DomainType]:
    """Map a single image's extracted text (+ metadata) to a DomainType."""
    domain = _match_image_keywords(extracted_text or "")
    if domain:
        return domain
    if metadata:
        meta_blob = " ".join(str(v) for v in metadata.values())
        return _match_image_keywords(meta_blob)
    return None


def map_image_domains(extractions: List[Dict[str, Any]]) -> "ImageDomainMapping":
    """
    Map multiple image extractions to domains.

    Args:
        extractions: list of {"image_id", "extracted_text", "metadata"}
    """
    image_domains: Dict[Any, DomainType] = {}
    unmapped: List[Any] = []
    for idx, ext in enumerate(extractions):
        image_id = ext.get("image_id", idx)
        domain = map_image_to_domain(ext.get("extracted_text", ""), ext.get("metadata"))
        if domain is not None:
            image_domains[image_id] = domain
        else:
            unmapped.append(image_id)
    return ImageDomainMapping(image_domains=image_domains, unmapped_images=unmapped)


class ImageDomainMapping:
    """Result of mapping images to domains."""

    def __init__(self, image_domains: Dict[Any, DomainType], unmapped_images: List[Any]):
        self.image_domains = image_domains
        self.unmapped_images = unmapped_images

    @property
    def active_domains(self) -> List[DomainType]:
        seen: List[DomainType] = []
        for domain in self.image_domains.values():
            if domain not in seen:
                seen.append(domain)
        return seen

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_domains": {str(k): v.value for k, v in self.image_domains.items()},
            "unmapped_images": self.unmapped_images,
            "active_domains": [d.value for d in self.active_domains],
        }
