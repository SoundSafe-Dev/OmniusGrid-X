"""Every mutation surface is protected against replay, or recorded as not (FS-659).

`IdempotencyMiddleware` dedupes retried mutations carrying an `Idempotency-Key`. It is scoped
by prefix, and the scope stops at a lane boundary on purpose — `main.py` says so:

    Correlation/kanban/intake/OTA/auth/RBAC surfaces are deliberately excluded — they are
    owned by other lanes.

That is the right call. Whether a retried kanban transition or an OTA rollout should dedupe is
a decision for the lane that owns it, and this middleware belongs to another one.

**But a deliberate scope and an accidental gap look identical from here**, which is rule 140:
fixing one side of a seam closes the instance and leaves the seam undefended. 167 of 208
mutating routes sit outside the middleware today. Nothing distinguishes the ones that were
considered from the ones nobody has looked at, and a new mutation surface added to a protected
lane lands outside protection in silence — the middleware does not fail, it simply does not
apply.

So this guard asserts nothing about which surfaces *should* be protected. It asserts that every
mounted mutation surface is **accounted for**: protected, or named below with the reason it is
not. A new one is neither, and that is what fails.
"""

from __future__ import annotations

import collections
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from _route_tree import flatten  # noqa: E402

from app.main import app  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
MAIN = REPO / "backend" / "app" / "main.py"

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

#: Prefixes outside the middleware, each with the reason. **Lane ownership is a reason.**
#: "Nobody has looked at it" is not, and is why this register exists.
UNPROTECTED: dict[str, str] = {
    # --- other lanes: whether a retried mutation dedupes is the owner's decision ----------
    "/api/v1/kanban": "Harsh's lane — a retried task transition is his call, not this middleware's",
    "/api/v1/engines": "Harsh's lane (tactical/strategic engines)",
    "/api/v1/logistics": "Harsh's lane (logistics correlation)",
    "/api/v1/nlp": "Harsh's lane (NLP correlation) — 17 routes, the largest unprotected surface",
    "/api/v1/model-monitoring": "Harsh's lane (MLOps)",
    "/api/v1/models": "Harsh's lane (MLOps model registry)",
    "/api/v1/fleet": "Hridyansh's lane (OTA) — rollouts carry their own resume semantics",
    "/api/v1/edge": "Hridyansh's lane (edge enrolment)",
    "/api/v1/rag": "htreinen's lane (retrieval and ingestion)",

    # --- replay is handled elsewhere, or would be wrong here -----------------------------
    "/api/v1/api-keys": "MUST NOT dedupe — each call is required to mint a distinct key",
    "/api/v1/erp": "inbound webhooks are deduped by vendor event id, not by Idempotency-Key",
    "/api/v1/commands": "command dispatch carries its own ack and dedupe protocol",
    "/api/v1/exports": "scheduled exports keep a delivery-attempt ledger of their own",
    "/api/v1/insights": "activation is gated by a state machine that refuses a second run",
    "/api/v1/shop-floor": "event fan-out is idempotent at the consumer",
    "/api/v1/bulk": "bulk operations are job-shaped and resumable by design",

    # --- interactive, low-volume, no retrying client -------------------------------------
    "/api/v1/auth": "authentication and RBAC; a replayed login is not a write to dedupe",
    "/api/v1/admin": "admin console, hand-driven",
    "/api/v1/organizations": "tenant provisioning, hand-driven and audited",
    "/api/v1/sso": "identity-provider configuration, hand-driven",
    "/api/v1/user": "per-user preferences and context",
    "/api/v1/feature-flags": "flag toggles, hand-driven",
    "/api/v1/registries": "reference data, edited by hand",
    "/api/v1/simulation": "scenario runs are explicitly repeatable",
    "/api/v1/twin": "optimize runs are read-shaped despite the verb",

    # --- compliance and data-governance surfaces with their own audit trail ---------------
    "/api/v1/gdpr": "erasure and consent are audited individually; a silent dedupe would hide one",
    "/api/v1/compliance": "report generation is keyed by its own request id",
    "/api/v1/data-residency": "tagging is idempotent by construction — same row, same region",
    "/api/v1/data-retention": "policy edits are versioned and hand-driven",
    "/api/v1/geofencing": "zone edits are hand-driven; alerts are deduped on the read side",
}


