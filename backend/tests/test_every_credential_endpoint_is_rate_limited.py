"""An unlimited credential endpoint is the brute-force control missing (FS-1018).

`api/auth.py` decorates every one of its endpoints with `@auth_rate_limit` — login,
register, refresh, logout, invite-validate, invite-accept. `api/mfa.py` decorated none of
its three, so enrolment, activation and **disabling MFA** had only the app-wide default
between them and an unbounded caller.

THE FINDING WAS NARROWER THAN IT LOOKED, and the correction is recorded here because
overstating it would be its own defect. The obvious fear — brute-forcing a 6-digit TOTP at
login — was already handled: login-time verification runs *inside* `auth.py`'s `login`,
which carries `AUTH_LOGIN_RATE_LIMIT`. The three MFA routes require an authenticated
session, so anyone reaching them already holds the account.

They are bounded anyway, for reasons that survive that correction: `DELETE /mfa` is a
security downgrade, `enroll` regenerates a secret on every call, `confirm` accepts an
8-character recovery-code-shaped input with nothing counting attempts, and — the general
argument — every other auth-adjacent state change in this codebase is limited, so an
unlimited one reads as an oversight whether or not it is exploitable today. A convention
with a hole in it is a convention nobody can rely on.

WHY A GUARD RATHER THAN THREE DECORATORS. The decorators are the fix; this is the thing
that notices the fourth endpoint. `slowapi` additionally requires a `request: Request`
parameter on anything it decorates and raises at import time without one, so a route added
without it fails loudly — but a route added without the decorator at all fails silently,
which is the case this covers.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from tests._source_trees import REPO_ROOT

#: Modules whose endpoints handle credentials, secrets or session state. A new one belongs
#: here the day it is written, not the day somebody notices it is unlimited.
CREDENTIAL_ROUTERS = ("auth.py", "mfa.py", "sso.py", "api_keys.py")

API_DIR = REPO_ROOT / "backend" / "app" / "api"

#: Endpoints that legitimately need no limiter, each with the reason. A read-only status
#: check is not a brute-force surface; a state change is.
EXEMPT = {
    "mfa.py::mfa_status": "read-only: reports whether MFA is on, changes nothing",
    "auth.py::get_current_user_info": "read-only: GET /me, already behind an authenticated session",
    "sso.py::sso_status": "read-only: reports whether SSO is configured, no credential accepted",
    "sso.py::sso_me": "read-only: echoes the authenticated user, changes nothing",
}


def _route_functions(path: pathlib.Path):
    """(name, decorators) for every function carrying an @router.<method> decorator."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = []
        is_route = False
        for dec in node.decorator_list:
            call = dec.func if isinstance(dec, ast.Call) else dec
            attr = getattr(call, "attr", None)
            value = getattr(call, "value", None)
            if attr in {"get", "post", "put", "patch", "delete"} and getattr(
                value, "id", ""
            ).endswith("router"):
                is_route = True
            names.append(ast.unparse(dec))
        if is_route:
            yield node.name, names


def _unlimited() -> list[str]:
    found = []
    for filename in CREDENTIAL_ROUTERS:
        path = API_DIR / filename
        if not path.exists():
            continue
        for name, decorators in _route_functions(path):
            key = f"{filename}::{name}"
            if key in EXEMPT:
                continue
            if not any("rate_limit" in d for d in decorators):
                found.append(key)
    return found


class TestTheWalkCanSeeItsSubject:
    def test_it_finds_the_routes_it_is_meant_to_check(self):
        total = sum(
            1 for f in CREDENTIAL_ROUTERS
            if (API_DIR / f).exists()
            for _ in _route_functions(API_DIR / f)
        )
        assert total >= 8, (
            f"only {total} credential routes found across {CREDENTIAL_ROUTERS}; the AST "
            "walk is broken rather than the API having shrunk"
        )

    def test_the_exempt_entries_still_name_real_routes(self):
        """A register entry for a route that no longer exists is a claim about nothing,
        and it hides the day that route comes back unlimited."""
        live = {
            f"{f}::{name}"
            for f in CREDENTIAL_ROUTERS if (API_DIR / f).exists()
            for name, _ in _route_functions(API_DIR / f)
        }
        stale = sorted(set(EXEMPT) - live)
        assert not stale, f"exempt entries name routes that no longer exist: {stale}"


class TestEveryCredentialEndpointIsRateLimited:
    def test_no_credential_route_is_unlimited(self):
        offenders = _unlimited()
        assert not offenders, (
            "credential endpoints with no rate limiter:\n  "
            + "\n  ".join(offenders)
            + "\n\nEvery state-changing route in these modules carries "
            "`@auth_rate_limit(...)`. Add one, or add the route to EXEMPT with the "
            "reason it is not a brute-force surface."
        )
