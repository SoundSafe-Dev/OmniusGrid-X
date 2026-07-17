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

from starlette.routing import Route  # noqa: E402

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

    seen = set()
    for route in app.routes:
        if not isinstance(route, Route):
            continue
        if "GET" not in (route.methods or set()):
            continue
        path = route.path
        if path in SKIP_EXACT or path in seen:
            continue
        seen.add(path)

        resp = await client_a.get(
            _probe_path(path, fill), params={"organization_id": fill}
        )
        tested += 1
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
