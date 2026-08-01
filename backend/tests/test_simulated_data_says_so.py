"""A fabricated figure must say it is fabricated (FS-267).

THE SHAPE OF THIS DEFECT, WHICH IS WHY IT NEEDS A SWEEP AND NOT FOUR ASSERTIONS.

`geotab_service` fabricates telematics with ~30 `random.*` call sites, and it had **two
defences that covered different sets of functions**:

  * `_require_simulated()` (FS-25) raises unless `GEOTAB_SIMULATED` is set, so fabricated
    data cannot reach a live deployment. Called by four functions.
  * `simulated_provenance()` (FS-233) stamps `simulated / data_source / warning` into the
    payload, so a consumer of the *demo* data can tell what it is holding. Applied to two.

The two that were gated but never stamped were `get_exceptions` — which draws
`exception_type` from a list containing `hos_violation`, a DOT-regulated finding — and
`get_device_diagnostics`, which invents DTC codes and cold-chain reefer temperatures. Both
reached the client through a declared response model, so the schema work made them read as
*more* trustworthy while the data was unchanged.

**A partial fix of this class is the dangerous state**, because the two functions that were
stamped are the evidence anyone would cite for believing the class is closed. So the guard
is a sweep over the pairing, not a test of the four functions that exist today: it fails
when a fifth gated function is added without a stamp.

WHAT IT DELIBERATELY DOES NOT ASSERT: that `get_device_location` always stamps. That method
prefers a real trip endpoint or exception fix and only invents a position when neither
exists — so its stamp is conditional, and requiring it unconditionally would demand that a
genuine GPS fix be labelled simulated. Both branches are asserted separately below.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.services import geotab_service as gs

SERVICE = pathlib.Path(gs.__file__)


def _functions_calling(name: str) -> set[str]:
    """Every method whose body calls `name`, found in the syntax rather than by import.

    AST, not `grep`: the docstrings in this area quote both helper names while explaining
    the defect, and a text search cannot tell an explanation from a call. That mistake has
    already been made once in this repo — a `UUID()` sweep that flagged the comment
    describing the fix.
    """
    tree = ast.parse(SERVICE.read_text())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                func = inner.func
                if isinstance(func, ast.Name) and func.id == name:
                    found.add(node.name)
    return found


class TestEveryGatedFunctionAlsoStamps:
    def test_the_sweep_can_see_its_subject(self):
        """A guard that finds nothing passes for the wrong reason."""
        gated = _functions_calling("_require_simulated")
        assert len(gated) >= 4, (
            f"only {len(gated)} gated functions found ({sorted(gated)}); there were 4 when "
            "this was written. Either the AST walk broke or the gate was removed — both "
            "are worth stopping for."
        )

    def test_no_gated_function_ships_unstamped(self):
        """THE ONE THAT MATTERS. Gated and unstamped is fabricated data with no label."""
        gated = _functions_calling("_require_simulated")
        stamped = _functions_calling("simulated_provenance")
        unstamped = gated - stamped
        assert not unstamped, (
            "these functions refuse to run outside simulated mode — so everything they "
            "return is fabricated — but do not stamp `simulated_provenance()` into the "
            f"payload, leaving a consumer no way to tell: {sorted(unstamped)}"
        )

    def test_the_stamp_carries_all_three_fields(self):
        """A consumer checks one field; the other two are what make it actionable."""
        stamp = gs.simulated_provenance()
        assert stamp["simulated"] is True
        assert stamp["data_source"] == "geotab_simulator"
        assert "DOT/ELD" in stamp["warning"], (
            "the warning must name the compliance regime it is not valid for — that is the "
            "sentence that stops the figure being pasted into an audit response"
        )


class TestTheStampReachesTheActualPayload:
    """The sweep above reads the syntax. These read what a caller receives."""

    @pytest.mark.asyncio
    async def test_an_exception_record_is_stamped_individually(self, monkeypatch):
        """Not merely the envelope: one exception is extracted and rendered as a row."""
        monkeypatch.setattr(gs.settings, "GEOTAB_SIMULATED", True)
        monkeypatch.setattr(gs.random, "randint", lambda a, b: max(a, 1))

        records = await gs.geotab_service.get_exceptions(organization_id=None)
        assert records, "the stub should force at least one record"
        for record in records:
            assert record["simulated"] is True
            assert record["data_source"] == "geotab_simulator"

    @pytest.mark.asyncio
    async def test_diagnostics_are_stamped(self, monkeypatch):
        monkeypatch.setattr(gs.settings, "GEOTAB_SIMULATED", True)
        payload = await gs.geotab_service.get_device_diagnostics(
            device_id="DEV-001", organization_id=None
        )
        assert payload["simulated"] is True
        # The reefer block is the reason this one matters: a cold-chain temperature
        # drives a decision about a load.
        assert "diagnostics" in payload

    @pytest.mark.asyncio
    async def test_an_invented_position_is_stamped(self, monkeypatch):
        monkeypatch.setattr(gs.settings, "GEOTAB_SIMULATED", True)
        position = await gs.geotab_service.get_device_location(device_id="DEV-001")
        assert position["simulated"] is True, (
            "with no db and no real fix on record this position is drawn from a bounding "
            "box; unlabelled, a map cannot tell it from a measurement"
        )

    @pytest.mark.asyncio
    async def test_a_real_position_is_NOT_stamped(self, monkeypatch):
        """The other direction, and it is not symmetric decoration.

        `get_device_location` prefers a real trip endpoint. Labelling that as simulated
        would be a falsehood in the opposite direction — and would teach a consumer that
        the flag means nothing.
        """
        from datetime import datetime, timezone
        from types import SimpleNamespace

        monkeypatch.setattr(gs.settings, "GEOTAB_SIMULATED", True)

        trip = SimpleNamespace(
            end_location={"latitude": 51.5, "longitude": -0.1},
            start_location=None,
            end_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
            start_time=None,
        )

        class _Result:
            def scalar_one_or_none(self):
                return trip

        class _Db:
            async def execute(self, *_a, **_k):
                return _Result()

        position = await gs.geotab_service.get_device_location(
            device_id="DEV-001", db=_Db()
        )
        assert position["latitude"] == 51.5
        assert "simulated" not in position, (
            "a fix that came from a recorded trip must not be labelled simulated"
        )


class TestTheGateItselfStillHolds:
    """FS-25's half of the pair. The stamp is useless if the gate stops working."""

    @pytest.mark.asyncio
    async def test_live_mode_refuses_rather_than_fabricating(self, monkeypatch):
        monkeypatch.setattr(gs.settings, "GEOTAB_SIMULATED", False)
        with pytest.raises(gs.GeoTabLiveModeNotConfigured):
            await gs.geotab_service.get_exceptions(organization_id=None)
        with pytest.raises(gs.GeoTabLiveModeNotConfigured):
            await gs.geotab_service.get_device_diagnostics(
                device_id="DEV-001", organization_id=None
            )

    def test_production_config_refuses_simulated_telematics(self):
        """`GEOTAB_SIMULATED` defaults True so the offline demo works, so the whole
        exposure rests on this validator. Asserted here as well as in
        `test_config_validation.py` because that default is what makes it load-bearing."""
        from app.core.config import Settings, validate_settings

        problems = validate_settings(
            Settings(ENVIRONMENT="production", GEOTAB_SIMULATED=True)
        )
        assert any("GEOTAB_SIMULATED" in p for p in problems)
