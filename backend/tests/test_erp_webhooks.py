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


def test_no_secret_fails_closed():
    """An unconfigured secret must reject, not wave the request through.

    This test previously asserted the opposite — `is True`, described as an
    "open webhook" — so the fail-open was locked in as intended behaviour rather
    than caught. Any integration row with an absent or empty
    `configuration.webhook_secret` accepted unsigned webhooks and wrote ERP
    events from them, on a route that test_route_auth_walk.py exempts from the
    authentication walk precisely because it is supposed to be HMAC-protected.
    """
    assert verify_signature(None, {"x": 1}, None) is False
    assert verify_signature("", {"x": 1}, None) is False
    # Even a well-formed signature cannot pass without a configured secret.
    assert verify_signature(None, {"x": 1}, compute_signature("s3cret", {"x": 1})) is False