def _protected_prefixes() -> list[str]:
    block = re.search(r"protected_prefixes=\((.*?)\n    \)", MAIN.read_text(), re.S)
    assert block, "protected_prefixes is gone from main.py — the middleware may be unwired"
    return re.findall(r'"([^"]+)"', block.group(1))


def _mutation_surfaces() -> dict[str, int]:
    """Top-level API prefix -> number of mutating route-methods mounted under it.

    Built from the live app through `_route_tree.flatten`, not from a regex over `main.py`.
    Two hand-rolled walkers failed before this one: `app.routes` holds lazy `_IncludedRouter`
    entries whose children carry RELATIVE paths, so a naive walk reports six routes and a
    clean tree. That pitfall is written at the top of `_route_tree.py`, which existed the
    whole time.
    """
    counts: collections.Counter[str] = collections.Counter()
    for route, prefix in flatten(app.routes):
        methods = getattr(route, "methods", None) or set()
        if not (methods & MUTATING):
            continue
        full = prefix + route.path
        parts = full.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "api":
            continue
        counts["/" + "/".join(parts[:3])] += len(methods & MUTATING)
    return dict(counts)


def _is_protected(prefix: str) -> bool:
    # The surface's own prefix must start with a protected one. The reverse — "a protected
    # prefix starts with this surface" — makes `/api/v1/assets` cover `/api/v1` and every
    # surface read as protected, which is how the first version of this reported a clean tree.
    return any(prefix.startswith(p) for p in _protected_prefixes())


class TestTheMeasurementIsReal:
    def test_surfaces_are_found(self):
        surfaces = _mutation_surfaces()
        assert len(surfaces) > 20, (
            f"only {len(surfaces)} mutation surfaces found; the route walk collapsed and "
            f"every assertion below would be about nothing"
        )

    def test_a_named_surface_reads_as_protected(self):
        """Positive control. `/api/v1/transportation` is in the protected list, so if this
        reads as unprotected the matcher is inverted — and an inverted matcher reports the
        whole tree clean, which two drafts of this file did."""
        assert _is_protected("/api/v1/transportation")

    def test_an_unnamed_surface_reads_as_unprotected(self):
        """Negative control, so the matcher is not simply answering True."""
        assert not _is_protected("/api/v1/not-a-real-surface")


class TestEverySurfaceIsAccountedFor:
    def test_no_surface_is_neither_protected_nor_recorded(self):
        unaccounted = sorted(
            f"{prefix} ({n} mutating routes)"
            for prefix, n in _mutation_surfaces().items()
            if not _is_protected(prefix) and prefix not in UNPROTECTED
        )
        assert not unaccounted, (
            f"{unaccounted} mutate and are neither covered by IdempotencyMiddleware nor "
            f"recorded in UNPROTECTED. A deliberate scope and an accidental gap look "
            f"identical from here — add the prefix to `protected_prefixes` in main.py, or "
            f"to UNPROTECTED with the reason. 'Nobody has looked at it' is not a reason."
        )

    def test_the_register_has_no_dead_entries(self):
        """A prefix that is now protected, or no longer mounted, overstates the gap and
        invites the work to be done twice."""
        live = _mutation_surfaces()
        stale = sorted(
            p for p in UNPROTECTED if p not in live or _is_protected(p)
        )
        assert not stale, (
            f"{stale} are recorded as unprotected but are protected now, or mount no "
            f"mutating routes. Remove them so the register means something."
        )

    @pytest.mark.parametrize("prefix", sorted(UNPROTECTED))
    def test_each_recorded_surface_gives_a_reason(self, prefix: str):
        reason = UNPROTECTED[prefix].strip()
        assert len(reason) > 15 and not reason.lower().startswith(("todo", "n/a", "none")), (
            f"{prefix} is recorded as unprotected with no usable reason. The register exists "
            f"to separate decisions from oversights; an empty reason makes it a list."
        )
