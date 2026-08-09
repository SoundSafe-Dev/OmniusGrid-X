"""A number in a computed response was computed, or says it was not (FS-533).

THE CLASS. Wave F closed "generated figures presented as measurements" for the GeoTab
surface — `random.*` behind a gate, stamped. This is the quieter half of the same class:
**deterministic constants written inline in a response builder**. A random number at least
moves; a hardcoded one reads as a measurement that happens to be steady, which is why it
survives longer.

Two instances, both on screens where the number decides something.

## Driver safety — three constants and a false period

`_driver_safety_out` returned `idleTimeHours: 0`, `seatbeltViolations: 0` and
`trend: "stable"` for every driver in every organisation, forever. The response model's own
docstring recorded this and left it, which is how a documented placeholder becomes a
permanent one.

`seatbeltViolations: 0` is not neutral on a driver safety report. It is a claim that no
driver has ever been recorded unbelted, on the same screen as a score that decides who gets
coached — and it was **counted from the same `geotab_exceptions` rows as the other three the
whole time**. It is now counted.

`period: "30d"` was the outright lie: `_exceptions` applied no time filter, so every count was
lifetime-to-date under a label saying thirty days. A driver's score got worse permanently and
could never recover, because nothing aged out. The query is windowed now, which makes the
label true and makes `trend` a comparison rather than a constant.

`idleTimeHours` is **null**, not zero. Idle time is a duration; `geotab_exceptions` records
events and has no duration column. There is nothing in this schema to compute it from, and a
zero is a measurement.

## Fuel surcharge — a money figure from three default arguments

`calculate_fuel_surcharge` took `base_fuel_price=2.50, current_fuel_price=3.50, mpg=6.0` as
defaults and its only caller passes none of them. Every freight charge the product has
produced came from a dollar-a-gallon differential written in a function signature — and the
response echoed those two prices back beside the amount, where they read as prices something
had looked up.

Worse than stale: **duplicated**. `optimize_route`, in the same class, already reads
`settings.FUEL_PRICE_USD_PER_GALLON` (3.50) and `settings.FLEET_AVERAGE_MPG` (6.0) — the same
numbers, disconnected. An operator setting their own fuel price moved the route estimate and
left every freight charge behind. Identical copies are the state in which divergence is least
likely to be noticed.

And the arithmetic was decorative: `(fuel_diff * (distance / mpg)) / distance` cancels
exactly, so the rate was always `fuel_diff / mpg`. Written to look like a per-mile calculation
over the trip.
"""

from __future__ import annotations

import inspect

import pytest

from app.api import fleet_health
from app.core.config import settings
from app.services.transportation_management import transportation_management_service


@pytest.mark.asyncio
class TestTheFuelSurchargeSaysWhatItRestsOn:
    """ASYNC, not `run_until_complete`. The first version drove the coroutine with
    `asyncio.get_event_loop().run_until_complete`, which passes when this file runs alone and
    fails inside the suite: pytest-asyncio owns the loop there, and grabbing it to run
    something synchronously either finds it already running or gets a fresh one the fixtures
    are not bound to. A test that passes in isolation and fails in company is testing the
    harness, not the code."""

    async def _surcharge(self, **kwargs):
        return await transportation_management_service.billing_engine.calculate_fuel_surcharge(
            distance_miles=500.0, **kwargs
        )

    async def test_no_price_is_a_hardcoded_default_argument(self):
        """The defect exactly. A money input with a literal default that no caller overrides
        is a number the operator cannot change and cannot see."""
        signature = inspect.signature(
            transportation_management_service.billing_engine.calculate_fuel_surcharge
        )
        literal_defaults = {
            name: parameter.default
            for name, parameter in signature.parameters.items()
            if isinstance(parameter.default, (int, float))
        }
        assert not literal_defaults, (
            f"{literal_defaults} are numeric literals defaulted in the signature of a "
            f"function that produces a billable amount. The only caller passes none of "
            f"them, so these ARE the figure. Read them from settings."
        )

    async def test_it_reads_the_same_settings_the_route_estimate_does(self):
        """`optimize_route` and this function are two figures on the same shipment. Before
        FS-533 they used numerically identical, entirely separate constants."""
        result = await self._surcharge()
        assert result["assumptions"]["current_fuel_price_usd_per_gallon"] == (
            settings.FUEL_PRICE_USD_PER_GALLON
        ), (
            "the surcharge uses a fuel price the route estimate does not. An operator who "
            "configures FUEL_PRICE_USD_PER_GALLON moves one figure and not the other."
        )
        assert result["assumptions"]["average_mpg"] == settings.FLEET_AVERAGE_MPG

    async def test_the_response_names_its_basis(self):
        result = await self._surcharge()
        assert result["assumptions"]["basis"] == "configured_fleet_assumptions", (
            "the surcharge does not say the amount came from configured averages rather "
            "than a carrier contract"
        )
        assert "not a carrier quote" in result["assumptions"]["note"]

    async def test_a_contract_table_is_named_as_a_default_lookup(self):
        """The contract branch takes `table['default']` and does not index by price — its
        source comment says "Implementation would look up based on current fuel price". A
        caller with a contract must be able to tell that their banded rate was not applied."""
        result = await self._surcharge(
            contract_rates={"fuel_surcharge_table": {"default": 0.42}}
        )
        assert result["assumptions"]["basis"] == "contract_table_default_entry"
        assert result["amount"] == pytest.approx(500.0 * 0.42, rel=1e-6)

    async def test_the_amount_did_not_change(self):
        """Behaviour-preserving on value. This fix is about what the response SAYS, and a
        silent repricing would be a much larger change than the one intended."""
        result = await self._surcharge()
        assert result["amount"] == pytest.approx(83.33, abs=0.01)


