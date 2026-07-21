"""
Unit tests for shared_key_detector.
"""

import pytest
from app.services.shared_key_detector import (
    normalize_key,
    extract_keys_from_text,
    extract_keys_from_filename,
    extract_keys_from_metadata,
    extract_keys_from_records,
    detect_shared_keys,
    auto_detect_correlation_groups,
)


def test_normalize_key():
    assert normalize_key("PO-123") == "PO-123"
    assert normalize_key("po - 123") == "PO-123"
    assert normalize_key("PO_123") == "PO-123"
    assert normalize_key("ASSET_ID_456") == "ASSET-ID-456"
    assert normalize_key("") == ""
    assert normalize_key(None) == ""


def test_extract_keys_from_text():
    text = "Order PO-456 on 2024-03-15 for asset ASSET-789"
    keys = extract_keys_from_text(text)
    assert "PO-456" in keys
    assert "2024-03-15" in keys
    assert "ASSET-789" in keys


def test_extract_keys_from_filename():
    assert "PO-123" in extract_keys_from_filename("PO-123-report.pdf")
    assert "2024-03-15" in extract_keys_from_filename("report-2024-03-15.docx")
    assert "ASSET-456" in extract_keys_from_filename("ASSET-456-maintenance.png")


def test_extract_keys_from_metadata():
    meta = {"title": "Order PO-789", "author": "John Doe"}
    keys = extract_keys_from_metadata(meta)
    assert "PO-789" in keys


def test_extract_keys_from_records():
    records = [
        {"asset_id": "ASSET-001", "order_number": "PO-100"},
        {"trailer_id": "TR-500", "date": "2024-01-01"},
    ]
    keys = extract_keys_from_records(records)
    assert "ASSET-001" in keys
    assert "PO-100" in keys
    assert "TR-500" in keys
    assert "2024-01-01" in keys


def test_detect_shared_keys():
    sources = [
        {"source_id": "A", "keys": ["PO-123", "ASSET-456"]},
        {"source_id": "B", "keys": ["PO-123", "DATE-2024"]},
        {"source_id": "C", "keys": ["ASSET-456"]},
    ]
    shared = detect_shared_keys(sources)
    assert "PO-123" in shared
    assert "ASSET-456" in shared
    assert len(shared["PO-123"]) == 2
    assert len(shared["ASSET-456"]) == 2


def test_auto_detect_correlation_groups():
    sources = [
        {"source_id": "A", "keys": ["PO-123"], "domains": ["PROD"]},
        {"source_id": "B", "keys": ["PO-123"], "domains": ["LOG"]},
        {"source_id": "C", "keys": ["ASSET-456"], "domains": ["MNT"]},
    ]
    groups = auto_detect_correlation_groups(sources)
    assert len(groups) == 1
    assert set(groups[0]["source_ids"]) == {"A", "B"}
    assert "PO-123" in groups[0]["shared_keys"]


def test_auto_detect_with_manual_keys():
    sources = [
        {"source_id": "A", "keys": ["PO-123"], "domains": ["PROD"]},
        {"source_id": "B", "keys": ["ASSET-456"], "domains": ["LOG"]},
    ]
    groups = auto_detect_correlation_groups(sources, manual_keys=["MANUAL-KEY"])
    # Manual key forces grouping if present in source content
    # Here it's not, so groups remain empty
    assert len(groups) == 0

    groups2 = auto_detect_correlation_groups(
        [{"source_id": "A", "keys": ["MANUAL-KEY"], "domains": ["PROD"]},
         {"source_id": "B", "keys": ["MANUAL-KEY"], "domains": ["LOG"]}],
        manual_keys=["MANUAL-KEY"],
    )
    assert len(groups2) == 1
def test_normalize_key_with_extra_spaces():
    """
    normalize_key should clean up extra whitespace and
    produce the same canonical key.
    """
    assert normalize_key("   po   999   ") == "PO-999"
