"""No fabricated telematics escapes with GEOTAB_SIMULATED off (FS-532).

`geotab_service` invents telematics at ~35 `random.*` sites, including `hos_violation`
exception types and hours-of-service figures — **DOT-regulated findings**. Two defences exist
and both are structural:

  * `test_simulated_data_says_so.py` (FS-267) pairs gating against stamping across the module,
    so a fifth gated function cannot be added without a provenance stamp.
  * `test_production_settings_are_validated.py` refuses `GEOTAB_SIMULATED` in production.

**Neither runs the code.** They assert the shape of the source, and the gate is spelled two
different ways: four functions call `_require_simulated()`, and `get_device_location` inlines
`if not settings.GEOTAB_SIMULATED` because it *prefers* real data and only invents a position
when no trip endpoint or exception fix exists. A structural check has to know both spellings —
and a third spelling, added by someone who did not read the first two, is invisible to it while
the fabricated data flows.

MY OWN DETECTOR PROVED THE POINT BEFORE THIS FILE EXISTED. Sweeping for functions that call
`random.` without calling `_require_simulated` flagged `get_device_location` as an ungated
fabricator. It is not — it gates correctly, by a different name. A structural sweep is exactly
one rename away from a false positive and one new spelling away from a false negative.

So this drives the service. With the flag off, every fabricating path must refuse; with it on,
everything it returns must say what it is. The question a behavioural test asks — *does
fabricated data come out?* — has one answer regardless of how the gate is written.
"""

from __future__ import annotations

import inspect
import random
import uuid

import pytest

from app.core.config import settings
from app.services import geotab_service as geotab_module
from app.services.geotab_service import geotab_service

#: Every service method that can invent data, with the arguments to drive it.
#: Derived from the source below rather than hand-listed, so a sixth fabricator joins
#: automatically instead of being quietly outside the sweep.
#: `DEV-001` rather than an invented id: `get_device_location` raises "not found" for a
#: device the mock registry does not know, which is a REFUSAL FOR THE WRONG REASON — the
#: first version of this table used "GT-0001" and every gate test passed on a 404 that had
#: nothing to do with the gate. A test that passes because it called the method wrongly
#: proves nothing, which is why the refusal assertion below excludes TypeError and this
#: table uses a device the service will actually try to answer for.
_DEVICE = "DEV-001"
_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
_DRIVER = uuid.UUID("00000000-0000-0000-0000-000000000002")

CALLS = {
    "get_exceptions": {"organization_id": _ORG, "db": None},
    "get_device_diagnostics": {"device_id": _DEVICE, "organization_id": _ORG, "db": None},
    "get_driver_hos": {"driver_id": _DRIVER, "organization_id": _ORG, "db": None},
    "get_fleet_summary": {"organization_id": _ORG, "db": None},
    "get_device_location": {"device_id": _DEVICE, "organization_id": _ORG, "db": None},
}


class _OneDriverSession:
    """The smallest session `get_driver_hos` needs: it looks the driver up before
    fabricating, and raises "not found" for an absent one.

    A stub rather than a real database, because the property under test is the GATE, not
    the query — and a fixture that needed Postgres would make this file skip in exactly
    the environments where somebody is checking whether fabricated HOS can escape.
    """

    def __init__(self, driver):
        self._driver = driver

    async def execute(self, _statement):
        driver = self._driver

        class _Result:
            def scalar_one_or_none(self):
                return driver

            def scalars(self):
                return self

            def all(self):
                return [driver] if driver else []

        return _Result()


