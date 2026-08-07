"""The load test's CI and real-infrastructure thresholds stay different (FS-373).

FS-373 reads *"`load-test` blocks on error rate but not on p95 latency; there is no latency SLO
gate anywhere"*. Half of that is true and **deliberate**, and the reasoning is written into
`tests/load/k6-load-test.js`:

    The latency SLOs stay out of CI on purpose. p(95)<500ms on a shared GitHub runner
    measures whichever neighbour is busy, not this API, and a gate that fails for reasons
    its author cannot act on is one that gets switched off.

The other half is not true: `p(95)<500` and `p(99)<1000` are asserted on the non-CI profile,
and `infra/prometheus/slo_rules.yml` is linted and unit-tested by the `prometheus-rules` job.

SO THIS GUARDS THE SPLIT RATHER THAN CLOSING THE ITEM, because the split is what can erode,
in both directions and both silently:

  * **Latency added to the CI profile** makes the job flaky for reasons nobody can fix. A
    flaky blocking gate does not get repaired; it gets `continue-on-error: true`, and then
    the error-rate assertion — the part that was working — stops blocking too. One bad
    threshold takes the good ones with it.
  * **Latency removed from the non-CI profile** deletes the only latency SLO the load test
    carries, and nothing would say so: the CI job never asserted it, so CI stays green.

k6 decides its exit code from thresholds alone — a failed `check()` does not fail the run — so
this block is the entire difference between a load test that can fail and one that cannot.
That is worth pinning.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests" / "load" / "k6-load-test.js"


def _thresholds() -> tuple[str, str]:
    """(ci block, full block) — the two arms of the `CI_SMOKE ? … : …` ternary."""
    source = SCRIPT.read_text()
    match = re.search(
        r"thresholds:\s*CI_SMOKE\s*\?\s*\{(?P<ci>.*?)\}\s*:\s*\{(?P<full>.*?)\}\s*,?\s*\}",
        source,
        re.S,
    )
    assert match, (
        "the CI_SMOKE threshold ternary could not be read out of k6-load-test.js. Either it "
        "was restructured — in which case this guard is checking a shape that no longer "
        "exists — or the regex broke. Both are worth stopping for."
    )
    return match.group("ci"), match.group("full")


class TestTheReaderIsNotVacuous:
    def test_the_script_exists(self):
        assert SCRIPT.exists(), f"{SCRIPT} is gone; this guard checks nothing"

    def test_both_arms_parse(self):
        ci, full = _thresholds()
        assert ci.strip() and full.strip(), "one arm of the ternary parsed empty"


class TestTheCIProfileStaysActionable:
    def test_ci_asserts_the_error_rate(self):
        """The part that IS stable on a shared runner, and the only reason the CI job can
        fail at all."""
        ci, _ = _thresholds()
        assert "http_req_failed" in ci, (
            "the CI smoke profile no longer asserts the transport error rate, which was the "
            "one thing it was gating on — the job can now pass whatever the app does"
        )

    def test_ci_does_not_assert_latency(self):
        ci, _ = _thresholds()
        assert "http_req_duration" not in ci, (
            "a latency threshold was added to the CI smoke profile. On a shared GitHub "
            "runner p(95) measures whichever neighbour is busy, so this job will fail for "
            "reasons nobody can act on — and a flaky blocking gate does not get repaired, it "
            "gets continue-on-error, which would take the error-rate assertion down with it."
        )


class TestTheRealProfileKeepsItsSLO:
    @pytest.mark.parametrize("threshold", ["p(95)<500", "p(99)<1000"])
    def test_the_latency_slo_is_still_asserted(self, threshold: str):
        """Nothing in CI exercises this arm, so removing it would be invisible: the load-test
        job would stay green because it never asserted latency in the first place."""
        _, full = _thresholds()
        assert threshold in full.replace(" ", ""), (
            f"the real-infrastructure profile no longer asserts {threshold}. That is the only "
            f"latency SLO this load test carries, and no CI job would notice it going."
        )

    def test_the_real_profile_also_keeps_the_error_rate(self):
        _, full = _thresholds()
        assert "http_req_failed" in full
