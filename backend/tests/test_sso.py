"""Focused unit tests for the Task 6 SSO claim/role mapping (pure functions).

No Keycloak or DB needed — these cover claim normalization, audience validation,
and the role mapping (including the Keycloak path-style groups like ``/admins``).
"""

import pytest

from app.core import sso
from app.core.sso import (
    SSOValidationError,
    _collect_roles_and_groups,
    _normalize_claims,
    _validate_audience,
    map_sso_role,
)


# --- map_sso_role -----------------------------------------------------------
def test_map_role_handles_keycloak_path_groups():
    assert map_sso_role([], ["/admins"]) == "admin"
    assert map_sso_role([], ["/ops/admins"]) == "admin"  # nested path
    assert map_sso_role([], ["/Viewers"]) == "viewer"     # case-insensitive + plural
    assert map_sso_role([], ["/operators"]) == "operator"
    assert map_sso_role([], ["/admin"]) == "admin"        # singular path also fine


def test_map_role_handles_bare_realm_roles():
    assert map_sso_role(["admin"], []) == "admin"
    assert map_sso_role(["viewer"], []) == "viewer"
    assert map_sso_role(["operator"], []) == "operator"


def test_map_role_precedence_admin_wins():
    assert map_sso_role([], ["/viewers", "/admins"]) == "admin"


def test_map_role_defaults_to_operator_for_unknown():
    assert map_sso_role([], ["/contractors"]) == "operator"
    assert map_sso_role([], []) == "operator"


# --- _validate_audience -----------------------------------------------------
def test_validate_audience_accepts_azp_and_aud(monkeypatch):
    monkeypatch.setattr(sso.settings, "KEYCLOAK_CLIENT_ID", "opsgrid")
    _validate_audience({"azp": "opsgrid"})                 # azp match
    _validate_audience({"aud": "opsgrid"})                 # aud string
    _validate_audience({"aud": ["other", "opsgrid"]})      # aud list contains
    with pytest.raises(SSOValidationError):
        _validate_audience({"aud": "someone-else"})


# --- _collect_roles_and_groups ---------------------------------------------
def test_collect_roles_and_groups(monkeypatch):
    monkeypatch.setattr(sso.settings, "KEYCLOAK_CLIENT_ID", "opsgrid")
    decoded = {
        "realm_access": {"roles": ["offline_access", "admin"]},
        "resource_access": {"opsgrid": {"roles": ["uma_protection"]}},
        "groups": ["/admins", "/ops"],
    }
    roles, groups = _collect_roles_and_groups(decoded)
    assert "admin" in roles and "uma_protection" in roles
    assert groups == ["/admins", "/ops"]


# --- _normalize_claims ------------------------------------------------------
def test_normalize_claims_builds_identity():
    claims = _normalize_claims({
        "sub": "abc", "email": "User@Example.com",
        "given_name": "Ada", "family_name": "Lovelace",
        "organization_id": "11111111-1111-1111-1111-111111111111",
    })
    assert claims.email == "user@example.com"  # lowercased
    assert claims.full_name == "Ada Lovelace"
    assert claims.enabled is True               # absent -> treated as enabled
    assert claims.email_verified is True        # absent -> treated as verified
    assert claims.organization_id == "11111111-1111-1111-1111-111111111111"


def test_normalize_claims_requires_email():
    with pytest.raises(SSOValidationError):
        _normalize_claims({"sub": "abc"})


def test_normalize_claims_explicit_false_blocks():
    claims = _normalize_claims({"email": "a@b.com", "enabled": False, "email_verified": False})
    assert claims.enabled is False
    assert claims.email_verified is False
