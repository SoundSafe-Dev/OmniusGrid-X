"""The application's role vocabulary — single source of truth (FS-222).

WHY THIS EXISTS. ``User.role`` was a bare ``String(50)`` with a Python-side default
of ``"operator"`` and no constraint anywhere. Nothing validated it, so:

* a typo (``"Admin"``, ``"opperator"``) stored fine and then matched no
  ``require_*`` dependency — the user silently had NO permissions rather than
  being rejected at the point the mistake was made;
* the vocabulary was duplicated. ``app/core/sso.py`` carried a private
  ``_APP_ROLES`` frozenset, ``middleware/rbac.py`` hard-coded ``"admin"`` and
  ``{"admin", "operator"}``, and ``api/compliance_reports.py`` hard-coded
  ``('admin', 'viewer')``. Three places to keep in sync, and they had already
  drifted (see ``ROLE_RANK`` below).

Roles are ORDERED. That ordering is the part that was missing, and its absence
produced a real access-control defect: two read-only compliance-report endpoints
were gated on ``require_roles('admin', 'viewer')``, which DENIES ``operator`` —
the default role every registered user gets. An operator could acknowledge alarms
and dispatch commands but could not read a report's status. With an explicit rank,
"viewer and above" is expressible and that inversion cannot be written by accident.
"""

from __future__ import annotations

from typing import Final, FrozenSet

# ---------------------------------------------------------------------------
# The roles
# ---------------------------------------------------------------------------

VIEWER: Final = "viewer"
OPERATOR: Final = "operator"
ADMIN: Final = "admin"

#: Least to most privileged. Used by :func:`at_least` and asserted by the
#: CHECK constraint added in migration 048.
ROLE_RANK: Final[dict[str, int]] = {
    VIEWER: 0,
    OPERATOR: 1,
    ADMIN: 2,
}

ROLES: Final[FrozenSet[str]] = frozenset(ROLE_RANK)

#: What a newly registered user gets. Deliberately not ADMIN.
DEFAULT_ROLE: Final = OPERATOR

# NOTE ON super_admin. `api/data_retention.py` needs a role that spans tenants:
# its config table has no organization_id and its DB functions act across every
# table for every tenant, so a per-org `require_admin` would let one tenant's
# admin purge another's data. That role is NOT defined here, because adding the
# string is the easy 10% — the hard part is that RLS scopes every query to
# app.current_org_id, so a cross-tenant operator needs a deliberate,
# separately-audited path around it. Inventing the role now would make the
# router look mountable while the isolation question stayed unanswered. It stays
# dark, guarded by tests/test_data_retention_router_unmounted.py.


def is_valid(role: str | None) -> bool:
    return role in ROLES


def at_least(role: str | None, minimum: str) -> bool:
    """Does ``role`` meet or exceed ``minimum``?

    An unknown role is never sufficient — a typo must fail closed rather than
    accidentally satisfying a low bar.
    """
    if role not in ROLE_RANK:
        return False
    return ROLE_RANK[role] >= ROLE_RANK[minimum]


def roles_at_least(minimum: str) -> FrozenSet[str]:
    """Every role meeting ``minimum``, for building an allow-list."""
    if minimum not in ROLE_RANK:
        raise ValueError(f"unknown role {minimum!r}")
    floor = ROLE_RANK[minimum]
    return frozenset(r for r, rank in ROLE_RANK.items() if rank >= floor)
