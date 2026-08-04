"""A capped or paged list must have an ORDER BY (FS-429).

**Postgres makes no promise about row order without one.** It may return any rows it likes
for a `LIMIT`, and different ones on the next call — the planner is free to change its mind
between a sequential scan and an index scan, and a row updated in between moves.

So an unordered `LIMIT` is two defects at once:

  * **A cap that hides an arbitrary subset.** `/api/v1/health-index` was
    `select(Asset).limit(100)`: a fleet of 340 assets got 100 of them, chosen by nobody, and
    a different 100 on refresh. There is no health column to sort by — the index is computed
    per asset in Python from OEE and alarms — so the cap could not even be a *named* trade
    until an order existed.
  * **Pagination that repeats and skips.** `/api/v1/assets/` takes `skip` and `limit` and is
    the list every asset screen in the product is built on. Page 2 of an unordered query can
    contain rows page 1 already showed and omit rows nobody ever sees. Scrolling a fleet is
    the most ordinary thing an operator does here.

WHY THE SIBLING GUARD DID NOT CATCH IT. `test_capped_lists_cannot_grow` asks whether a
capped list can *say* it was capped. That is a different question from whether the cap is
deterministic, and an endpoint can pass it while returning a different arbitrary subset every
call. `/health-index` sat in that file's recorded list for a truncation signal it does not
have, with the sharper problem unnoticed underneath.

SCOPE. Only `limit`-bearing GETs that build a `select(...)`. A handler that caps a list it
assembled in Python is ordered by whatever produced it and is out of scope; the sweep counts
what it examined so a shrinking subject cannot pass silently.
"""

from __future__ import annotations

import inspect
import re

from fastapi import routing

from app.main import app
from tests._route_tree import http_routes

#: Prose is not code. A docstring explaining ordering, or a comment saying "no ORDER BY
#: because …", must not be read as an implementation — the same trap that had
#: `test_capped_lists_cannot_grow` crediting a handler for documenting `mark_truncated`.
_DOCSTRING = re.compile(r'("""|\'\'\')(?:.|\n)*?\1')
_COMMENT = re.compile(r"#[^\n]*")


def _code_only(source: str) -> str:
    return _COMMENT.sub("", _DOCSTRING.sub("", source))


def _capped_selects() -> list[tuple[str, str, str]]:
    """(module, path, code) for every limit-bearing GET that builds a select()."""
    found = []
    for route, path, methods in http_routes(app):
        if not isinstance(route, routing.APIRoute) or "GET" not in methods:
            continue
        if "limit" not in {p.name for p in route.dependant.query_params}:
            continue
        try:
            source = inspect.getsource(route.endpoint)
        except (OSError, TypeError):  # pragma: no cover - defensive
            continue
        code = _code_only(source)
        if "select(" not in code or ".limit(" not in code:
            continue
        found.append((route.endpoint.__module__.rsplit(".", 1)[-1], path, code))
    return found


CAPPED = _capped_selects()

#: Endpoints whose ordering lives somewhere this sweep cannot see — a helper, a service
#: call, or a query built in another module. Each needs a reason, not just a name.
ORDERED_ELSEWHERE: dict[str, str] = {}


class TestTheSweepIsNotVacuous:
    def test_it_finds_capped_selects(self):
        assert len(CAPPED) >= 15, (
            f"only {len(CAPPED)} limit-bearing GETs building a select() were found; the "
            f"route walk or the source read is broken and every assertion below would pass "
            f"while checking nothing"
        )

    def test_it_ignores_prose(self):
        """A comment mentioning order_by must not count as ordering."""
        assert "order_by" not in _code_only(
            'def f():\n    """Returns rows in order_by name."""\n    # order_by(x)\n    pass\n'
        )

    def test_it_sees_a_real_order_by(self):
        assert "order_by" in _code_only("def f():\n    return select(A).order_by(A.name)\n")


def test_every_capped_list_is_ordered():
    unordered = [
        f"[{module}] {path}"
        for module, path, code in CAPPED
        if "order_by" not in code and path not in ORDERED_ELSEWHERE
    ]
    assert not unordered, (
        "these endpoints cap or page a query with no ORDER BY. Postgres may return any "
        "rows for a LIMIT and different ones next call, so the cap hides an arbitrary "
        "subset and `skip` can repeat rows on one page and skip them on the next:\n  "
        + "\n  ".join(sorted(unordered))
    )
