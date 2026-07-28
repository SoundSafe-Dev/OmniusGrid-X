"""Every endpoint the README documents must exist on the app.

WHY THIS IS THE SAME CLASS AS THE FRONTEND SWEEPS. `test_frontend_calls_real_endpoints.py`
asserts that a path the *client* calls is served. The README's API Reference is the other
client — the one a new engineer or an integrator reads before writing any code — and
nothing checked it at all.

WHAT IT FOUND, on its first run: **22 of 124 documented rows were wrong.** Not stylistic
drift; paths that return 404 to anyone who tries them:

  * `/api/v1/commands/{command_id}/status` and `.../cancel` — the real routes put the verb
    BEFORE the id (`/commands/status/{id}`, `/commands/cancel/{id}`);
  * `/api/v1/telemetry/latest/{id}` — really `/telemetry/{asset_id}/latest`;
  * `/api/v1/kanban/boards` and three siblings — **no boards surface exists**; there is one
    board per organisation at `/kanban/board`;
  * `/api/v1/registries/{id}/compliance-score` and `/risk-score` — two invented variants of
    one real `/score`;
  * five `/api/v1/correlations*` rows that live under `/registries/correlations`;
  * five logistics rows missing a segment, because `logistics_correlation` carries its own
    `/logistics` prefix AND is mounted under `/api/v1/logistics`, so its routes really are
    at `/api/v1/logistics/logistics/…`. That doubling is a recorded defect, deliberately
    not fixed because removing the inner prefix collides with `fleet_logistics` — and
    documenting the *intended* path instead of the real one hid it from everyone who
    would have hit the 404.

THE POINT. Documentation that cannot be executed rots silently, and the rot is invisible
precisely because nobody runs a README. This makes the API Reference a checked artefact.

SCOPE. Only rows of the form `| GET | \\`/api/v1/…\\` | description |` — the API Reference
tables. Prose mentions of a router prefix (`/api/v1/twin`, `/api/v1/rag`) are not endpoint
claims and are left alone.
"""

from __future__ import annotations

import pathlib
import re
from typing import Dict, List, Set, Tuple

import pytest

from app.main import app

README = pathlib.Path(__file__).resolve().parents[2] / "README.md"

#: `| GET | `/api/v1/x` | what it does |` — a row in an API Reference table.
DOCUMENTED_ROW = re.compile(
    r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`(/api/v1/[^`]+)`\s*\|", re.M
)


def _normalise(path: str) -> str:
    """Path-parameter names differ between the docs and the code (`{id}` vs
    `{asset_id}`); the SHAPE is what matters."""
    return re.sub(r"\{[^}]+\}", "{p}", path.rstrip("/")) or "/"


def _live_routes() -> Dict[str, Set[str]]:
    table: Dict[str, Set[str]] = {}
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if method.lower() in {"get", "post", "put", "patch", "delete"}:
                table.setdefault(_normalise(path), set()).add(method.upper())
    return table


LIVE = _live_routes()
DOCUMENTED: List[Tuple[str, str]] = DOCUMENTED_ROW.findall(README.read_text())


class TestTheSweepIsNotVacuous:
    def test_it_finds_the_documented_rows(self):
        assert len(DOCUMENTED) >= 100, (
            f"only {len(DOCUMENTED)} documented endpoints found in the README; the row "
            f"pattern no longer matches the tables and this file would pass while "
            f"checking nothing"
        )

    def test_it_reads_the_live_route_table(self):
        assert len(LIVE) >= 200, f"only {len(LIVE)} live routes resolved"

    def test_a_known_route_resolves(self):
        assert "GET" in LIVE[_normalise("/api/v1/commands/status/{command_id}")]

    def test_an_invented_route_does_not(self):
        """Proves the check can fail — this is one of the paths the README claimed."""
        assert _normalise("/api/v1/kanban/boards") not in LIVE

    def test_path_parameter_names_are_not_compared(self):
        """`{id}` in the docs and `{asset_id}` in the code are the same endpoint.
        Comparing them literally would make this file fail on every row."""
        assert _normalise("/api/v1/x/{id}") == _normalise("/api/v1/x/{asset_id}")


@pytest.mark.parametrize(
    "method,path",
    DOCUMENTED,
    ids=[f"{m} {p}" for m, p in DOCUMENTED],
)
def test_documented_endpoint_is_served(method: str, path: str):
    shape = _normalise(path)
    assert shape in LIVE, (
        f"README documents {method} {path}, which the app does not serve. Anyone "
        f"following the API Reference gets a 404. Fix the row, or the route."
    )
    assert method in LIVE[shape], (
        f"README documents {method} {path}, but that path serves only "
        f"{sorted(LIVE[shape])}."
    )
