"""Two fabricated defaults compounding into a billed figure (FS-665).

**PINS A DEFECT THIS DOES NOT CLOSE.** Every assertion below passes against today's code and
describes what it does, because the fix is a decision about what the endpoint promises rather
than a wiring change — and a finding worth $1,333.33 should not live in a commit message.

THE TWO DEFAULTS, independent and in the same call chain:

  * `get_shipment_costs` — `distance = route.total_distance_miles if … else **500.0**`
  * `calculate_linehaul` — `rate_per_mile = rate_per_mile or **2.50**`

Neither is reachable from the other, and neither says it fired. A shipment with no route and
no contract rate is billed 500 invented miles at an invented $2.50, and the endpoint reports
`distance_miles: 500.0` as fact — the Transportation page renders "500 mi".

WHY IT SURVIVED. The 500 has a comment beside it explaining a Decimal/float TypeError, and
that comment is correct and load-bearing; the fabrication went unremarked next to a real fix.
The 2.50 is labelled `# Default rates if not specified`, which is true and says nothing about
the fact that the result is then billed.

WHY IT IS NOT FIXED HERE. `ShipmentCostsOut.linehaul.amount` and `.total_cost` are
non-optional floats. Answering 0 for an unknown distance fabricates a cheap shipment exactly
as 500 fabricates an expensive one, so there is no honest number — the endpoint has to be able
to say "not estimated", and `LinehaulCharge`/`FuelSurchargeCharge` would need a way to carry
that. There is precedent: `FuelSurchargeCharge` already exists *because* the surcharge is not
always a measurement. Extending the same idea to the linehaul is a contract change with
clients to check, and it is a product decision about what the figure means.

WHAT IS ALREADY HONEST, and worth keeping: `distance_miles` is `Optional[float]` on the wire,
the TypeScript declares `distanceMiles: number | null`, and `TransportationManagement.tsx`
hides the row when it is null. The contract can express "unknown" today; only the server
declines to.
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


class TestWhatAnUnpricedShipmentIsBilled:
    async def test_the_rate_is_invented_when_no_contract_says_otherwise(self, engine):
        """`rate_per_mile or 2.50`. A shipment on a carrier with no negotiated rate is billed
        at a number nobody agreed to, and nothing in the response says so."""
        charge = await engine.calculate_linehaul(
            distance_miles=1.0, weight_lbs=0.0, contract_rates=None
        )
        assert charge["amount"] == FABRICATED_RATE

    async def test_a_real_contract_rate_is_used_when_there_is_one(self, engine):
        """The control. If this failed, the default would be overriding real rates and the
        finding would be far worse than described."""
        charge = await engine.calculate_linehaul(
            distance_miles=1.0, weight_lbs=0.0, contract_rates={"per_mile": 4.10}
        )
        assert charge["amount"] == 4.10

    async def test_the_two_defaults_compound(self, engine):
        """THE FINDING, quantified. This is exactly the call `get_shipment_costs` makes for a
        shipment whose route has no distance and whose carrier has no contract."""
        linehaul = await engine.calculate_linehaul(
            distance_miles=FABRICATED_DISTANCE, weight_lbs=0.0, contract_rates=None
        )
        surcharge = await engine.calculate_fuel_surcharge(
            distance_miles=FABRICATED_DISTANCE, contract_rates=None
        )
        total = linehaul["amount"] + surcharge["amount"]

        assert linehaul["amount"] == 1250.00, "500 invented miles at an invented $2.50"
        assert round(total, 2) == 1333.33, (
            "a shipment with no route and no contract rate is billed $1,333.33, every cent "
            "of it from two defaults that do not know about each other and neither of which "
            "reports that it fired"
        )

    async def test_nothing_in_the_result_marks_the_figure_as_invented(self, engine):
        """The reason the number is dangerous rather than merely wrong. `rateBasis` is the
        field that could carry it — `FuelSurchargeCharge` exists precisely because the
        surcharge is not always a measurement — and it says `per_mile` either way."""
        invented = await engine.calculate_linehaul(
            distance_miles=FABRICATED_DISTANCE, weight_lbs=0.0, contract_rates=None
        )
        real = await engine.calculate_linehaul(
            distance_miles=FABRICATED_DISTANCE, weight_lbs=0.0, contract_rates={"per_mile": 2.50}
        )
        assert invented == real, (
            "a fabricated rate and a contracted one at the same value produce byte-identical "
            "results, so no caller can tell them apart. That is what has to change, and it "
            "is a contract decision rather than a wiring fix."
        )


class TestTheDistanceFallbackIsStillThere:
    def test_the_literal_is_where_this_file_says_it_is(self):
        """Pins the citation, not the behaviour. Rule 129 says cite a section rather than a
        line, and this is the compromise for a bare literal: assert the code still contains
        it, so the day somebody makes it honest this test fails and points here."""
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "services" / "transportation_management.py"
        ).read_text()
        assert "else 500.0" in source, (
            "the 500-mile fallback is gone — if that was deliberate, delete this test and the "
            "finding in the delivery log with it"
        )
        assert "rate_per_mile or 2.50" in source
