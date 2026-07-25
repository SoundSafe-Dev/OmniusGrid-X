"""Shared HS256 JWT capability tokens for time-limited report downloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog
import jwt
from jwt import PyJWTError as JWTError

from app.core.config import settings

logger = structlog.get_logger()

TOKEN_VERSION = 1
PURPOSE_EXPORT = "export_download"
PURPOSE_COMPLIANCE_REPORT = "compliance_report_download"
PURPOSE_AGENT_RELEASE = "agent_release_download"
PURPOSE_MODEL_ARTIFACT = "model_artifact_download"
SUPPORTED_PURPOSES = frozenset(
    {
        PURPOSE_EXPORT,
        PURPOSE_COMPLIANCE_REPORT,
        PURPOSE_AGENT_RELEASE,
        PURPOSE_MODEL_ARTIFACT,
    }
)
SUPPORTED_SIGNED_URL_ALGORITHMS = frozenset({"HS256"})


@dataclass(frozen=True)
class VerifiedDownloadToken:
    job_id: UUID
    organization_id: UUID
    token_id: str
    token_version: int
    purpose: str
    expires_at: datetime


class SignedTokenError(Exception):
    """Structured rejection reason for auditing; never expose details to clients."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_fallback_warning_emitted = False


def _emit_fallback_warning() -> None:
    global _fallback_warning_emitted
    if _fallback_warning_emitted or settings.SIGNED_URL_SECRET_KEY:
        return
    _fallback_warning_emitted = True
    logger.warning(
        "signed_url_secret_fallback",
        detail="SIGNED_URL_SECRET_KEY is unset; falling back to JWT_SECRET_KEY",
    )


def signed_url_secret() -> str:
    _emit_fallback_warning()
    return settings.SIGNED_URL_SECRET_KEY or settings.JWT_SECRET_KEY


def signed_url_algorithm() -> str:
    algorithm = settings.SIGNED_URL_ALGORITHM
    if algorithm not in SUPPORTED_SIGNED_URL_ALGORITHMS:
        raise SignedTokenError("unsupported_algorithm")
    return algorithm


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _parse_uuid(value: Any, claim: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise SignedTokenError(f"invalid_{claim}") from exc


def _expires_from_claim(exp: Any) -> datetime:
    if isinstance(exp, datetime):
        return _as_utc(exp)
    if isinstance(exp, (int, float)):
        return datetime.fromtimestamp(exp, tz=timezone.utc)
    raise SignedTokenError("invalid_exp")


def create_signed_download_token(
    purpose: str,
    job_id: UUID,
    organization_id: UUID,
    *,
    expires_at: datetime | None = None,
) -> str:
    if purpose not in SUPPORTED_PURPOSES:
        raise ValueError(f"Unsupported download purpose '{purpose}'")
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.EXPORT_LINK_EXPIRE_MINUTES
        )
    expires_at = _as_utc(expires_at)
    now = datetime.now(timezone.utc)
    payload = {
        "ver": TOKEN_VERSION,
        "iss": settings.SIGNED_URL_ISSUER,
        "aud": settings.SIGNED_URL_AUDIENCE,
        "purpose": purpose,
        "job_id": str(job_id),
        "organization_id": str(organization_id),
        "iat": int(now.timestamp()),
        "exp": expires_at,
        "jti": str(uuid4()),
    }
    algorithm = signed_url_algorithm()
    return jwt.encode(
        payload,
        signed_url_secret(),
        algorithm=algorithm,
    )


def _verify_v1_payload(payload: dict[str, Any], expected_purpose: str) -> VerifiedDownloadToken:
    if payload.get("ver") != TOKEN_VERSION:
        raise SignedTokenError("unsupported_token_version")
    if payload.get("purpose") != expected_purpose:
        raise SignedTokenError("wrong_purpose")
    for claim in ("job_id", "organization_id", "iat", "jti", "exp"):
        if payload.get(claim) in (None, ""):
            raise SignedTokenError(f"missing_{claim}")
    issued_at = _expires_from_claim(payload["iat"])
    expires_at = _expires_from_claim(payload["exp"])
    if issued_at > datetime.now(timezone.utc) + timedelta(seconds=60):
        raise SignedTokenError("invalid_iat")
    if expires_at <= issued_at:
        raise SignedTokenError("invalid_exp")
    token_id = _parse_uuid(payload["jti"], "jti")
    return VerifiedDownloadToken(
        job_id=_parse_uuid(payload["job_id"], "job_id"),
        organization_id=_parse_uuid(payload["organization_id"], "organization_id"),
        token_id=str(token_id),
        token_version=TOKEN_VERSION,
        purpose=str(payload["purpose"]),
        expires_at=expires_at,
    )


