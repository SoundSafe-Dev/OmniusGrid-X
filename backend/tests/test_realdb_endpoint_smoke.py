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

from tests.route_walk import http_paths  # noqa: E402

# Paths that legitimately depend on infrastructure this harness doesn't run.
# They must degrade to 503 (which the walk allows) — anything else fails.
SKIP_EXACT = {
    "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
}


def _probe_path(path: str, fill: str) -> str:
    return "/".join(
        fill if seg.startswith("{") and seg.endswith("}") else seg
        for seg in path.split("/")
    )


@pytest.mark.asyncio
async def test_no_get_endpoint_5xxs_against_migrated_postgres(app, client_a, seeded_orgs):
    fill = str(seeded_orgs["org_a_id"])  # a real uuid; routing succeeds, rows may 404
    failures = []
    tested = 0

    # Walks via the shared flattener: iterating app.routes directly sees only
    # the handful of top-level entries, because fastapi >=0.130 keeps
    # include_router() results as lazy _IncludedRouter containers. This probed 2
    # GET routes instead of ~200 until the `tested > 150` assertion below caught
    # it.
    for path in http_paths(app, "GET", skip=SKIP_EXACT):
        tested += 1
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
            failures.append(f"GET {path} -> {type(exc).__name__}: {str(exc)[:160]}")
            continue
        # 503 = a declared "optional infra unavailable" (redis feature-flag
        # store, pg_stat_statements diagnostics). Everything else >= 500 is a
        # real-DB bug of the class this test exists to prevent.
        if resp.status_code >= 500 and resp.status_code != 503:
            failures.append(f"GET {path} -> {resp.status_code}: {resp.text[:120]}")

    assert tested > 150, f"walk looks broken — only {tested} GET routes probed"
    assert not failures, (
        "GET endpoints 5xx against a migrations-built Postgres (real-DB drift "
        "or naive-datetime class):\n  " + "\n  ".join(sorted(failures))
    )