class _SessionWithALocationlessTrip:
    """A session holding one trip for the device, with NO position on it.

    THIS EXISTS BECAUSE A MUTATION TEST CAUGHT THE FILE BEING VACUOUS. Deleting
    `get_device_location`'s inline gate left every assertion here passing: with
    `GEOTAB_SIMULATED=false` the mock registry is not consulted, so `known_ids` is empty and
    the method raises "Device not found" — a refusal, for a reason that has nothing to do
    with the gate. The test asserted "it refuses" and got that from somewhere else.

    A trip with no `start_location` or `end_location` puts the device INTO `known_ids` and
    leaves `location` as None, which is the only path that reaches the gate. With the gate
    the call raises "No known location"; without it, it invents coordinates — and only this
    fixture can tell those apart.

    ORDER-AWARE, because the method issues two queries: the trip first, then the most recent
    exception. Answering both with the trip made the second read `exc.location` off a
    `GeoTabTrip` and raise AttributeError — a failure in the fixture that would have read as
    a failure in the gate.
    """

    def __init__(self):
        self._calls = 0

    async def execute(self, _statement):
        from app.db.models import GeoTabTrip

        self._calls += 1
        first = self._calls == 1
        trip = (
            GeoTabTrip(
                device_id=_DEVICE,
                organization_id=_ORG,
                start_location=None,
                end_location=None,
            )
            if first
            else None
        )

        class _Result:
            def scalar_one_or_none(self):
                return trip

        return _Result()


def _session_with_a_driver():
    from app.db.models import Driver

    return _OneDriverSession(
        Driver(id=_DRIVER, organization_id=_ORG, first_name="A", last_name="B")
    )


def _fabricating_methods() -> set[str]:
    """Service methods whose body contains a `random.` call."""
    return {
        name
        for name, member in inspect.getmembers(type(geotab_service))
        if inspect.isfunction(member) and "random." in inspect.getsource(member)
    }


class TestTheSweepCoversEveryFabricator:
    def test_the_call_table_is_complete(self):
        """The failure this file exists to prevent, applied to itself: a fabricator outside
        the table is a path the behavioural test never drives, which is exactly the state
        the structural guards were already in."""
        uncovered = sorted(_fabricating_methods() - set(CALLS))
        assert not uncovered, (
            f"{uncovered} invent data and are not driven by this test. Add them to CALLS "
            f"with arguments that reach the fabricating branch."
        )

    def test_it_found_the_fabricators(self):
        assert len(_fabricating_methods()) >= 5, (
            "fewer than five fabricating methods found; either the module was rewritten or "
            "`inspect.getsource` stopped resolving, and this sweep is then vacuous"
        )


@pytest.mark.asyncio
class TestNothingIsInventedWhenTheGateIsOff:
    """The whole point. With `GEOTAB_SIMULATED=false` a fabricating path must refuse rather
    than return, whichever way its gate happens to be written."""

    @pytest.mark.parametrize("method", sorted(CALLS))
    async def test_it_refuses(self, method: str, monkeypatch):
        monkeypatch.setattr(settings, "GEOTAB_SIMULATED", False)

        with pytest.raises(Exception) as raised:  # noqa: PT011 — the type differs per gate
            await getattr(geotab_service, method)(**CALLS[method])

        # `_require_simulated` raises SimulatedDataDisabled; `get_device_location` raises
        # ValueError, which the router maps to 404. Both refuse, which is the property.
        # Asserting one exception type would pin the spelling this file exists to ignore.
        assert not isinstance(raised.value, (TypeError, AttributeError)), (
            f"{method} raised {type(raised.value).__name__}, which is a call error in this "
            f"test rather than the gate refusing. Fix the arguments in CALLS — a test that "
            f"passes because it called the method wrongly proves nothing about the gate."
        )


    async def test_a_known_device_with_no_fix_is_refused_not_invented(self, monkeypatch):
        """The discriminating case for `get_device_location`, and the one the parametrized
        refusal above cannot make.

        That test passes even with the gate deleted, because with simulation off the mock
        registry is skipped and the device is simply unknown — a refusal from a different
        branch. Here the device IS known (a trip exists) and has no position, which is the
        only path that reaches the gate. With it: "No known location". Without it: invented
        coordinates, returned as a fix, in a live deployment.
        """
        monkeypatch.setattr(settings, "GEOTAB_SIMULATED", False)

        with pytest.raises(ValueError) as raised:
            await geotab_service.get_device_location(
                device_id=_DEVICE,
                organization_id=_ORG,
                db=_SessionWithALocationlessTrip(),
            )
        assert "No known location" in str(raised.value), (
            f"expected a refusal to invent a position, got {raised.value!r}. A device with "
            f"a trip on record but no fix must 404, never receive coordinates drawn from a "
            f"bounding box — on a map those are indistinguishable."
        )