class TestDriverSafetyReportsWhatItMeasures:
    def test_the_window_is_applied_and_labelled_from_one_place(self):
        source = inspect.getsource(fleet_health)
        assert 'f"{SAFETY_WINDOW_DAYS}d"' in source, (
            'the period label is a literal again. It read "30d" while the query applied no '
            "time filter at all, so every count was lifetime-to-date — the label and the "
            "filter have to come from the same constant or they drift apart again."
        )
        assert "since=window_start" in source or "since=previous_start" in source, (
            "the safety query no longer passes a window, so `period` is a claim about a "
            "filter that is not applied"
        )

    def test_seatbelt_violations_are_counted_not_declared(self):
        driver = type("D", (), {"id": "d1", "first_name": "A", "last_name": "B"})()
        out = fleet_health._driver_safety_out(driver, {"seatbelt": 3, "speeding": 1})
        assert out["seatbeltViolations"] == 3, (
            "seatbeltViolations is not counted from the exception rows. A hardcoded 0 on a "
            "safety report is a claim that no driver has ever been recorded unbelted."
        )

    def test_every_known_spelling_is_counted(self):
        """`exception_type` is a free-form string and GeoTab spells this differently across
        firmware. Missing a spelling under-counts a safety figure, which is the direction
        that looks like good news."""
        driver = type("D", (), {"id": "d1", "first_name": "A", "last_name": "B"})()
        for spelling in fleet_health.SEATBELT_EXCEPTION_TYPES:
            out = fleet_health._driver_safety_out(driver, {spelling: 2})
            assert out["seatbeltViolations"] == 2, f"{spelling!r} is not counted"

    def test_idle_time_is_null_rather_than_zero(self):
        driver = type("D", (), {"id": "d1", "first_name": "A", "last_name": "B"})()
        out = fleet_health._driver_safety_out(driver, {})
        assert out["idleTimeHours"] is None, (
            "idleTimeHours is a number again. `geotab_exceptions` records events with no "
            "duration column, so there is nothing to compute hours from — and a zero is a "
            "measurement, which is the whole class this fix is in."
        )

    def test_trend_is_a_comparison_and_null_without_one(self):
        driver = type("D", (), {"id": "d1", "first_name": "A", "last_name": "B"})()

        assert fleet_health._driver_safety_out(driver, {"speeding": 1})["trend"] is None, (
            'with no previous window there is nothing to compare, and "stable" would be a '
            "claim rather than an observation — which is what it was for every driver"
        )
        worse = fleet_health._driver_safety_out(driver, {"speeding": 5}, {"speeding": 1})
        assert worse["trend"] == "worsening"
        better = fleet_health._driver_safety_out(driver, {"speeding": 1}, {"speeding": 5})
        assert better["trend"] == "improving"
        same = fleet_health._driver_safety_out(driver, {"speeding": 2}, {"speeding": 2})
        assert same["trend"] == "stable"

    def test_both_routes_share_the_builder(self):
        """The list and the per-driver page must not score the same driver differently —
        FS-492's shape, where one caller keeps a private copy of what another computes."""
        source = inspect.getsource(fleet_health)
        assert source.count("_driver_safety_out(") >= 3, (
            "one of the two safety routes stopped using the shared builder"
        )
