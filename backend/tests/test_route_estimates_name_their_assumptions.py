"""A route cost estimate must say what it rests on (FS-348).

THE DEFECT, AND WHY IT IS HARDER TO SEE THAN A RANDOM NUMBER.

`RouteOptimizer.optimize_route` computed three figures from four literals written inline:

    estimated_hours = total_distance / 50          # avg 50 mph
    fuel_gallons    = total_distance / 6           # 6 mpg
    fuel_cost       = fuel_gallons * 3.50          # $3.50/gal
    toll_cost       = total_distance * 0.05        # 5 cents per mile

The distance those multiply is real — `app.services.routing` does haversine, or OSRM road
distance when configured. The four constants are not measurements of anything: they are a
national average from an unrecorded date. A fleet of electric vans, or a region with no toll
roads, gets a confidently wrong number.

**Deterministic output reads as computed.** A random figure at least looks suspicious under
inspection; `$412.50` does not, which is why this survived longer than the GeoTab
fabrications did.

AND THE OUTPUT IS PERSISTED. `create_route` writes all three onto
`routes.estimated_duration_hours`, `.fuel_cost_estimate` and `.toll_cost_estimate`, and
`GET /transportation/routes` serves them — so the guess becomes a stored per-route cost that
outlives the request.

WHAT THE FIX IS AND IS NOT. The constants are now settings, so an operator can set them to
their own fleet, and `optimize_route` returns the `assumptions` it used beside the figures.
That does not make the estimate a quote. It makes what the estimate rests on visible to
whoever reads it — the same standard applied to the GeoTab simulator in FS-267.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.transportation_management import RouteOptimizer

# Chicago → Milwaukee, roughly 80 miles apart. Real coordinates so the distance comes from
# the routing seam rather than the no-coordinates fallback.
ORIGIN = {"latitude": 41.8781, "longitude": -87.6298, "city": "Chicago"}
DESTINATION = {"latitude": 43.0389, "longitude": -87.9065, "city": "Milwaukee"}


def _optimize(**over):
    return RouteOptimizer().optimize_route(
        origin=over.pop("origin", ORIGIN),
        destination=over.pop("destination", DESTINATION),
        **over,
    )


class TestTheAssumptionsAreVisible:
    def test_the_payload_names_every_constant_it_used(self):
        """The whole point. A consumer reading `fuel_cost_estimate` can see the fuel price
        and the mpg it came from, in the same response."""
        result = _optimize()
        assumptions = result["assumptions"]
        assert assumptions["average_speed_mph"] == settings.FLEET_AVERAGE_SPEED_MPH
        assert assumptions["average_mpg"] == settings.FLEET_AVERAGE_MPG
        assert assumptions["fuel_price_usd_per_gallon"] == settings.FUEL_PRICE_USD_PER_GALLON
        assert assumptions["toll_usd_per_mile"] == settings.TOLL_COST_USD_PER_MILE

    def test_it_says_the_figures_are_not_a_quote(self):
        assert "not" in _optimize()["assumptions"]["note"].lower()

    def test_it_names_the_distance_source_separately(self):
        """The distance is the one figure here that IS measured, so its provenance is
        reported separately from the assumed constants — conflating them would understate
        the distance and overstate the costs."""
        assert _optimize()["assumptions"]["distance_source"] == settings.ROUTING_PROVIDER


class TestTheFiguresFollowTheSettings:
    """The constants were inline, so changing a fleet's mpg meant editing a service. These
    assert the arithmetic actually reads the settings rather than merely reporting them."""

    def test_fuel_cost_moves_with_the_configured_price(self, monkeypatch):
        cheap = _optimize()
        monkeypatch.setattr(settings, "FUEL_PRICE_USD_PER_GALLON", 7.00)
        dear = _optimize()
        assert dear["fuel_cost_estimate"] > cheap["fuel_cost_estimate"], (
            "fuel cost ignored the configured price — the literal is still in the formula"
        )

    def test_fuel_cost_moves_with_the_configured_mpg(self, monkeypatch):
        thirsty = _optimize()
        monkeypatch.setattr(settings, "FLEET_AVERAGE_MPG", 60.0)
        efficient = _optimize()
        assert efficient["fuel_cost_estimate"] < thirsty["fuel_cost_estimate"]

    def test_duration_moves_with_the_configured_speed(self, monkeypatch):
        slow = _optimize()
        monkeypatch.setattr(settings, "FLEET_AVERAGE_SPEED_MPH", 100.0)
        fast = _optimize()
        assert fast["estimated_duration_hours"] < slow["estimated_duration_hours"]

    def test_a_toll_free_region_can_be_configured_to_zero(self, monkeypatch):
        """`* 0.05` was unconditional, so every route in every region carried a toll."""
        monkeypatch.setattr(settings, "TOLL_COST_USD_PER_MILE", 0.0)
        assert _optimize()["toll_cost_estimate"] == 0.0


class TestMisconfigurationDoesNotFiveHundred:
    """These are operator-settable now, so a zero is reachable from config rather than
    from code — and a ZeroDivisionError on a request path would show the operator a 500
    instead of the reason."""

    def test_zero_mpg_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(settings, "FLEET_AVERAGE_MPG", 0.0)
        assert _optimize()["fuel_cost_estimate"] == 0.0

    def test_zero_speed_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(settings, "FLEET_AVERAGE_SPEED_MPH", 0.0)
        result = _optimize()
        assert result["estimated_duration_hours"] >= 0.0


class TestTheDistanceIsStillReal:
    def test_a_longer_trip_costs_more(self, monkeypatch):
        """Guards against the fix flattening the one measured input into a constant too."""
        near = _optimize(destination={"latitude": 42.0, "longitude": -87.7})
        far = _optimize(destination={"latitude": 47.6062, "longitude": -122.3321})
        assert far["total_distance_miles"] > near["total_distance_miles"]
        assert far["fuel_cost_estimate"] > near["fuel_cost_estimate"]

    def test_waypoints_add_stop_time(self):
        direct = _optimize()
        with_stop = _optimize(waypoints=[{"latitude": 42.5, "longitude": -87.8}])
        assert (
            with_stop["estimated_duration_hours"] > direct["estimated_duration_hours"]
        ), "the per-stop allowance is not being applied"


class TestNoInlineConstantsRemain:
    def test_the_formula_reads_settings_not_literals(self):
        """The defect was four numbers in an arithmetic expression. This fails if one comes
        back, which a future edit could easily do while the tests above still pass — they
        assert direction, and a literal would keep the direction right for the default
        configuration."""
        import ast
        import inspect

        source = inspect.getsource(RouteOptimizer.optimize_route)
        tree = ast.parse(source.lstrip())

        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp):
                continue
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, (int, float)):
                    # 60.0 converts stop MINUTES to hours — a unit, not an assumption.
                    if side.value not in (0, 1, 60, 60.0):
                        offenders.append(side.value)

        assert not offenders, (
            f"numeric literals are back in the costing arithmetic: {offenders}. Fleet "
            "assumptions belong in settings, where an operator can see and change them."
        )
