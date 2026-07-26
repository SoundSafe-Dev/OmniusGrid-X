"""ERP inbound webhook signature verification.

WHAT THIS FILE USED TO ASSERT, AND WHY IT WAS WRONG.

The signature was computed over `json.dumps(event_data, sort_keys=True)` — the
*parsed* payload, re-serialised with sorted keys. No ERP vendor signs a canonicalised
re-serialisation of its own payload; SAP, Dynamics, NetSuite and Intuit all sign the
exact bytes they transmit. Key order, whitespace, unicode escaping and float
formatting all differ, so the digest could never match a real delivery and **every
genuine vendor webhook was rejected with 401**.

The old tests passed because they called the production `compute_signature` to produce
the signature they then verified — a fixture encoding the same assumption as the code,
which is structurally incapable of disconfirming it. One test asserted the very
property that made it broken:

    def test_signature_order_independent():
        assert compute_signature(secret, a) == compute_signature(secret, b)

Order independence is exactly what stops a signature from authenticating a real
request. It reads like a robustness feature and is the bug.

These tests now sign RAW BYTES the way a vendor would, and the central one asserts
that a re-serialised body does NOT verify.

The fail-closed cases below are kept from the previous version, which had already
fixed an earlier defect: `verify_signature` used to return True when no secret was
configured, making the route an open write.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from app.api.erp_webhooks import compute_signature, verify_signature

SECRET = "s3cret-webhook-key"

#: Bytes as a vendor would put them on the wire: unsorted keys, their whitespace.
RAW_BODY = b'{"event_id":"evt-1","event_type":"po.created","amount":1234.50,"entity_type":"PurchaseOrder"}'


def _hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _b64(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


class TestRawBodySignatures:
    def test_a_hex_signature_over_the_raw_body_verifies(self):
        assert verify_signature(SECRET, RAW_BODY, _hex(SECRET, RAW_BODY))

    def test_a_base64_signature_verifies(self):
        """Intuit sends base64 in `intuit-signature`. Supporting one encoding and
        rejecting the other looks identical to a forged request."""
        assert verify_signature(SECRET, RAW_BODY, _b64(SECRET, RAW_BODY))

    def test_a_sha256_prefixed_signature_verifies(self):
        """GitHub-style `sha256=<hex>`, used by several middlewares."""
        assert verify_signature(SECRET, RAW_BODY, f"sha256={_hex(SECRET, RAW_BODY)}")

    def test_compute_signature_matches_a_plain_hmac_of_the_bytes(self):
        """Known-answer, so the suite is not merely self-consistent."""
        assert compute_signature(SECRET, RAW_BODY) == _hex(SECRET, RAW_BODY)


class TestTheRegression:
    """The assertions that would have caught the original defect."""

    def test_a_reserialised_body_does_not_verify(self):
        """THE CENTRAL ONE.

        A signature over the parsed-and-re-dumped payload must be REJECTED, because
        that is not what the vendor signed. The old implementation accepted exactly
        this, and nothing else.
        """
        reserialised = json.dumps(json.loads(RAW_BODY), sort_keys=True).encode()
        assert reserialised != RAW_BODY, "pick a body that really does re-serialise differently"
        assert not verify_signature(SECRET, RAW_BODY, _hex(SECRET, reserialised)), (
            "a signature over re-serialised JSON was accepted; that is the old scheme, "
            "and it cannot authenticate any real vendor delivery"
        )

    def test_key_order_is_no_longer_ignored(self):
        """The inverse of the old `test_signature_order_independent`. Two payloads
        with the same fields in a different order are DIFFERENT BYTES and must produce
        different signatures, or the signature is not binding the request actually
        sent."""
        assert compute_signature(SECRET, b'{"x":1,"y":2}') != compute_signature(
            SECRET, b'{"y":2,"x":1}'
        )

    def test_whitespace_changes_the_signature(self):
        """Pretty-printed and compact JSON are semantically identical and are not the
        same request."""
        assert compute_signature(SECRET, b'{"a":1}') != compute_signature(SECRET, b'{ "a": 1 }')


class TestFailsClosed:
    def test_a_tampered_body_is_rejected(self):
        assert not verify_signature(SECRET, RAW_BODY + b" ", _hex(SECRET, RAW_BODY))

    def test_the_wrong_secret_is_rejected(self):
        assert not verify_signature(SECRET, RAW_BODY, _hex("other-secret", RAW_BODY))

    def test_no_secret_configured_rejects_everything(self):
        """An integration without a webhook secret must not accept unauthenticated
        events. Treating "no secret" as "skip verification" turns the endpoint into an
        open write — which it once was, on a route the auth walk deliberately exempts
        because it is supposed to be HMAC-protected.
        """
        assert not verify_signature(None, RAW_BODY, _hex(SECRET, RAW_BODY))
        assert not verify_signature("", RAW_BODY, _hex(SECRET, RAW_BODY))

    @pytest.mark.parametrize("signature", [None, "", "   ", "not-hex", "deadbeef"])
    def test_a_missing_or_malformed_signature_is_rejected(self, signature):
        """Including the empty header: a caller must not bypass verification by
        omitting it."""
        assert verify_signature(SECRET, RAW_BODY, signature) is False

    def test_a_signature_for_a_different_body_is_rejected(self):
        assert not verify_signature(SECRET, RAW_BODY, _hex(SECRET, b'{"event_id":"evt-2"}'))


class TestTenantResolutionIsBySignature:
    """The route is one shared path per erp_type with nothing identifying the
    organisation. It used to take `.first()` of the active integrations ACROSS ALL
    ORGANISATIONS and verify against that one's secret — so with two tenants both
    running SAP, only whichever row the database returned first could ever
    authenticate, and every other tenant's genuine events were rejected as forged.

    The route now selects the integration whose secret verifies these exact bytes.
    """

    def test_only_the_holder_of_the_matching_secret_verifies(self):
        signature = _hex("tenant-a-secret", RAW_BODY)
        assert verify_signature("tenant-a-secret", RAW_BODY, signature)
        assert not verify_signature("tenant-b-secret", RAW_BODY, signature), (
            "a second tenant's secret verified another tenant's webhook"
        )

    def test_a_tenant_without_a_secret_never_wins_the_match(self):
        """Otherwise an integration with no secret configured would swallow every
        other tenant's events."""
        assert not verify_signature(None, RAW_BODY, _hex("anything", RAW_BODY))
