"""An OEE that could not be computed is not a machine running at 0% (FS-461).

The backend learned this already. `backend/tests/test_oee_failure_is_not_zero.py` opens:
"Zero OEE is not a null result. It is a machine that produced nothing for the whole window —
the single worst number this platform can report about a piece of equipment." There it was an
`except` block appending a row of zeros. **The edge agent had the same defect through a
different door, and nobody checked the other side of the boundary.**

`calculate_quality` returned `0.0` when no parts had been counted, and `calculate_performance`
returned `0.0` when there was no operating time — or, more often, when `production_count` was
0 and the numerator `parts × cycle_time` came out at zero. Since OEE is the product of the
three, either one pinned it to zero.

WHY THAT WAS NOT A RARE EDGE CASE. Part counts arrive through OPTIONAL telemetry:
`payload.get("total_parts", payload.get("parts_total"))`. A PackML feed that reports state and
not counts — which is most of them — never populates it. So every asset on such a site
published `edge_oee = 0` from the moment its agent started, forever, into a per-asset
Prometheus gauge. Reproduced before the fix: a machine that ran a solid hour in Execute
reported `availability 12.5, performance 0.0, quality 0.0, oee 0.0`.

WHAT CHANGED. The two undefined factors return `None`, OEE is `None` when either is, and
`set_oee` does not publish a gauge for a value it does not have. A gauge that stops advancing
is what "no data" looks like in Prometheus — `absent()` and staleness are written for exactly
that, and a hardcoded zero defeats both.

**Availability is deliberately never None.** Its denominator is the window itself, which
always exists, so a machine that sat idle really was available 0% of the time. That is a
measurement, and blanking it would lose a real signal to fix an unreal one.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from prometheus_client import REGISTRY

from opsgrid_agent import metrics
from opsgrid_agent.analytics import oee_tracker
from opsgrid_agent.analytics.local_oee import LocalOEECalculator


def _msg(asset_id: str, state: str, ts: datetime) -> dict:
    return {
        "asset_id": asset_id,
        "collector_type": "packml",
        "timestamp_edge": ts.isoformat(),
        "payload": {"packml_state": state},
    }


class TestAnUnmeasurableFactorIsNone(unittest.TestCase):
    def setUp(self) -> None:
        self.calc = LocalOEECalculator("unit-under-test")

    def test_quality_with_no_parts_counted(self):
        self.assertIsNone(
            self.calc.calculate_quality(),
            "zero good parts out of zero parts is a ratio with no denominator, not 0% quality",
        )

    def test_quality_once_parts_exist(self):
        # The other direction: a fix that returns None unconditionally passes the test
        # above and destroys the feature.
        self.calc.add_production_count(10, 9)
        self.assertEqual(self.calc.calculate_quality(), 90.0)

    def test_quality_of_genuinely_zero_good_parts(self):
        """The sharp distinction. Ten parts made and none good IS 0% quality, and must
        still be reported — that is a real and serious measurement."""
        self.calc.add_production_count(10, 0)
        self.assertEqual(self.calc.calculate_quality(), 0.0)

    def test_performance_with_no_operating_time(self):
        self.assertIsNone(
            self.calc.calculate_performance(),
            "a machine that never ran has no rate; 0% would claim it ran and produced nothing",
        )

    def test_performance_with_operating_time_but_no_counts(self):
        now = datetime.now(timezone.utc)
        self.calc.add_state_change("Stopped", "Execute", now, 3600.0)
        self.assertIsNone(
            self.calc.calculate_performance(),
            "an hour of running with no part counts in telemetry is unmeasured "
            "performance, not zero performance",
        )

    def test_availability_is_still_a_number_when_nothing_ran(self):
        """Deliberately NOT None — the window is the denominator and it always exists."""
        self.assertEqual(self.calc.calculate_availability(), 0.0)


class TestOEEIsNoneWhenAFactorIs(unittest.TestCase):
    def test_the_product_of_an_unknown_is_unknown(self):
        calc = LocalOEECalculator("m")
        now = datetime.now(timezone.utc)
        calc.add_state_change("Stopped", "Execute", now, 3600.0)
        result = calc.calculate_oee()
        self.assertIsNone(result["oee"])
        self.assertEqual(result["availability"], 12.5, "availability is still measured")
        self.assertEqual(
            result["oee_unavailable_reason"],
            "no part counts in telemetry",
            "the payload must say WHICH factor was missing; 'unavailable' alone sends the "
            "reader back to the code",
        )

    def test_a_fully_measured_machine_still_reports_a_number(self):
        calc = LocalOEECalculator("m")
        now = datetime.now(timezone.utc)
        calc.add_state_change("Stopped", "Execute", now, 3600.0)
        calc.add_production_count(40, 38)
        result = calc.calculate_oee()
        self.assertEqual(result["quality"], 95.0)
        self.assertIsNotNone(result["oee"])
        self.assertIsNone(result["oee_unavailable_reason"])


class TestTheGaugeIsNotPublishedWithoutAValue(unittest.TestCase):
    """Prometheus has no null. Not setting the gauge is how absence is expressed."""

    def test_an_unmeasurable_oee_leaves_the_series_unset(self):
        oee_tracker.reset()
        asset = "fs461-never-measured"
        now = datetime.now(timezone.utc)
        oee_tracker.record(_msg(asset, "Execute", now - timedelta(hours=1)))
        oee_tracker.record(_msg(asset, "Stopped", now))
        self.assertIsNone(
            REGISTRY.get_sample_value("edge_oee", {"asset_id": asset}),
            "edge_oee was published for an asset whose OEE could not be computed — the "
            "worst number this system can report about a machine, asserted as fact",
        )
        self.assertIsNotNone(
            REGISTRY.get_sample_value("edge_oee_availability", {"asset_id": asset}),
            "availability IS measurable and must still be published; suppressing it would "
            "lose a real signal",
        )

    def test_a_measurable_oee_is_published(self):
        oee_tracker.reset()
        asset = "fs461-measured"
        now = datetime.now(timezone.utc)
        oee_tracker.record(_msg(asset, "Execute", now - timedelta(hours=1)))
        closing = _msg(asset, "Stopped", now)
        closing["payload"].update({"total_parts": 40, "good_parts": 38})
        oee_tracker.record(closing)
        self.assertIsNotNone(
            REGISTRY.get_sample_value("edge_oee", {"asset_id": asset}),
            "a fully measured machine must still reach the gauge",
        )

    def test_set_oee_tolerates_a_partial_dict(self):
        """`set_oee` is called with whatever `calculate_oee` returned. A missing key and a
        None value must behave the same — neither is a licence to write zero."""
        metrics.set_oee("fs461-partial", {"availability": 42.0})
        self.assertEqual(
            REGISTRY.get_sample_value("edge_oee_availability", {"asset_id": "fs461-partial"}),
            42.0,
        )
        self.assertIsNone(
            REGISTRY.get_sample_value("edge_oee", {"asset_id": "fs461-partial"})
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
