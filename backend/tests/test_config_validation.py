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
    # Dev auth bypasses and wildcard CORS default insecure — flagged in prod.
    assert any("ALLOW_DEV_TOKEN" in p for p in problems)
    assert any("ALLOW_OPEN_REGISTRATION" in p for p in problems)
    assert any("CORS_ALLOW_ORIGINS" in p for p in problems)
    assert any("GEOTAB_WEBHOOK_SECRET" in p for p in problems)
    assert any("ERP_ENCRYPTION_KEY" in p for p in problems)


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
    )
    assert validate_settings(s) == []
