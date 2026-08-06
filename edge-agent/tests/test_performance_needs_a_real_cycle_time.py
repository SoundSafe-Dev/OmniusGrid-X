"""Performance is measured against the machine's rated rate, or not at all (FS-463).

Performance = (parts produced x ideal cycle time) / operating time. The ideal cycle time is
a property of the MACHINE — seconds per part when it runs flat out — and the agent hardcoded
it:

    self.ideal_cycle_time: float = 60.0  # seconds (default)

set in `__init__`, never read from configuration, never assignable, never referenced anywhere
else in the tree. **Every machine in the world was assumed to take sixty seconds per part.**

WHAT THAT PRODUCES, measured before the fix:

    a press with a 3s cycle, running flat out for an hour   -> 100%   (computed 2000%, clamped)
    a CNC with a 600s cycle, running flat out for an hour   ->  10%   (no clamp at the bottom)

The clamp is what made it survive. Fast machines came out at exactly 100% and looked
perfect; only slow machines showed the error, as a machine running perfectly reported one
tenth of its rate.

FOUND BY A SYSTEMATIC PASS, not by chance. Three consecutive findings in this agent turned
out to be defects the backend had already fixed, so the sweep became: take each closed
backend class and ask whether the agent computes the same quantity. This is
`test_maintenance_costs_are_computed_not_invented` — a number derived from an invented
constant — and the backend's own `oee_calculator._get_ideal_cycle_time` reads it per asset
from `asset.connection_config['ideal_cycle_time_seconds']`. The agent had no way to be told
at all.

WHAT CHANGED. No default. `oee_tracker.configure(asset_id, seconds)` is called from the
collector-registration loop in `main.py`, next to the alert-rule registration that already
lived there, reading the same config key the backend reads. Unconfigured, performance is
`None` with a reason — consistent with FS-461: absence is reported, not invented.

**This turns performance OFF for any deployment that never configured a cycle time.** That
is the point. Those deployments were not getting performance; they were getting a number
computed from sixty.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from opsgrid_agent.analytics import oee_tracker
from opsgrid_agent.analytics.local_oee import LocalOEECalculator


def _ran_an_hour(calc: LocalOEECalculator, parts: int) -> None:
    calc.add_state_change("Stopped", "Execute", datetime.now(timezone.utc), 3600.0)
    calc.add_production_count(parts, parts)


class TestNoRateMeansNoPerformance(unittest.TestCase):
    def test_an_unconfigured_asset_reports_no_performance(self):
        calc = LocalOEECalculator("m")
        _ran_an_hour(calc, 60)
        self.assertIsNone(
            calc.calculate_performance(),
            "performance was computed against a hardcoded 60s cycle, which is a property "
            "of no machine in particular",
        )

    def test_the_reason_names_the_missing_configuration(self):
        calc = LocalOEECalculator("m")
        _ran_an_hour(calc, 60)
        result = calc.calculate_oee()
        self.assertIsNone(result["oee"])
        self.assertEqual(
            result["oee_unavailable_reason"],
            "no ideal cycle time configured for this asset",
            "an operator seeing a blank performance figure needs to be told it is a "
            "config gap, not a broken machine",
        )

    def test_a_configured_asset_reports_the_real_figure(self):
        """The other direction. Returning None always would pass the tests above."""
        calc = LocalOEECalculator("m", ideal_cycle_time=30.0)
        _ran_an_hour(calc, 60)  # 60 parts x 30s = 1800s of ideal work in 3600s of running
        self.assertEqual(calc.calculate_performance(), 50.0)

    def test_the_hardcoded_sixty_is_gone(self):
        """The constant itself. A default reintroduced 'so it always returns something'
        restores the defect exactly, and would pass every behavioural test above for any
        machine that happens to have a 60-second cycle."""
        calc = LocalOEECalculator("m")
        self.assertIsNone(
            calc.ideal_cycle_time,
            "LocalOEECalculator has a default cycle time again; performance is once more "
            "measured against a number that describes no particular machine",
        )


class TestTheConfigurationSeamWorks(unittest.TestCase):
    def setUp(self) -> None:
        oee_tracker.reset()

    def _msg(self, asset_id: str, state: str, **payload):
        return {
            "asset_id": asset_id,
            "collector_type": "packml",
            "timestamp_edge": datetime.now(timezone.utc).isoformat(),
            "payload": {"packml_state": state, **payload},
        }

    def test_a_configured_rate_reaches_the_calculator(self):
        oee_tracker.configure("a1", 30.0)
        oee_tracker.record(self._msg("a1", "Execute"))
        result = oee_tracker.record(self._msg("a1", "Stopped", total_parts=10, good_parts=10))
        self.assertIsNotNone(result)
        self.assertIsNone(
            result["oee_unavailable_reason"],
            "the configured rate did not reach the calculator",
        )

    def test_configuring_after_the_first_message_still_applies(self):
        """Collector registration and the first telemetry message race in practice, and
        an agent that only honoured configuration set before the first reading would work
        on a developer's laptop and not on a machine that is already running."""
        oee_tracker.record(self._msg("a2", "Execute"))
        oee_tracker.configure("a2", 30.0)
        result = oee_tracker.record(self._msg("a2", "Stopped", total_parts=10, good_parts=10))
        self.assertIsNone(result["oee_unavailable_reason"])

    def test_a_nonsense_rate_is_refused_rather_than_clamped(self):
        """Zero, negative and non-numeric are rejected. Clamping to a minimum would
        resurrect an invented number by another route."""
        for bad in (0, -5, "fast", None, ""):
            oee_tracker.reset()
            oee_tracker.configure("a3", bad)
            oee_tracker.record(self._msg("a3", "Execute"))
            result = oee_tracker.record(
                self._msg("a3", "Stopped", total_parts=10, good_parts=10)
            )
            self.assertEqual(
                result["oee_unavailable_reason"],
                "no ideal cycle time configured for this asset",
                f"a cycle time of {bad!r} was accepted as a rate",
            )


class TestTheAgentReadsTheKeyTheBackendWrites(unittest.TestCase):
    """The two sides must agree on the config key, and neither imports the other."""

    def test_main_registers_the_cycle_time_next_to_the_alert_rules(self):
        import pathlib

        main = (
            pathlib.Path(__file__).resolve().parent.parent / "opsgrid_agent" / "main.py"
        ).read_text()
        assert "oee_tracker.configure(" in main, (
            "nothing calls oee_tracker.configure, so no deployment can ever supply a cycle "
            "time and performance is off everywhere"
        )
        assert "ideal_cycle_time_seconds" in main, (
            "main.py no longer reads the ideal_cycle_time_seconds key"
        )

    def test_the_key_matches_the_backend(self):
        import pathlib

        calc = (
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "backend"
            / "app"
            / "services"
            / "oee_calculator.py"
        )
        if not calc.exists():  # pragma: no cover - backend not checked out
            self.skipTest("backend not present")
        self.assertIn(
            "ideal_cycle_time_seconds",
            calc.read_text(),
            "the backend no longer reads `ideal_cycle_time_seconds`, so the agent and the "
            "cloud now expect different config keys for the same machine property",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
