"""Unit coverage for invitation credentials, URLs, and escaped email content."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services.email_templates import build_user_invitation_email
from app.services.user_invitations import (
    InvitationTokenError,
    invitation_token_hash,
    invitation_token_organization,
    invitation_url,
    issue_invitation_token,
    validate_new_password,
)


def test_invitation_token_contains_org_routing_and_only_hash_is_derived():
    organization_id = uuid4()
    token, stored_hash = issue_invitation_token(organization_id)

    assert invitation_token_organization(token) == organization_id
    assert stored_hash == invitation_token_hash(token)
    assert len(stored_hash) == 64
    assert token not in stored_hash
    assert len(token.split(".", 1)[1]) == 43


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-uuid.secret",
        f"{uuid4()}.too-short",
        f"{uuid4()}.{'a' * 42}!",
        f"{uuid4()}.{'a' * 44}",
    ],
)
def test_malformed_invitation_tokens_are_rejected(token):
    with pytest.raises(InvitationTokenError):
        invitation_token_organization(token)


def test_invitation_url_places_credential_in_fragment(monkeypatch):
    monkeypatch.setattr(
        "app.services.user_invitations.settings.USER_INVITE_PUBLIC_BASE_URL",
        "https://app.example.com/",
    )
    token, _ = issue_invitation_token(uuid4())

    url = invitation_url(token)

    assert url == f"https://app.example.com/accept-invite#token={token}"
    assert "?" not in url


def test_invitation_email_escapes_untrusted_html():
    content = build_user_invitation_email(
        organization_name="<script>alert(1)</script>",
        requested_role="<admin>",
        invitation_url='https://example.com/#token="unsafe"',
        expires_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert "<script>" not in content.html_body
    assert "&lt;script&gt;" in content.html_body
    assert "&lt;admin&gt;" in content.html_body
    assert "&quot;unsafe&quot;" in content.html_body
    assert "https://example.com/#token=" in content.text_body


def test_password_policy_enforces_minimum_and_bcrypt_byte_limit(monkeypatch):
    monkeypatch.setattr(
        "app.services.user_invitations.settings.USER_PASSWORD_MIN_LENGTH",
        12,
    )
    validate_new_password("twelve-chars!")

    with pytest.raises(ValueError, match="at least 12"):
        validate_new_password("short")
    with pytest.raises(ValueError, match="72 UTF-8 bytes"):
        validate_new_password("🙂" * 19)
