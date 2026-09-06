"""Tests for production config validation (task 17)."""

from app.core.config import Settings, validate_settings


def test_dev_config_has_no_problems():
    s = Settings(ENVIRONMENT="development")
    assert validate_settings(s) == []


def test_production_flags_insecure_defaults():
    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="dev_secret_key_change_in_production",
        DEBUG=True,
        EDGE_BOOTSTRAP_TOKEN="",
    )
    problems = validate_settings(s)
    assert any("JWT_SECRET_KEY" in p for p in problems)
    assert any("DEBUG" in p for p in problems)
    assert any("EDGE_BOOTSTRAP_TOKEN" in p for p in problems)
    # Dev auth bypass and wildcard CORS defaults are insecure. Open
    # registration now defaults closed, so it should not create a problem.
    assert any("ALLOW_DEV_TOKEN" in p for p in problems)
    assert not any("ALLOW_OPEN_REGISTRATION" in p for p in problems)
    assert any("CORS_ALLOW_ORIGINS" in p for p in problems)
    assert any("GEOTAB_WEBHOOK_SECRET" in p for p in problems)
    assert any("ERP_ENCRYPTION_KEY" in p for p in problems)
    assert any("GEOTAB_SIMULATED" in p for p in problems)
    assert any("EDGE_REQUIRE_PROOF_OF_POSSESSION" in p for p in problems)
    # FS-744. `RATE_LIMIT_ENABLED` defaults False like the rest of this list, and was the
    # one default nothing here checked — so production could ship with the only
    # brute-force control on /auth/login switched off. Asserted in BOTH directions: this
    # rejects it, and `test_production_with_secure_config_passes` proves a config that
    # sets it is accepted, so the check cannot be satisfied by rejecting everything.
    assert any("RATE_LIMIT_ENABLED" in p for p in problems)


def test_production_with_secure_config_passes():
    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a-very-long-random-production-secret",
        DEBUG=False,
        EDGE_BOOTSTRAP_TOKEN="rotate-me",
        ALLOW_DEV_TOKEN=False,
        ALLOW_OPEN_REGISTRATION=False,
        CORS_ALLOW_ORIGINS="https://app.example.com",
        GEOTAB_WEBHOOK_SECRET="rotate-me-too",
        ERP_ENCRYPTION_KEY="a-stable-erp-master-key",
        GEOTAB_SIMULATED=False,
        EDGE_REQUIRE_PROOF_OF_POSSESSION=True,
        # ADDED BY FS-744, and its absence here was the point. This config was the
        # repository's definition of "secure production" and it left the only
        # brute-force control on /auth/login switched off — the gate was missing, so
        # nothing rejected it.
        RATE_LIMIT_ENABLED=True,
    )
    assert validate_settings(s) == []


class TestTheJwtSecretIsLongEnoughToBeWorthHaving:
    """FS-969. The gate checked PRESENCE and not LENGTH.

    `JWT_SECRET_KEY=hunter2` is not empty and is not the dev default, so it passed every
    check this file had — while being seven bytes against a SHA-256 HMAC. RFC 7518 s3.2
    requires the key to be no shorter than the hash output (32 bytes for HS256); below
    that, the brute-force space against every token the service has ever signed is
    narrower than the algorithm advertises.

    Found by upgrading PyJWT to 2.13.0 for CVE-2026-48526/48523, which added an
    `InsecureKeyLengthWarning` at decode time and made the test suite say so out loud.
    That warning is not a gate: it fires after the token is already signed, in a log line,
    on a machine already running. This is the same finding moved to startup, where a
    deployment can still be stopped.
    """

    def test_a_short_secret_is_refused(self):
        s = Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="hunter2",
        )
        problems = validate_settings(s)
        assert any("JWT_SECRET_KEY" in p and "bytes" in p for p in problems), (
            "a 7-byte JWT secret passed the production gate. It is not empty and not the "
            "dev default, which is all the gate used to check."
        )

    def test_a_secret_one_byte_short_is_refused(self):
        """The boundary, not just an obviously-bad value: 31 bytes must fail."""
        s = Settings(ENVIRONMENT="production", JWT_SECRET_KEY="x" * 31)
        assert any("JWT_SECRET_KEY" in p and "bytes" in p for p in validate_settings(s))

    def test_a_secret_of_exactly_the_minimum_is_accepted(self):
        """The other direction, so the check cannot be satisfied by rejecting everything:
        exactly 32 bytes is the RFC's floor and must pass."""
        s = Settings(ENVIRONMENT="production", JWT_SECRET_KEY="x" * 32)
        assert not any("JWT_SECRET_KEY" in p for p in validate_settings(s))

    def test_the_dev_default_still_reports_as_the_dev_default(self):
        """The length branch is `elif`, so the more specific and more actionable message
        ("this is the dev default") must still win over the generic length one."""
        s = Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="dev_secret_key_change_in_production",
        )
        jwt_problems = [p for p in validate_settings(s) if "JWT_SECRET_KEY" in p]
        assert jwt_problems == ["JWT_SECRET_KEY is unset or the insecure dev default"]

    def test_a_multibyte_secret_is_measured_in_bytes_not_characters(self):
        """31 multi-byte characters is 93 bytes of key material and must pass. Measuring
        `len(str)` instead of `len(str.encode())` would reject it -- the inverse of the
        defect this class exists for, and the reason the check encodes first."""
        s = Settings(ENVIRONMENT="production", JWT_SECRET_KEY="é" * 31)
        assert not any("JWT_SECRET_KEY" in p for p in validate_settings(s))
