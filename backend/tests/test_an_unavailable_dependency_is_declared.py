"""A router that reports a dependency outage must declare 503, and one that cannot must not.

`app/core/responses.py` keeps TWO status codes out of `common_responses` on purpose, with the
same argument for each: only some routes can produce them, and declaring them everywhere would
tell a generated SDK to handle responses most operations never send. 409 is the first; this
file is the second.

The module says exactly how membership is meant to be decided:

    Grep for `status_code=503` before adding a router here — the point of a separate mapping
    is that membership means something.

**Nothing performed that grep.** `analysis_sessions` raises 503 for
`CorrelationModelUnavailableError` — the correlation model being unreachable, which is the
outage case this mapping exists for — and was mounted with `common_responses`. So the one
status that means *the model is down and this is not your fault* was undeclared, and a client
built from the schema had no branch for it (FS-733).

WHY A DERIVED CHECK RATHER THAN A LIST. Membership is decidable from the code: a router can
answer 503 if a handler in it raises one. That makes both directions assertable, and each
fails differently —

  * a router that CAN report an outage without declaring it leaves the SDK unable to tell
    "your request was wrong" from "the thing behind this endpoint is down", which are the two
    responses a caller must handle differently: one is a bug to fix, the other is a retry;
  * a router that declares it and CANNOT leaves a branch that never runs, which is the
    over-promise `responses.py` argues against in its own comment.

THE GRANULARITY IS THE ROUTER, not the route, and that is deliberate — `unavailable_responses`
is applied at `include_router`, so the question this file can answer is the question the
codebase actually asks. 409 is per-route because `conflict_response` is spread per-route. Each
check matches the shape of the thing it checks.
"""

from __future__ import annotations

import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
API_DIR = BACKEND / "app" / "api"
MAIN = BACKEND / "app" / "main.py"

RAISES_503 = ("HTTP_503", "status_code=503")

#: Routers whose 503 comes from somewhere this check cannot see, with the reason. Empty, and
#: it should stay that way: a router that reports an outage should say so in its schema.
EXEMPT: dict[str, str] = {}


def _mounted_with() -> dict[str, str]:
    """router module -> the responses mapping it is mounted with."""
    return {
        m.group(1): m.group(2)
        for m in re.finditer(
            r"app\.include_router\(\s*(\w+)\.router[^)]*?responses=(\w+)", MAIN.read_text(), re.S
        )
    }


def _raises_503() -> set[str]:
    return {
        path.stem
        for path in API_DIR.glob("*.py")
        if any(marker in path.read_text() for marker in RAISES_503)
    }


class TestTheMeasurementIsReal:
    def test_the_mounts_are_readable(self):
        """Vacuity. If the `include_router` regex breaks, every assertion below passes over
        an empty map — which is how a register rots without anybody noticing."""
        mounted = _mounted_with()
        assert len(mounted) > 40, f"only {len(mounted)} routers parsed from main.py"
        assert "health" in mounted, "the health router was not found at all"

    def test_both_mappings_are_in_use(self):
        """If everything were mounted with one mapping, this file would be asserting a
        tautology. The split is the thing being checked."""
        values = set(_mounted_with().values())
        assert {"common_responses", "unavailable_responses"} <= values, (
            f"expected both response mappings in use, found {values}"
        )

    def test_a_known_reporter_is_detected(self):
        """`health` exists to report dependency state; if it stops looking like a 503
        raiser, the detector has drifted rather than the code."""
        assert "health" in _raises_503()


class TestEveryOutageIsDeclared:
    def test_no_router_reports_an_outage_without_declaring_it(self):
        mounted = _mounted_with()
        missing = sorted(
            name
            for name in _raises_503()
            if name in mounted
            and mounted[name] != "unavailable_responses"
            and name not in EXEMPT
        )
        assert not missing, (
            f"{missing} raise 503 and are mounted with a mapping that does not declare it. A "
            f"client cannot then tell 'your request was wrong' from 'the dependency is down' "
            f"— one is a bug to fix, the other is a retry. Mount with `unavailable_responses`."
        )

    def test_no_router_declares_an_outage_it_cannot_report(self):
        """The over-promise direction, which `responses.py` argues is equally bad."""
        raises = _raises_503()
        phantom = sorted(
            name
            for name, mapping in _mounted_with().items()
            if mapping == "unavailable_responses" and name not in raises
        )
        assert not phantom, (
            f"{phantom} declare 503 and raise none. Either the raise was removed and the "
            f"declaration outlived it, or it was never true — `responses.py` asks for a grep "
            f"before adding a router to that mapping, and this is that grep."
        )

    @pytest.mark.parametrize("router", sorted(EXEMPT))
    def test_every_exemption_states_a_reason(self, router: str):
        assert len(EXEMPT[router].strip()) > 30, f"{router} is exempt with no reason"
