"""Unit tests for shared signed download tokens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from jose import jwt

from app.services.export_delivery import (
    create_download_signature,
    decode_download_signature,
    verify_download_signature,
)
from app.utils import signed_urls as signed_urls_module
from app.utils.signed_urls import (
    PURPOSE_COMPLIANCE_REPORT,
    PURPOSE_EXPORT,
    SignedTokenError,
    TOKEN_VERSION,
    create_signed_download_token,
    decode_signed_download_token,
    verify_signed_download_token,
)


@pytest.fixture
def signed_settings(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SIGNED_URL_SECRET_KEY", "signed-secret")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "jwt-secret")
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(settings, "SIGNED_URL_ALGORITHM", "HS256")
    monkeypatch.setattr(settings, "SIGNED_URL_ISSUER", "test-issuer")
    monkeypatch.setattr(settings, "SIGNED_URL_AUDIENCE", "test-audience")
    monkeypatch.setattr(settings, "SIGNED_URL_ACCEPT_LEGACY_EXPORT_TOKENS", True)
    monkeypatch.setattr(settings, "EXPORT_LINK_EXPIRE_MINUTES", 1440)
    monkeypatch.setattr(settings, "EXPORT_PUBLIC_BASE_URL", "http://example.test")
    signed_urls_module._fallback_warning_emitted = False


def _legacy_export_token(job_id, org_id) -> str:
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    return jwt.encode(
        {
            "organization_id": str(org_id),
            "job_id": str(job_id),
            "purpose": PURPOSE_EXPORT,
            "exp": expires,
        },
        "jwt-secret",
        algorithm="HS256",
    )


def test_valid_compliance_token(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = create_signed_download_token(
        PURPOSE_COMPLIANCE_REPORT,
        job_id,
        org_id,
    )
    verified = verify_signed_download_token(token, PURPOSE_COMPLIANCE_REPORT, job_id)
    assert verified.organization_id == org_id
    assert verified.token_version == TOKEN_VERSION
    assert verified.purpose == PURPOSE_COMPLIANCE_REPORT
    assert verified.token_id


def test_tampered_token_fails(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = create_signed_download_token(PURPOSE_COMPLIANCE_REPORT, job_id, org_id)
    broken = token[:-1] + ("a" if token[-1] != "a" else "b")
    with pytest.raises(SignedTokenError):
        verify_signed_download_token(broken, PURPOSE_COMPLIANCE_REPORT, job_id)


def test_expired_token_fails(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    token = create_signed_download_token(
        PURPOSE_COMPLIANCE_REPORT,
        job_id,
        org_id,
        expires_at=expired_at,
    )
    with pytest.raises(SignedTokenError):
        verify_signed_download_token(token, PURPOSE_COMPLIANCE_REPORT, job_id)


def test_missing_claim_fails(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = jwt.encode(
        {
            "ver": TOKEN_VERSION,
            "iss": "test-issuer",
            "aud": "test-audience",
            "purpose": PURPOSE_COMPLIANCE_REPORT,
            "organization_id": str(org_id),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "jti": str(uuid4()),
        },
        "signed-secret",
        algorithm="HS256",
    )
    with pytest.raises(SignedTokenError):
        verify_signed_download_token(token, PURPOSE_COMPLIANCE_REPORT, job_id)


def test_missing_iat_fails(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = jwt.encode(
        {
            "ver": TOKEN_VERSION,
            "iss": "test-issuer",
            "aud": "test-audience",
            "purpose": PURPOSE_COMPLIANCE_REPORT,
            "job_id": str(job_id),
            "organization_id": str(org_id),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "jti": str(uuid4()),
        },
        "signed-secret",
        algorithm="HS256",
    )
    with pytest.raises(SignedTokenError) as exc:
        verify_signed_download_token(token, PURPOSE_COMPLIANCE_REPORT, job_id)
    assert exc.value.reason == "missing_iat"


def test_signed_algorithm_is_independent_from_login_jwt(signed_settings, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS512")
    job_id = uuid4()
    org_id = uuid4()
    token = create_signed_download_token(PURPOSE_COMPLIANCE_REPORT, job_id, org_id)
    assert verify_signed_download_token(
        token,
        PURPOSE_COMPLIANCE_REPORT,
        job_id,
    ).organization_id == org_id


def test_unsupported_signed_algorithm_fails_closed(signed_settings, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SIGNED_URL_ALGORITHM", "HS512")
    with pytest.raises(SignedTokenError) as exc:
        create_signed_download_token(
            PURPOSE_COMPLIANCE_REPORT,
            uuid4(),
            uuid4(),
        )
    assert exc.value.reason == "unsupported_algorithm"


def test_wrong_issuer_fails(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = jwt.encode(
        {
            "ver": TOKEN_VERSION,
            "iss": "wrong-issuer",
            "aud": "test-audience",
            "purpose": PURPOSE_COMPLIANCE_REPORT,
            "job_id": str(job_id),
            "organization_id": str(org_id),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "jti": str(uuid4()),
        },
        "signed-secret",
        algorithm="HS256",
    )
    with pytest.raises(SignedTokenError):
        verify_signed_download_token(token, PURPOSE_COMPLIANCE_REPORT, job_id)


def test_wrong_audience_fails(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = jwt.encode(
        {
            "ver": TOKEN_VERSION,
            "iss": "test-issuer",
            "aud": "wrong-audience",
            "purpose": PURPOSE_COMPLIANCE_REPORT,
            "job_id": str(job_id),
            "organization_id": str(org_id),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "jti": str(uuid4()),
        },
        "signed-secret",
        algorithm="HS256",
    )
    with pytest.raises(SignedTokenError):
        verify_signed_download_token(token, PURPOSE_COMPLIANCE_REPORT, job_id)


def test_export_token_rejected_for_compliance(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = create_signed_download_token(PURPOSE_EXPORT, job_id, org_id)
    with pytest.raises(SignedTokenError):
        verify_signed_download_token(token, PURPOSE_COMPLIANCE_REPORT, job_id)


def test_compliance_token_rejected_for_export(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = create_signed_download_token(PURPOSE_COMPLIANCE_REPORT, job_id, org_id)
    with pytest.raises(SignedTokenError):
        verify_signed_download_token(token, PURPOSE_EXPORT, job_id)


def test_wrong_job_id_fails(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = create_signed_download_token(PURPOSE_COMPLIANCE_REPORT, job_id, org_id)
    with pytest.raises(SignedTokenError):
        verify_signed_download_token(token, PURPOSE_COMPLIANCE_REPORT, uuid4())


def test_malformed_uuid_claim_fails(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = jwt.encode(
        {
            "ver": TOKEN_VERSION,
            "iss": "test-issuer",
            "aud": "test-audience",
            "purpose": PURPOSE_COMPLIANCE_REPORT,
            "job_id": "not-a-uuid",
            "organization_id": str(org_id),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "jti": str(uuid4()),
        },
        "signed-secret",
        algorithm="HS256",
    )
    with pytest.raises(SignedTokenError):
        decode_signed_download_token(token, PURPOSE_COMPLIANCE_REPORT)


def test_legacy_export_token_remains_valid(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    token = _legacy_export_token(job_id, org_id)
    verified = verify_signed_download_token(token, PURPOSE_EXPORT, job_id)
    assert verified.token_version == 0
    assert verified.organization_id == org_id


def test_legacy_export_tokens_can_be_disabled(signed_settings, monkeypatch):
    from app.core.config import settings

    job_id = uuid4()
    org_id = uuid4()
    token = _legacy_export_token(job_id, org_id)
    monkeypatch.setattr(settings, "SIGNED_URL_ACCEPT_LEGACY_EXPORT_TOKENS", False)
    with pytest.raises(SignedTokenError) as exc:
        verify_signed_download_token(token, PURPOSE_EXPORT, job_id)
    assert exc.value.reason == "legacy_tokens_disabled"


def test_export_wrapper_compatibility(signed_settings):
    job_id = uuid4()
    org_id = uuid4()
    signature = create_download_signature(job_id, org_id)
    payload = decode_download_signature(signature)
    assert payload is not None
    assert payload["job_id"] == str(job_id)
    assert verify_download_signature(signature, job_id, org_id)


def test_build_compliance_signed_download_url_encodes_token(signed_settings):
    from app.utils.signed_urls import build_compliance_signed_download_url

    job_id = uuid4()
    org_id = uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
    url, returned_expiry = build_compliance_signed_download_url(
        job_id,
        org_id,
        expires_at,
    )
    assert "/signed-download?" in url
    assert "token=" in url
    assert returned_expiry == expires_at


def test_uvicorn_access_log_redacts_signed_credentials():
    import logging

    from app.core.logging_filters import SensitiveQueryAccessLogFilter

    token = "secret.jwt.value"
    signature = "legacy.signature"
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1",
            "GET",
            f"/download?token={token}&signature={signature}&page=2",
            "1.1",
            200,
        ),
        None,
    )
    assert SensitiveQueryAccessLogFilter().filter(record)
    rendered = record.getMessage()
    assert token not in rendered
    assert signature not in rendered
    assert "page=2" in rendered
    assert "REDACTED" in rendered
