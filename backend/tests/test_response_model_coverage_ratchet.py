"""A route may not land without declaring what it returns — a ratchet, not a rule.

Pool #43. `response_model` coverage was **191/417 (45%)** when the task pool was
written on 2026-07-26 and **203/453 (45%)** when this file was added five days
later: the absolute number rose while the ratio stood still, because new routes
kept landing undeclared as fast as old ones were fixed. A burn-down without a
ratchet is a treadmill, so the ratchet comes first.

WHAT AN UNDECLARED ROUTE COSTS. The OpenAPI schema is what the contract gate
(`test_api_contract.py`) drives, and schemathesis can only check what is
declared — so 250 undeclared routes are 250 the gate cannot see, and a gate over
55% of the surface reports on the half nobody was worried about. It is also what
the generated SDK is built from (#42) and what the frontend's types are supposed
to mirror.

WHY A RATCHET AND NOT `assert undeclared == 0`. Same reasoning as
`scripts/contract_ratchet.py`: 250 routes cannot be fixed in one change, and a
gate that fails every build from the day it lands is a gate somebody comments
out. This one fails only if the number goes UP. Lower `MAX_UNDECLARED` as the
burn-down proceeds; never raise it.

THE VACUITY TRAP, WHICH THIS FILE WOULD OTHERWISE HAVE WALKED INTO.
`app.routes` holds 74 objects, of which 2 are real routes — the rest are lazy
`_IncludedRouter` containers. A walk that does not recurse sees 2 routes, finds
both declared or not, and passes with total confidence about 0.4% of the API.
The traversal is therefore imported from `_route_tree`, shared with
`test_route_auth_walk`, and `test_the_walk_is_not_vacuous` fails if the route
count collapses — because the cheapest way to satisfy a ratchet is to stop
counting.
"""

from __future__ import annotations

import pytest

from app.main import app
from tests._route_tree import http_routes

#: The measured number of routes serving an undeclared response, 2026-07-31.
#: LOWER THIS as routes are declared. Raising it means a route landed without a
#: response_model, which is the thing this file exists to prevent.
MAX_UNDECLARED = 243

#: Total routes when that number was measured. A large swing means something
#: structural changed and the ratchet's denominator is no longer comparable.
EXPECTED_TOTAL = 453
TOTAL_TOLERANCE = 0.15


def _undeclared() -> list[str]:
    out = []
    for route, path, methods in http_routes(app):
        if getattr(route, "response_model", None) is None:
            module = getattr(route.endpoint, "__module__", "?").split(".")[-1]
            out.append(f"{','.join(sorted(methods)):<12} {path}  [{module}]")
    return sorted(out)


def _total() -> int:
    return sum(1 for _ in http_routes(app))


class TestTheWalkCanSeeItsSubject:
    """Asserted before the ratchet, because a ratchet over nothing always passes."""

    def test_the_walk_is_not_vacuous(self):
        total = _total()
        assert total > 400, (
            f"the route walk found only {total} routes. The app serves ~{EXPECTED_TOTAL}. "
            "This is the lazy-_IncludedRouter trap: a non-recursing walk sees 2 routes "
            "and every guard built on it passes vacuously. Fix the traversal in "
            "tests/_route_tree.py — do not adjust the ratchet to match."
        )

    def test_the_total_has_not_moved_structurally(self):
        total = _total()
        drift = abs(total - EXPECTED_TOTAL) / EXPECTED_TOTAL
        assert drift <= TOTAL_TOLERANCE, (
            f"route count moved {total - EXPECTED_TOTAL:+d} (now {total}, baseline "
            f"{EXPECTED_TOTAL}). Routes get added legitimately; a swing this size means "
            "the denominator changed shape. Re-measure and update EXPECTED_TOTAL with the "
            "date, so the coverage ratio stays comparable."
        )

    def test_some_routes_do_declare_a_response_model(self):
        """The inverse vacuity check: if `response_model` stopped being readable
        on every route, `_undeclared()` would return everything and the ratchet
        would fail loudly — but if it became unreadable as None everywhere, the
        count would look perfect. Neither should pass quietly."""
        declared = _total() - len(_undeclared())
        assert declared > 150, (
            f"only {declared} routes appear to declare a response_model. That is far "
            "below the measured 203 and suggests the attribute is no longer being read, "
            "not that coverage collapsed."
        )


class TestTheRatchet:
    def test_no_new_undeclared_routes(self):
        undeclared = _undeclared()
        assert len(undeclared) <= MAX_UNDECLARED, (
            f"{len(undeclared)} routes serve an undeclared response; the ratchet allows "
            f"{MAX_UNDECLARED}.\n\n"
            "A route with no `response_model` is invisible to the API contract gate, "
            "absent from the generated SDK, and a promise the OpenAPI schema cannot "
            "make. Declare one on the new route.\n\n"
            "If you are DECLARING routes rather than adding them, lower MAX_UNDECLARED "
            "to the new number.\n\nCurrently undeclared:\n  "
            + "\n  ".join(undeclared[:40])
            + (f"\n  ... and {len(undeclared) - 40} more" if len(undeclared) > 40 else "")
        )

    def test_the_ratchet_is_not_slack(self):
        """A floor far above the real number silently permits regressions.

        The contract ratchet keeps a deliberate 9-point margin because its score
        genuinely varies between runs. This count does not vary — it is read
        from the route table, not measured — so any slack is pure permission.
        """
        undeclared = len(_undeclared())
        assert MAX_UNDECLARED - undeclared <= 5, (
            f"the ratchet allows {MAX_UNDECLARED} undeclared routes but only {undeclared} "
            f"exist, leaving room for {MAX_UNDECLARED - undeclared} regressions to land "
            "unnoticed. This count is deterministic, so it needs no margin: lower "
            f"MAX_UNDECLARED to {undeclared}."
        )