def _decode_v1_token(token: str, expected_purpose: str) -> VerifiedDownloadToken:
    algorithm = signed_url_algorithm()
    try:
        payload = jwt.decode(
            token,
            signed_url_secret(),
            algorithms=[algorithm],
            issuer=settings.SIGNED_URL_ISSUER,
            audience=settings.SIGNED_URL_AUDIENCE,
        )
    except JWTError as exc:
        raise SignedTokenError("invalid_signature_or_expired") from exc
    return _verify_v1_payload(payload, expected_purpose)


def _decode_legacy_export_token(token: str) -> VerifiedDownloadToken:
    if not settings.SIGNED_URL_ACCEPT_LEGACY_EXPORT_TOKENS:
        raise SignedTokenError("legacy_tokens_disabled")
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise SignedTokenError("invalid_signature_or_expired") from exc
    if payload.get("ver") == TOKEN_VERSION:
        raise SignedTokenError("legacy_shape_mismatch")
    if payload.get("purpose") != PURPOSE_EXPORT:
        raise SignedTokenError("wrong_purpose")
    for claim in ("job_id", "organization_id", "exp"):
        if payload.get(claim) in (None, ""):
            raise SignedTokenError(f"missing_{claim}")
    expires_at = _expires_from_claim(payload["exp"])
    latest_allowed_expiry = datetime.now(timezone.utc) + timedelta(
        minutes=settings.EXPORT_LINK_EXPIRE_MINUTES,
        seconds=60,
    )
    if expires_at > latest_allowed_expiry:
        raise SignedTokenError("legacy_expiry_too_far")
    return VerifiedDownloadToken(
        job_id=_parse_uuid(payload["job_id"], "job_id"),
        organization_id=_parse_uuid(payload["organization_id"], "organization_id"),
        token_id="legacy",
        token_version=0,
        purpose=PURPOSE_EXPORT,
        expires_at=expires_at,
    )


def decode_signed_download_token(
    token: str,
    expected_purpose: str,
) -> VerifiedDownloadToken:
    if expected_purpose not in SUPPORTED_PURPOSES:
        raise SignedTokenError("unsupported_purpose")
    try:
        return _decode_v1_token(token, expected_purpose)
    except SignedTokenError:
        if expected_purpose != PURPOSE_EXPORT:
            raise
        return _decode_legacy_export_token(token)


def verify_signed_download_token(
    token: str,
    expected_purpose: str,
    job_id: UUID | str,
) -> VerifiedDownloadToken:
    """Verify a signed download token and bind it to ``job_id``.

    ``job_id`` accepts a ``UUID`` or its canonical string form. That tolerance is
    deliberate rather than sloppy: the token payload round-trips through JSON, so
    ``verified.job_id`` is always a ``UUID``, while the ORM's ``UUIDString`` type
    reads ids back as dashed STRINGS on every dialect (FS-55, so JSON output is
    uniform). Any caller that pulls an id off a model — a worker, a background
    task — therefore holds a str, and a bare ``!=`` rejected a token that was in
    fact valid. Comparing canonically removes the footgun without weakening the
    check: the strings are the same length and format, so this is not a loosened
    match, just a type-agnostic one.
    """
    verified = decode_signed_download_token(token, expected_purpose)
    if str(verified.job_id) != str(job_id):
        raise SignedTokenError("job_id_mismatch")
    return verified


def build_compliance_signed_download_url(
    job_id: UUID,
    organization_id: UUID,
    expires_at: datetime,
) -> tuple[str, datetime]:
    from urllib.parse import urlencode

    expires_at = _as_utc(expires_at)
    token = create_signed_download_token(
        PURPOSE_COMPLIANCE_REPORT,
        job_id,
        organization_id,
        expires_at=expires_at,
    )
    base = settings.EXPORT_PUBLIC_BASE_URL.rstrip("/")
    query = urlencode({"token": token})
    url = f"{base}/api/v1/compliance/reports/{job_id}/signed-download?{query}"
    return url, expires_at


def build_agent_release_signed_download_url(
    release_id: UUID,
    organization_id: UUID,
    expires_at: datetime,
) -> tuple[str, datetime]:
    from urllib.parse import urlencode

    expires_at = _as_utc(expires_at)
    token = create_signed_download_token(
        PURPOSE_AGENT_RELEASE,
        release_id,
        organization_id,
        expires_at=expires_at,
    )
    base = settings.EXPORT_PUBLIC_BASE_URL.rstrip("/")
    query = urlencode({"token": token})
    url = f"{base}/api/v1/fleet/releases/{release_id}/bundle?{query}"
    return url, expires_at


def build_model_artifact_signed_download_url(
    model_id: UUID,
    organization_id: UUID,
    expires_at: datetime,
) -> tuple[str, datetime]:
    from urllib.parse import urlencode

    expires_at = _as_utc(expires_at)
    token = create_signed_download_token(
        PURPOSE_MODEL_ARTIFACT,
        model_id,
        organization_id,
        expires_at=expires_at,
    )
    base = settings.EXPORT_PUBLIC_BASE_URL.rstrip("/")
    query = urlencode({"token": token})
    url = f"{base}/api/v1/models/{model_id}/download?{query}"
    return url, expires_at