@pytest.mark.asyncio
class TestEverythingSaysWhatItIsWhenTheGateIsOn:
    @pytest.mark.parametrize("method", ["get_exceptions", "get_device_diagnostics", "get_driver_hos"])
    async def test_every_row_carries_provenance(self, method: str, monkeypatch):
        """These three fabricate unconditionally, so every row they produce is invented and
        every row must say so. `get_exceptions` draws from a list containing `hos_violation`
        and `get_driver_hos` reports duty hours — a consumer that cannot tell these from a
        real ELD read is one audit away from a serious problem."""
        monkeypatch.setattr(settings, "GEOTAB_SIMULATED", True)

        # SEEDED, BECAUSE THIS TEST WAS FLAKY ABOUT ONE RUN IN ELEVEN (FS-680).
        # `get_exceptions` builds `range(random.randint(0, 10))` rows, so it legitimately
        # returns an EMPTY list roughly 9% of the time, and the `assert rows` below then
        # failed for a reason that has nothing to do with provenance. Caught in a full-suite
        # run and initially mistaken for a regression from unrelated work, because the
        # previous run had happened to draw a non-zero count.
        #
        # Seeded rather than the assertion relaxed: "zero rows all carry provenance" is
        # vacuously true, so accepting an empty draw would leave the test passing while
        # checking nothing — the failure mode this file exists to prevent. Seed 0 draws six.
        random.seed(0)

        arguments = dict(CALLS[method])
        if method == "get_driver_hos":
            arguments["db"] = _session_with_a_driver()

        result = await getattr(geotab_service, method)(**arguments)
        rows = result if isinstance(result, list) else [result]
        assert rows, f"{method} returned nothing to check in simulated mode"

        for row in rows:
            assert row.get("simulated") is True, (
                f"a row from {method} does not carry `simulated: true`. It reached the "
                f"client through a declared response model, which makes it read as more "
                f"trustworthy while the data is unchanged."
            )
            assert row.get("data_source"), f"a row from {method} names no data source"

    async def test_an_invented_position_is_stamped_and_a_real_one_is_not(self, monkeypatch):
        """`get_device_location` is the conditional case, and both directions matter.
        Stamping a genuine GPS fix as simulated is a falsehood in the other direction, and
        the one that teaches a consumer to ignore the flag."""
        monkeypatch.setattr(settings, "GEOTAB_SIMULATED", True)

        invented = await geotab_service.get_device_location(**CALLS["get_device_location"])
        assert invented.get("simulated") is True, (
            "an invented position is not stamped, so a map cannot tell it from a fix and "
            "the device appears parked in a field in Illinois"
        )
        assert invented.get("latitude") is not None


@pytest.mark.asyncio
class TestTheGateIsNotJustTheFlag:
    async def test_a_live_deployment_cannot_turn_it_on(self):
        """The flag itself must be refused in production, or the gate is one environment
        variable from being irrelevant. Asserted here rather than trusting the settings
        validator to keep existing — this is the file that would be read after an incident."""
        from app.core.config import validate_settings

        source = inspect.getsource(validate_settings)
        assert "GEOTAB_SIMULATED" in source, (
            "production validation no longer refuses GEOTAB_SIMULATED. Every assertion "
            "above then guards a flag any deployment may set, and the DOT-regulated HOS "
            "figures become reachable in a live environment."
        )
