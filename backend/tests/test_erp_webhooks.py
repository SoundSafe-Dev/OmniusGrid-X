"""Tests for ERP webhook signature verification (Phase A, task 4)."""

from app.api.erp_webhooks import compute_signature, verify_signature


def test_signature_roundtrip():
    secret = "s3cret"
    event = {"event_id": "e1", "event_type": "invoice.created", "amount": 10}
    sig = compute_signature(secret, event)
    assert verify_signature(secret, event, sig) is True


def test_signature_order_independent():
    secret = "s3cret"
    a = {"b": 2, "a": 1}
    b = {"a": 1, "b": 2}
    assert compute_signature(secret, a) == compute_signature(secret, b)  # sort_keys


def test_wrong_signature_rejected():
    assert verify_signature("s3cret", {"x": 1}, "deadbeef") is False


def test_missing_signature_rejected_when_secret_set():
    assert verify_signature("s3cret", {"x": 1}, None) is False


def test_no_secret_allows_through():
    # Unconfigured secret -> signature not enforced (open webhook).
    assert verify_signature(None, {"x": 1}, None) is True
    assert verify_signature("", {"x": 1}, None) is True
