"""The correlation id stopped at the process boundary (FS-1014).

`RequestContextMiddleware` binds `request_id` into structlog's contextvars, so every log
line this process writes carries it. Every outbound ERP call then opened an `aiohttp`
session with no correlation header at all — `grep -n "correlation_id"` across
`services/erp_connectors/` and `services/erp_middleware/` returned nothing in either
directory.

So a failing ERP webhook and the request that triggered it could not be joined. Our side
is fully traceable; the vendor's side records an unattributed request; the operator
correlating an incident across the two has a timestamp and hope. Every counter, retry
classifier and circuit breaker worked — what was missing was the thread between two
systems, which is the one thing none of them can reconstruct afterwards.

WHY IT IS READ FROM CONTEXTVARS. The alternative is threading a `request_id` parameter
through the connector base class, five middleware services and their forty-odd call sites.
That is the change nobody makes, which is precisely why the header was never added.

WHY AN EMPTY DICT OUTSIDE A REQUEST. A scheduled sync has no originating request. Minting a
fresh id there would produce something that *looks* like correlation and correlates
nothing — worse than absence, because it invites a reader to trust it.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
import structlog

from app.middleware.request_context import REQUEST_ID_HEADER, outbound_correlation_headers
from tests._source_trees import REPO_ROOT

OUTBOUND_DIRS = [
    REPO_ROOT / "backend" / "app" / "services" / "erp_connectors",
    REPO_ROOT / "backend" / "app" / "services" / "erp_middleware",
]


class TestTheHeaderItself:
    def test_it_carries_the_bound_request_id(self):
        structlog.contextvars.bind_contextvars(request_id="req-abc-123")
        try:
            assert outbound_correlation_headers() == {REQUEST_ID_HEADER: "req-abc-123"}
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

    def test_it_is_empty_outside_a_request(self):
        """A scheduled worker must not invent one. See the module docstring."""
        structlog.contextvars.clear_contextvars()
        assert outbound_correlation_headers() == {}


class TestEverySessionFactoryPropagatesIt:
    """The factories introduced by FS-1008 are the single injection point; this asserts
    every one of them actually uses it, rather than one file being missed."""

    def _factories(self):
        for directory in OUTBOUND_DIRS:
            for path in sorted(directory.glob("*.py")):
                tree = ast.parse(path.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == "_session":
                        yield path, node

    def test_the_factories_exist_to_be_checked(self):
        found = list(self._factories())
        assert len(found) >= 10, (
            f"only {len(found)} `_session` factories found across {[str(d) for d in OUTBOUND_DIRS]}; "
            "the AST walk is broken, or the factories were inlined again"
        )

    def test_each_passes_the_correlation_headers(self):
        missing = []
        for path, node in self._factories():
            source = ast.unparse(node)
            if "outbound_correlation_headers" not in source:
                missing.append(str(path.relative_to(REPO_ROOT)))
        assert not missing, (
            "session factories that do not propagate the correlation id:\n  "
            + "\n  ".join(missing)
            + "\n\nWithout it a failing call in that file cannot be joined to the request "
            "that caused it. Pass `headers=outbound_correlation_headers()`."
        )
