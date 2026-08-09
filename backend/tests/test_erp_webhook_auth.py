"""Vendor-aware inbound webhook authentication.

WHY THIS LAYER EXISTS. Fixing the HMAC to hash the raw body was necessary but not
sufficient: the route accepted exactly one header, `X-Webhook-Signature`, carrying a
hex digest. **We invented that header.** No ERP vendor sends it, so no vendor's webhook
could authenticate regardless of how correctly we hashed.

    Intuit QuickBooks   `intuit-signature`, base64 HMAC-SHA256 over the raw body
    Dataverse/Dynamics  a static header configured on the serviceendpoint record --
                        no HMAC option exists
    NetSuite            whatever a SuiteScript user-event script sends
    SAP Event Mesh      usually OAuth/basic on the subscription
    Odoo                base_automation puts a token in the URL

So header and scheme are per-integration configuration with per-vendor defaults. These
tests pin the defaults (so a vendor's out-of-the-box wiring works with only a secret
supplied) and the fail-closed behaviour on every degenerate input.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from app.services.erp_webhook_auth import (
    DEFAULT_HEADER,
    HMAC_SHA256,
    SHARED_SECRET,
    authenticate_webhook,
    describe_scheme,
    resolve_scheme,
)

SECRET = "verifier-token-abc"
RAW = b'{"eventNotifications":[{"realmId":"123","dataChangeEvent":{"entities":[]}}]}'


def _hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _b64(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def _auth(erp_type, configuration, headers, raw=RAW):
    return authenticate_webhook(
        erp_type=erp_type, configuration=configuration, raw_body=raw, headers=headers
    )


class TestVendorDefaults:
    def test_intuit_defaults_to_its_own_header_and_base64(self):
        """The one scheme verified against vendor documentation -- the Intuit connector
        implements the same check for the same reason."""
        scheme = resolve_scheme("intuit", {})
        assert scheme["header"] == "intuit-signature"
        assert scheme["encoding"] == "base64"
        assert scheme["mode"] == HMAC_SHA256

    def test_an_intuit_webhook_authenticates_with_only_a_secret_configured(self):
        """The whole point of vendor defaults: wiring up Intuit should require the
        verifier token and nothing else."""
        ok, reason = _auth(
            "intuit", {"webhook_secret": SECRET}, {"intuit-signature": _b64(SECRET, RAW)}
        )
        assert ok, reason

    def test_dataverse_defaults_to_a_static_header_not_an_hmac(self):
        """Dataverse serviceendpoint webhooks have no HMAC option -- they send an HTTP
        header whose name and value you choose. Pretending otherwise would mean every
        Dynamics webhook failed."""
        scheme = resolve_scheme("dynamics", {})
        assert scheme["mode"] == SHARED_SECRET

    def test_a_dataverse_webhook_authenticates_on_the_static_header(self):
        ok, reason = _auth(
            "dynamics",
            {"webhook_secret": SECRET},
            {"x-omniusgrid-webhook-token": SECRET},
        )
        assert ok, reason

    def test_an_unknown_vendor_falls_back_to_hmac_on_the_historical_header(self):
        scheme = resolve_scheme("some-new-erp", {})
        assert scheme["mode"] == HMAC_SHA256
        assert scheme["header"] == DEFAULT_HEADER


class TestPerIntegrationOverride:
    def test_the_header_name_can_be_overridden(self):
        """Necessary for NetSuite and for anything behind a middleware, where the
        sending end is operator-defined."""
        ok, _ = _auth(
            "netsuite",
            {"webhook_secret": SECRET, "webhook_signature_header": "X-Acme-Signature"},
            {"x-acme-signature": _hex(SECRET, RAW)},
        )
        assert ok

    def test_the_mode_can_be_overridden(self):
        ok, _ = _auth(
            "sap",
            {"webhook_secret": SECRET, "webhook_auth_mode": "shared_secret",
             "webhook_signature_header": "x-sap-token"},
            {"x-sap-token": SECRET},
        )
        assert ok

    def test_header_matching_is_case_insensitive(self):
        """HTTP header names are, and vendors are inconsistent about casing."""
        for name in ("intuit-signature", "Intuit-Signature", "INTUIT-SIGNATURE"):
            ok, reason = _auth("intuit", {"webhook_secret": SECRET}, {name: _b64(SECRET, RAW)})
            assert ok, f"{name}: {reason}"

    def test_a_pinned_encoding_rejects_the_other_form(self):
        """An operator who pins base64 should not silently accept hex; a mismatch
        usually means the sender is not the vendor they think it is."""
        config = {"webhook_secret": SECRET, "webhook_signature_encoding": "base64",
                  "webhook_signature_header": DEFAULT_HEADER}
        ok_b64, _ = _auth("sap", config, {DEFAULT_HEADER: _b64(SECRET, RAW)})
        ok_hex, _ = _auth("sap", config, {DEFAULT_HEADER: _hex(SECRET, RAW)})
        assert ok_b64 and not ok_hex

    def test_auto_encoding_accepts_either(self):
        config = {"webhook_secret": SECRET}
        assert _auth("sap", config, {DEFAULT_HEADER: _hex(SECRET, RAW)})[0]
        assert _auth("sap", config, {DEFAULT_HEADER: _b64(SECRET, RAW)})[0]

    def test_a_sha256_prefix_is_tolerated(self):
        ok, _ = _auth("sap", {"webhook_secret": SECRET},
                      {DEFAULT_HEADER: f"sha256={_hex(SECRET, RAW)}"})
        assert ok


class TestFailsClosed:
    def test_no_secret_rejects_even_a_correct_signature(self):
        """An integration with no secret must not accept unauthenticated events. This
        route is exempt from the authentication walk precisely because it is supposed
        to be protected here."""
        ok, reason = _auth("intuit", {}, {"intuit-signature": _b64(SECRET, RAW)})
        assert not ok and "webhook_secret" in reason

    def test_a_missing_header_rejects(self):
        ok, reason = _auth("intuit", {"webhook_secret": SECRET}, {})
        assert not ok and "missing" in reason

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_header_rejects(self, value):
        """A present-but-blank header must not read as "nothing to check"."""
        ok, _ = _auth("intuit", {"webhook_secret": SECRET}, {"intuit-signature": value})
        assert not ok

    def test_an_unsupported_mode_rejects_rather_than_falling_back(self):
        """A typo in the mode must not silently downgrade the check to a default."""
        ok, reason = _auth(
            "sap",
            {"webhook_secret": SECRET, "webhook_auth_mode": "hmac-sha-256"},
            {DEFAULT_HEADER: _hex(SECRET, RAW)},
        )
        assert not ok and "unsupported" in reason

    def test_a_tampered_body_rejects(self):
        ok, _ = _auth("sap", {"webhook_secret": SECRET},
                      {DEFAULT_HEADER: _hex(SECRET, RAW)}, raw=RAW + b" ")
        assert not ok

    def test_the_wrong_secret_rejects(self):
        ok, _ = _auth("sap", {"webhook_secret": SECRET},
                      {DEFAULT_HEADER: _hex("other", RAW)})
        assert not ok

    def test_a_shared_secret_mismatch_rejects(self):
        ok, _ = _auth("dynamics", {"webhook_secret": SECRET},
                      {"x-omniusgrid-webhook-token": "wrong"})
        assert not ok

    def test_hmac_mode_with_no_body_rejects(self):
        ok, reason = _auth("sap", {"webhook_secret": SECRET},
                           {DEFAULT_HEADER: _hex(SECRET, RAW)}, raw=None)
        assert not ok and "raw body" in reason


class TestTenantSeparation:
    def test_only_the_holder_of_the_matching_secret_authenticates(self):
        """The route resolves the tenant by trying each candidate integration, so this
        property is what keeps one tenant's events out of another's records."""
        signature = _b64("tenant-a", RAW)
        assert _auth("intuit", {"webhook_secret": "tenant-a"}, {"intuit-signature": signature})[0]
        assert not _auth("intuit", {"webhook_secret": "tenant-b"}, {"intuit-signature": signature})[0]


class TestOperatorDiagnostics:
    def test_describe_scheme_never_leaks_the_secret(self):
        described = describe_scheme("intuit", {"webhook_secret": SECRET})
        assert SECRET not in str(described)
        assert described["secret_configured"] is True

    def test_describe_scheme_reports_what_the_operator_must_configure(self):
        """This is what turns a deliberately-silent 401 into something actionable."""
        described = describe_scheme("intuit", {})
        assert described["signature_header"] == "intuit-signature"
        assert described["auth_mode"] == HMAC_SHA256
        assert described["secret_configured"] is False
