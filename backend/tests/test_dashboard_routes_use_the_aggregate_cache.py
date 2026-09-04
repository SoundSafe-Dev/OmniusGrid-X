"""/overview and /fleet/oee are wired to the bounded cache, and stay wired (FS-896).

`test_aggregate_cache.py` proves `cached_aggregate` itself behaves correctly; this proves
the two routes it was built for still call it, by exact function name (rule 296) rather
than by reading the file's general shape.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _handler_source(name: str) -> ast.AST:
    tree = ast.parse((APP / "api/dashboard.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} moved or was renamed; this guard is blind")


class TestBothPolledRoutesCallTheCache:
    def test_overview_calls_cached_aggregate(self):
        body = ast.unparse(_handler_source("get_dashboard_overview"))
        assert "cached_aggregate(" in body, (
            "get_dashboard_overview no longer calls cached_aggregate -- every open tab "
            "polling this route every 30s is back to hitting the database directly"
        )

    def test_fleet_oee_calls_cached_aggregate(self):
        body = ast.unparse(_handler_source("get_fleet_oee"))
        assert "cached_aggregate(" in body, (
            "get_fleet_oee no longer calls cached_aggregate"
        )

    def test_overview_key_includes_the_org(self):
        """A cache key missing org_id would serve one tenant's dashboard to another."""
        body = ast.unparse(_handler_source("get_dashboard_overview"))
        assert "dashboard_overview:{org_id}" in body, (
            "the /overview cache key no longer visibly includes org_id -- verify by "
            "name, not by trusting the call is scoped correctly"
        )

    def test_fleet_oee_key_includes_the_org_and_the_time_range(self):
        """`hours` changes the answer; a key without it would serve a 24h answer to a
        168h request or vice versa."""
        body = ast.unparse(_handler_source("get_fleet_oee"))
        assert "fleet_oee:{org_id}:{hours}" in body, (
            "the /fleet/oee cache key no longer visibly includes both org_id and hours"
        )
