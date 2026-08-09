"""Escaped email templates for report and invitation delivery."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ComplianceReportEmailContent:
    subject: str
    text_body: str
    html_body: str


@dataclass(frozen=True)
class UserInvitationEmailContent:
    subject: str
    text_body: str
    html_body: str


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat(sep=" ", timespec="seconds")
    return value.astimezone().isoformat(sep=" ", timespec="seconds")


def build_compliance_report_email(
    *,
    framework: str,
    generated_at: datetime,
    download_url: str,
    expires_at: datetime,
) -> ComplianceReportEmailContent:
    """Render subject and bodies for a compliance report notification."""
    safe_framework = html.escape(framework, quote=True)
    generated_text = _format_timestamp(generated_at)
    expires_text = _format_timestamp(expires_at)
    safe_generated = html.escape(generated_text, quote=True)
    safe_expires = html.escape(expires_text, quote=True)
    safe_url = html.escape(download_url, quote=True)

    subject = f"OmniusGrid compliance report: {framework}"

    text_body = (
        "Your OmniusGrid compliance report is ready.\n\n"
        f"Framework: {framework}\n"
        f"Generated at: {generated_text}\n"
        f"Download: {download_url}\n"
        f"Link expires at: {expires_text}\n\n"
        "This link is time-limited and grants access to this one report. "
        "Please do not forward it."
    )

    html_body = (
        "<html><body>"
        "<p>Your <strong>OmniusGrid</strong> compliance report is ready.</p>"
        "<ul>"
        f"<li><strong>Framework:</strong> {safe_framework}</li>"
        f"<li><strong>Generated at:</strong> {safe_generated}</li>"
        f"<li><strong>Link expires at:</strong> {safe_expires}</li>"
        "</ul>"
        f'<p><a href="{safe_url}">Download report</a></p>'
        "<p>This link is time-limited and grants access to this one report. "
        "Please do not forward it.</p>"
        "</body></html>"
    )

    return ComplianceReportEmailContent(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


def build_user_invitation_email(
    *,
    organization_name: str,
    requested_role: str,
    invitation_url: str,
    expires_at: datetime,
) -> UserInvitationEmailContent:
    """Render an escaped invitation without exposing transport secrets."""

    subject_org = " ".join(organization_name.split())
    subject = f"You're invited to {subject_org} on OmniusGrid"
    expires_text = _format_timestamp(expires_at)
    safe_org = html.escape(organization_name, quote=True)
    safe_role = html.escape(requested_role, quote=True)
    safe_url = html.escape(invitation_url, quote=True)
    safe_expires = html.escape(expires_text, quote=True)

    text_body = (
        f"You have been invited to join {organization_name} on OmniusGrid.\n\n"
        f"Role: {requested_role}\n"
        f"Accept invitation: {invitation_url}\n"
        f"Invitation expires at: {expires_text}\n\n"
        "This link is one-time and intended only for you. "
        "If you were not expecting this invitation, you can ignore this email."
    )
    html_body = (
        "<html><body>"
        f"<p>You have been invited to join <strong>{safe_org}</strong> "
        "on OmniusGrid.</p>"
        f"<p><strong>Role:</strong> {safe_role}</p>"
        f'<p><a href="{safe_url}">Accept invitation</a></p>'
        f"<p>This invitation expires at {safe_expires}.</p>"
        "<p>This link is one-time and intended only for you. "
        "If you were not expecting this invitation, you can ignore this email.</p>"
        "</body></html>"
    )
    return UserInvitationEmailContent(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
