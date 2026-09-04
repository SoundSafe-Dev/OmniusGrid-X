"""telemetry.py's `skip` had no ceiling; the shared other-lanes guard could not see it (FS-899).

`test_generated_input_cannot_five_hundred.py::TestEveryOffsetDeclaresItsCeiling` already
enforces this for every in-lane route, but `telemetry` is listed in
`tests/_lane_failures.py::LANE_ROUTERS` -- a shared allowlist covering three different
guards, for reasons unrelated to pagination (the module also serves correlation-adjacent
reads). That exemption made this specific gap invisible to the general sweep. `telemetry.py`
is core platform, not any other lane's file (no README lane row claims it), so this pins
the fix directly rather than by editing a shared, cross-guard allowlist for one file's sake.
"""
from __future__ import annotations

from app.main import app
from app.core.pagination import MAX_OFFSET


def _telemetry_history_params():
    spec = app.openapi()
    operation = spec["paths"]["/api/v1/telemetry/{asset_id}/history"]["get"]
    return {p["name"]: p["schema"] for p in operation["parameters"]}


def test_skip_declares_the_bigint_ceiling():
    params = _telemetry_history_params()
    assert "skip" in params, "the skip parameter is gone; this guard is blind"
    minimum_arms = params["skip"].get("anyOf") or [params["skip"]]
    maximum = next(
        (arm.get("maximum") for arm in minimum_arms if arm.get("type") == "integer"),
        None,
    )
    assert maximum == MAX_OFFSET, (
        f"skip's declared maximum is {maximum}, expected MAX_OFFSET ({MAX_OFFSET}) -- "
        f"a value above the Postgres bigint OFFSET ceiling reaches asyncpg and 500s "
        f"where the schema promises a 4xx"
    )


def test_limit_ceiling_matches_historians_raw_query():
    """Lowered from 10000 to 5000: this endpoint defaults to every metric on the asset
    (no metric_name filter required) and each row carries a JSON metadata column, so a
    row here is heavier than historian.py's single-metric series point, which caps at
    the same 5000."""
    params = _telemetry_history_params()
    arms = params["limit"].get("anyOf") or [params["limit"]]
    maximum = next(
        (arm.get("maximum") for arm in arms if arm.get("type") == "integer"), None
    )
    assert maximum == 5000, f"limit's ceiling is {maximum}, expected 5000"
