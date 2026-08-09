"""Real-DB endpoint smoke (FS-92): no GET may 5xx against a migrated Postgres.

Locks in the guarantee that was violated during the convergence: the app must
actually RUN against a production-shaped (migrations-built) database, not just
SQLite ``create_all``. A manual version of this walk found 16 endpoints 500ing
(users.* drift, ``metadata`` renames, ``lower(uuid)``, naive-datetime
arithmetic); this keeps the count at zero.

Uses the session testcontainers TimescaleDB (schema via ``scripts/migrate.py``)
and an authenticated org-admin client. Skips where docker is unavailable.
"""

from __future__ import annotations

import pytest

pytest.importorskip("testcontainers")

from tests._lane_failures import GET_FAILURES  # noqa: E402
from tests.route_walk import http_paths  # noqa: E402

# Paths that legitimately depend on infrastructure this harness doesn't run.
# They must degrade to 503 (which the walk allows) — anything else fails.
SKIP_EXACT = {
    "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
}

# Endpoints known to 5xx against a real Postgres, owned by another lane.
#
# This guard could not run at all until the testcontainers pin was repaired, so
# these surfaced all at once rather than at the commit that broke each. Fixing
# them here would mean editing other people's subsystems blind; leaving the gate
# permanently red would train everyone to ignore it. So they are listed, owned,
# and asserted BOTH ways: a new 5xx outside this list fails, and an entry that
# starts passing also fails, so the list cannot quietly rot.
#
# Do not add to this list to make your own change go green.
#
# MOVED TO `tests/_lane_failures.py` (FS-363), which adds an owner, a precise fix and an
# EXPIRY to each entry. The list was already asserted both ways and so could not rot — but
# an entry with a reason and no date is a decision nobody has to make again, which is what
# `test_ci_quarantine_expires.py` exists to prevent for CI's `--ignore` flags. Shared with
# the write walk so one root cause is recorded once rather than twice.
#
# `test_lane_failures_expire.py` enforces the dates and needs no database, because an
# expiry that only fires when Docker is available is an expiry that does not fire.
KNOWN_LANE_FAILURES = {path: entry.reason for path, entry in GET_FAILURES.items()}


def _probe_path(path: str, fill: str) -> str:
    return "/".join(
        fill if seg.startswith("{") and seg.endswith("}") else seg
        for seg in path.split("/")
    )


@pytest.mark.asyncio
async def test_no_get_endpoint_5xxs_against_migrated_postgres(app, client_a, seeded_orgs):
    fill = str(seeded_orgs["org_a_id"])  # a real uuid; routing succeeds, rows may 404
    failures: dict[str, str] = {}  # route path -> failure detail
    probed: set[str] = set()

    # Walks via the shared flattener: iterating app.routes directly sees only
    # the handful of top-level entries, because fastapi >=0.130 keeps
    # include_router() results as lazy _IncludedRouter containers. This probed 2
    # GET routes instead of ~200 until the `probed > 150` assertion below caught
    # it.
    for path in http_paths(app, "GET", skip=SKIP_EXACT):
        probed.add(path)
        try:
            resp = await client_a.get(
                _probe_path(path, fill), params={"organization_id": fill}
            )
        except Exception as exc:  # noqa: BLE001
            # ASGITransport re-raises unhandled app exceptions instead of
            # returning 500, so without this the walk aborts on the first bad
            # endpoint and reports one failure rather than all of them. A
            # response-model mismatch (ResponseValidationError) is exactly the
            # real-DB drift this guard exists to surface.
            failures[path] = f"GET {path} -> {type(exc).__name__}: {str(exc)[:160]}"
            continue
        # 503 = a declared "optional infra unavailable" (redis feature-flag
        # store, pg_stat_statements diagnostics). Everything else >= 500 is a
        # real-DB bug of the class this test exists to prevent.
        if resp.status_code >= 500 and resp.status_code != 503:
            failures[path] = f"GET {path} -> {resp.status_code}: {resp.text[:120]}"

    assert len(probed) > 150, (
        f"walk looks broken — only {len(probed)} GET routes probed"
    )

    unexpected = sorted(
        detail for path, detail in failures.items()
        if path not in KNOWN_LANE_FAILURES
    )
    assert not unexpected, (
        "GET endpoints 5xx against a migrations-built Postgres (real-DB drift "
        "or naive-datetime class):\n  " + "\n  ".join(unexpected)
    )

    # The other direction: a known failure that now passes must be removed from
    # the list, or it silently stops being covered. Only consider entries whose
    # route still exists, so deleting an endpoint doesn't fail this.
    fixed = sorted((set(KNOWN_LANE_FAILURES) & probed) - set(failures))
    assert not fixed, (
        "these are in KNOWN_LANE_FAILURES but now pass — delete their entries "
        "so they are covered again:\n  " + "\n  ".join(fixed)
    )
