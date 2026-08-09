"""A machine state nobody could read is not a machine that stopped (FS-462).

`PackMLStateMapper.map_state` translates whatever string a PLC reports into a PackML state.
For anything it did not recognise it returned `PackMLState.IDLE` — **and `IDLE` is in
`AVAILABILITY_LOSS_STATES`**. So a vendor string outside the asset type's mapping was
recorded as downtime, and a machine running at full rate appeared to be stopped.

HOW LIKELY IS A MISS. The default maps are per asset type and do not overlap:
`create_mapper_for_asset_type("3d_printer")` knows "printing" and not "running"; the CNC map
knows "running" and not "printing". One wrong `asset_type` in a config, one firmware update
that renames a state, or one machine whose vendor says "in_progress" is enough. Verified
before the fix: a printer mapper given "running" returned `Idle`, `is_availability_loss` was
True, and the only trace was a single log line.

THREE THINGS SAID IT WAS WRONG, all of them already in the file:

  * `get_state_category` has an `"unknown"` branch — **dead code**, unreachable because
    every enum member was in one of the two category sets;
  * `get_unknown_states()` exists as a public accessor and **nothing outside the module
    calls it**, so the record of what could not be mapped never left the object;
  * the warning fires once per DISTINCT string, on a device that by construction may be
    unable to ship logs — so the one line recording a permanently mis-measured machine
    could also be the one that is lost.

WHAT CHANGED. `PackMLState.UNDEFINED`, in neither category set, which revives the "unknown"
branch. A counter, `edge_packml_unmapped_total`, labelled by asset TYPE — the vendor string
is arbitrary text off a PLC and would hand unbounded cardinality to Prometheus. And time
spent in an unmapped state is excluded from availability's denominator rather than counted as
downtime, which is the standard OEE treatment of excluded time and the same rule as
everywhere else in this codebase: a count must not stand in for a measurement.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from prometheus_client import REGISTRY

from opsgrid_agent.analytics.local_oee import LocalOEECalculator
from opsgrid_agent.packml import (
    AVAILABILITY_LOSS_STATES,
    PRODUCTIVE_STATES,
    PackMLState,
    create_mapper_for_asset_type,
)


class TestAnUnmappedStateIsNotIdle(unittest.TestCase):
    def test_a_printer_reporting_running_is_not_recorded_as_stopped(self):
        """The exact reproduction. "running" is a CNC word; the printer map has "printing"."""
        mapper = create_mapper_for_asset_type("3d_printer")
        state = mapper.map_state("running")
        self.assertEqual(state, PackMLState.UNDEFINED)
        self.assertFalse(
            mapper.is_availability_loss(state),
            "a state the mapper could not read was counted as downtime — a machine running "
            "at full rate recorded as stopped",
        )
        self.assertFalse(mapper.is_productive(state), "nor may it be counted as running")
        self.assertEqual(mapper.get_state_category(state), "unknown")

    def test_a_state_it_does_understand_still_maps(self):
        """The other direction: a mapper that returns UNDEFINED for everything passes the
        test above and destroys the feature."""
        mapper = create_mapper_for_asset_type("3d_printer")
        self.assertEqual(mapper.map_state("printing"), PackMLState.EXECUTE)
        self.assertTrue(mapper.is_productive(mapper.map_state("printing")))

    def test_a_genuinely_idle_machine_is_still_idle(self):
        """The sharp distinction. "idle" IS mapped, and idle time IS availability loss —
        that is a real measurement and must not be blanked."""
        mapper = create_mapper_for_asset_type("3d_printer")
        state = mapper.map_state("idle")
        self.assertEqual(state, PackMLState.IDLE)
        self.assertTrue(mapper.is_availability_loss(state))

    def test_an_absent_state_is_undefined_rather_than_idle(self):
        mapper = create_mapper_for_asset_type("generic")
        self.assertEqual(mapper.map_state(""), PackMLState.UNDEFINED)

    def test_undefined_is_in_neither_category(self):
        """The property the whole fix rests on. If someone later adds UNDEFINED to
        AVAILABILITY_LOSS_STATES "for completeness", the defect returns in full."""
        self.assertNotIn(PackMLState.UNDEFINED, AVAILABILITY_LOSS_STATES)
        self.assertNotIn(PackMLState.UNDEFINED, PRODUCTIVE_STATES)

    def test_every_real_packml_state_is_still_categorised(self):
        """UNDEFINED is the ONLY uncategorised member. A real state falling out of both
        sets would be silently excluded from availability, which is this defect inverted."""
        uncategorised = set(PackMLState) - PRODUCTIVE_STATES - AVAILABILITY_LOSS_STATES
        self.assertEqual(
            uncategorised,
            {PackMLState.UNDEFINED},
            "a genuine PackML state is in neither category set; its time would be excluded "
            "from availability's denominator as though nobody could read it",
        )


class TestTheMissIsCounted(unittest.TestCase):
    def _value(self, asset_type: str) -> float:
        # `or 0.0` on the READ, not at each call site: a labelled counter does not exist
        # in the registry until it is first incremented, so an untouched label reads None.
        # The first draft normalised only the "before" side and compared None to 0.0,
        # which failed on test ordering rather than on anything about the product.
        return REGISTRY.get_sample_value(
            "edge_packml_unmapped_total", {"asset_type": asset_type}
        ) or 0.0

    def test_each_occurrence_increments_not_just_the_first(self):
        """The log warns once per distinct string. The counter must not, or a machine
        reporting one unmapped state forever registers as a single event."""
        mapper = create_mapper_for_asset_type("cnc")
        before = self._value("cnc")
        for _ in range(3):
            mapper.map_state("printing")  # a printer word, on a CNC map
        self.assertEqual(self._value("cnc"), before + 3)

    def test_a_mapped_state_does_not_increment(self):
        mapper = create_mapper_for_asset_type("cnc")
        mapper.map_state("running")  # genuinely in the CNC map
        before = self._value("cnc")
        mapper.map_state("running")
        self.assertEqual(self._value("cnc"), before)


class TestUnmeasuredTimeIsNotDowntime(unittest.TestCase):
    def test_a_wholly_unreadable_window_reports_no_availability(self):
        now = datetime.now(timezone.utc)
        calc = LocalOEECalculator("m")
        calc.add_state_change("Undefined", "Undefined", now, 8 * 3600)
        result = calc.calculate_oee()
        self.assertIsNone(
            result["availability"],
            "0% would say the machine was down all shift, when in truth nothing could "
            "read what it reported",
        )
        self.assertEqual(
            result["oee_unavailable_reason"], "no interpretable machine states in the window"
        )

    def test_availability_is_taken_over_the_readable_part_of_the_window(self):
        """4h unreadable + 2h Execute in an 8h window is 50%, not 25%. The unreadable half
        is excluded from the denominator, not scored as downtime."""
        now = datetime.now(timezone.utc)
        calc = LocalOEECalculator("m")
        calc.add_state_change("Execute", "Undefined", now - timedelta(hours=2), 4 * 3600)
        calc.add_state_change("Stopped", "Execute", now, 2 * 3600)
        self.assertEqual(calc.calculate_availability(), 50.0)

    def test_an_idle_machine_still_scores_zero(self):
        """Availability must not become None just because it is low. A machine that sat
        idle all shift really was available 0% of the time — a measurement, and the single
        most useful one this calculator produces."""
        now = datetime.now(timezone.utc)
        calc = LocalOEECalculator("m")
        calc.add_state_change("Stopped", "Idle", now, 8 * 3600)
        self.assertEqual(calc.calculate_availability(), 0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
