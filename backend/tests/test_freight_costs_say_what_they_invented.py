"""Two fabricated defaults compounding into a billed figure — and the fix (FS-665).

**THIS FILE PINNED A DEFECT AND NOW PINS ITS FIX.** It was written first as a description of
what the code did, because the repair was a decision about what the endpoint promises rather
than a wiring change. The decision was taken: **when the distance is unknown the endpoint
reports the charge as not estimated rather than inventing one**, which is the same answer
FS-533 gave for the fuel surcharge and the same shape `distance_miles: Optional[float]`
already had on the wire.

THE TWO DEFAULTS, independent and in the same call chain:

  * `get_shipment_costs` — `distance = route.total_distance_miles if … else **500.0**`
  * `calculate_linehaul` — `rate_per_mile = rate_per_mile or **2.50**`

Neither was reachable from the other, and neither said it fired. A shipment with no route and
no contract rate was billed 500 invented miles at an invented $2.50 — $1,333.33 in total — and
the endpoint reported `distance_miles: 500.0` as fact, which the Transportation page rendered
as "500 mi".

WHAT EACH BECAME. The distance fallback is **gone**: `None` now reaches both calculators and
both answer `amount: None` with `rate_basis: "not_estimated"`. The rate default is **kept and
labelled**, exactly as FS-533 kept the fleet-average surcharge and labelled it — an
uncontracted carrier is still billed the list rate, and `assumptions.basis` now says
`default_list_rate` where a contracted one says `contract_rate`. Those two were previously
byte-identical at the same value.

WHY IT SURVIVED. The 500 has a comment beside it explaining a Decimal/float TypeError, and
that comment is correct and load-bearing; the fabrication went unremarked next to a real fix.
The 2.50 is labelled `# Default rates if not specified`, which is true and says nothing about
the fact that the result is then billed.

WHAT THE CONTRACT CHANGE COST. `linehaul.amount`, `fuel_surcharge.amount`, `mileage_charge`,
`weight_charge` and `total_cost` are now `Optional[float]`, and the TypeScript follows. The
page renders an em dash rather than `$0.00` and carries one line saying why — the same
argument its own comment already made about accessorials: *a zero in a cost breakdown reads
as "nothing was charged" rather than "not calculated here"*.

That `distance_miles` was already `Optional[float]`, already `number | null` in the client,
and already hidden by the page when absent is what made the change small. The contract could
express "unknown" the whole time; only the server declined to.
"""

from __future__ import annotations

import pytest

from app.services.transportation_management import FreightBillingEngine

#: The two literals, named once so the tests read as a description rather than magic numbers.
FABRICATED_DISTANCE = 500.0
FABRICATED_RATE = 2.50


@pytest.fixture
def engine() -> FreightBillingEngine:
    return FreightBillingEngine()


class TestTheRateIsLabelledRatherThanHidden:
    async def test_an_uncontracted_carrier_is_billed_the_list_rate(self, engine):
        """Unchanged behaviour, deliberately. Removing the default would refuse to price
        every uncontracted shipment, which is a bigger change than this defect warrants —
        FS-533 made the same call for the fuel surcharge."""
        charge = await engine.calculate_linehaul(
            distance_miles=1.0, weight_lbs=0.0, contract_rates=None
        )
        assert charge["amount"] == FABRICATED_RATE

    async def test_and_the_response_says_the_rate_was_a_default(self, engine):
        """THE FIX for the rate. Previously nothing in the payload distinguished this from a
        negotiated rate."""
        charge = await engine.calculate_linehaul(
            distance_miles=1.0, weight_lbs=0.0, contract_rates=None
        )
        assert charge["assumptions"]["basis"] == "default_list_rate"

    async def test_a_contract_rate_is_named_as_one(self, engine):
        charge = await engine.calculate_linehaul(
            distance_miles=1.0, weight_lbs=0.0, contract_rates={"per_mile": 4.10}
        )
        assert charge["amount"] == 4.10
        assert charge["assumptions"]["basis"] == "contract_rate"

    async def test_the_two_are_no_longer_byte_identical(self, engine):
        """The property that made the figure dangerous. A fabricated rate and a contracted
        one at the SAME VALUE used to produce identical results, so no caller could tell them
        apart. This is the assertion that inverts."""
        invented = await engine.calculate_linehaul(
            distance_miles=500.0, weight_lbs=0.0, contract_rates=None
        )
        contracted = await engine.calculate_linehaul(
            distance_miles=500.0, weight_lbs=0.0, contract_rates={"per_mile": FABRICATED_RATE}
        )
        assert invented["amount"] == contracted["amount"], "same rate, same money"
        assert invented != contracted, (
            "a defaulted rate and a contracted one at the same value are still "
            "indistinguishable — the label is not reaching the payload"
        )


class TestNoDistanceMeansNoEstimate:
    async def test_the_linehaul_is_not_estimated(self, engine):
        """THE FIX for the distance. There is no honest number: 0 fabricates a cheap shipment
        exactly as 500 fabricated an expensive one, so the charge declines."""
        charge = await engine.calculate_linehaul(
            distance_miles=None, weight_lbs=0.0, contract_rates=None
        )
        assert charge["amount"] is None
        assert charge["rate_basis"] == "not_estimated"
        assert charge["assumptions"]["basis"] == "distance_unavailable"

    async def test_the_fuel_surcharge_is_not_estimated_either(self, engine):
        """`distance * rate` on both sides, so both decline together. A surcharge estimated
        beside a linehaul that could not be would be the same lie, half as large."""
        charge = await engine.calculate_fuel_surcharge(
            distance_miles=None, contract_rates=None
        )
        assert charge["amount"] is None
        assert charge["rate_basis"] == "not_estimated"

    async def test_the_charge_says_what_to_do_about_it(self, engine):
        """A refusal with no next step is only marginally better than a wrong number."""
        charge = await engine.calculate_linehaul(
            distance_miles=None, weight_lbs=0.0, contract_rates=None
        )
        assert "route" in charge["assumptions"]["note"].lower()

    async def test_a_real_distance_still_bills(self, engine):
        """The control. If this failed the fix would have stopped pricing every shipment."""
        charge = await engine.calculate_linehaul(
            distance_miles=500.0, weight_lbs=0.0, contract_rates={"per_mile": 2.00}
        )
        assert charge["amount"] == 1000.00


class TestTheCompoundingIsGone:
    async def test_the_thirteen_hundred_dollars_is_no_longer_invented(self, engine):
        """The finding, inverted. This exact call produced $1,333.33 of fabricated cost for a
        shipment with no route and no contract; both components now decline."""
        linehaul = await engine.calculate_linehaul(
            distance_miles=None, weight_lbs=0.0, contract_rates=None
        )
        surcharge = await engine.calculate_fuel_surcharge(
            distance_miles=None, contract_rates=None
        )
        assert linehaul["amount"] is None and surcharge["amount"] is None, (
            "a shipment with no route and no contract rate was billed $1,333.33, every cent "
            "from two defaults that did not know about each other"
        )

    def test_the_distance_fallback_is_gone_from_the_source(self):
        """Pins the removal. If somebody reintroduces a numeric fallback for an absent
        distance, this is the test that should stop them."""
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "services" / "transportation_management.py"
        ).read_text()
        assert "else 500.0" not in source, (
            "the 500-mile fallback is back. There is no honest number for an unknown "
            "distance — see this module's docstring."
        )
