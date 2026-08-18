"""A collector that cannot reach its device must back off (FS-472).

Every industrial collector runs the same loop: try to read, and on failure drop the
connection and sleep. Five of them slept for `poll_interval` — the same interval they use
when everything is working — so a PLC that was switched off drew a connection attempt every
five seconds, forever. Over a day that is roughly **17,000 identical attempts**, each one
costing the device a socket it has to refuse and the agent a log line nobody will read.

It is not a data defect, which is why it survived: nothing is wrong with the readings, the
suite is green, and the only symptom is a device being dialled at a rate nobody chose.

THE MACHINERY ALREADY EXISTED. `resilience.py` has `ExponentialBackoff` and a three-state
`CircuitBreaker`, both tested, and `modbus`, `opcua` and `mqtt` have used them since they were
written. The other five collectors were written later and did not. **A shared utility is only
shared if the next person knows it is there**, and nothing pointed at it from the files that
needed it.

MEASURED, on a dead device over twelve loop iterations: five connection attempts instead of
twelve, delays of 1, 2, 4, 8, 16 seconds and then the breaker holding at its cooldown. In
steady state an unreachable device is probed once per 300-second cooldown cap rather than
once per poll interval.

WHAT THIS ASSERTS. That every collector with a reconnect loop owns both instruments and
consults them — not that the tuning is right. The values are a first-pass guess in every
collector that has them, and the comment in `modbus_collector.py` saying so is still true.
"""

from __future__ import annotations

import ast
import asyncio
import itertools
from pathlib import Path
from unittest.mock import patch

import pytest

COLLECTORS = Path(__file__).resolve().parent.parent / "opsgrid_agent" / "collectors"

#: Modules with no device connection to lose, so nothing to reconnect to.
_NO_CONNECTION = {
    "__init__.py",
    "base.py",
    # Owns no socket — but it DOES have a retry loop, and the reason needed updating
    # (FS-580). `_run_collector` supervises each collector with a FIXED 5-second delay,
    # bounded at 10 restarts, and FS-501 made a clean return count as a restart.
    #
    # Exempt deliberately, not by oversight. The invariant here is about not hammering a
    # remote endpoint that is down; this loop restarts a LOCAL object, and its cap is what
    # bounds the cost rather than a growing delay. What the cap also does is give up
    # permanently after ~50 seconds — the collector is then dead for the life of the
    # process, which is a supervision-policy question for the edge lane rather than a
    # backoff one, and is recorded here because the previous reason ("owns no socket")
    # stopped describing the file the moment it gained a retry loop.
    "coordinator.py",
    "adapter.py",          # wraps another collector
    "file_watcher.py",     # a directory is either there or it is not
    "screen_scraper.py",   # reads a local framebuffer
    "audio.py",            # a local device or a synthesiser
    "video.py",
    "sparkplug_b.py",      # delegates its transport to the mqtt collector
}


def _reconnecting_modules() -> list[Path]:
    """Collector modules whose poll loop drops and re-establishes a connection."""
    found = []
    for path in sorted(COLLECTORS.glob("*.py")):
        if path.name in _NO_CONNECTION:
            continue
        source = path.read_text()
        if "_disconnect" in source and "while self._running" in source:
            found.append(path)
    return found


class TestTheSweepCanSeeItsSubject:
    def test_it_finds_the_reconnecting_collectors(self):
        modules = _reconnecting_modules()
        assert len(modules) >= 5, (
            f"only {len(modules)} reconnecting collectors found; the scan is broken and "
            f"every assertion below would pass over nothing"
        )

    def test_the_exemptions_still_name_real_files(self):
        stale = sorted(n for n in _NO_CONNECTION if not (COLLECTORS / n).exists())
        assert not stale, f"these exempted modules no longer exist: {stale}"


@pytest.mark.parametrize("path", _reconnecting_modules(), ids=lambda p: p.stem)
class TestEachOneOwnsTheInstruments:
    def test_it_obtains_both(self, path: Path):
        """OWNS a matched pair — not necessarily by constructing them itself (FS-473).

        This asserted `ExponentialBackoff(` and `CircuitBreaker(` appeared in the file,
        which was true when every collector built its own. Factoring the constants into
        `ReconnectPolicy` removed those literals and failed five collectors that had just
        become *more* correct. **A guard written against one implementation of a property
        fails the next implementation of the same property**, so it asks about the
        attributes now.
        """
        source = path.read_text()
        obtains = "ReconnectPolicy" in source or (
            "ExponentialBackoff(" in source and "CircuitBreaker(" in source
        )
        assert obtains, (
            f"{path.name} reconnects and obtains no backoff or breaker. `resilience.py` "
            f"has had both since modbus was written; a device that is switched off is "
            f"otherwise dialled once per poll interval indefinitely."
        )
        for attribute in ("self._backoff", "self._breaker"):
            assert attribute in source, f"{path.name} has no {attribute}"

    def test_it_does_not_hardcode_the_tuning(self, path: Path):
        """The point of the policy (FS-473).

        The four constants were a first-pass guess written in eight files. A guess in one
        place is a guess; a guess in eight is one nobody can revise, because the person
        with the telemetry has to find all eight and the ones they miss keep the old
        behaviour.
        """
        source = path.read_text()
        hardcoded = [
            literal
            for literal in ("failure_threshold=", "cooldown_cap=", "initial_cooldown=", "cap=60")
            if literal in source
        ]
        assert not hardcoded, (
            f"{path.name} sets {hardcoded} inline instead of taking them from "
            f"ReconnectPolicy. That is how the same guess ended up in eight files."
        )

    def test_it_consults_the_breaker_before_attempting(self, path: Path):
        """Owning a breaker and not asking it is the same as not having one."""
        source = path.read_text()
        assert "_breaker.allow()" in source, (
            f"{path.name} constructs a CircuitBreaker and never calls `allow()`, so it "
            f"opens and nothing waits"
        )

    def test_it_records_both_outcomes(self, path: Path):
        source = path.read_text()
        for call in ("record_failure()", "record_success()"):
            assert call in source, (
                f"{path.name} never calls `{call}`. A breaker told only about failures "
                f"never closes; told only about successes it never opens."
            )

    def test_the_failure_path_sleeps_on_the_backoff(self, path: Path):
        """The actual defect: sleeping for `poll_interval` after a failure is what made a
        dead device cost 17,000 attempts a day."""
        source = path.read_text()
        assert "next_delay()" in source, (
            f"{path.name} has a backoff and never advances it, so every retry waits the "
            f"same amount and the curve is decoration"
        )
        assert "_backoff.reset()" in source, (
            f"{path.name} never resets its backoff, so one blip leaves every later outage "
            f"starting from the top of the curve"
        )


class TestTheBehaviourNotJustTheWiring:
    """The wiring checks above are structural. This runs a loop against a dead device."""

    @pytest.mark.asyncio
    async def test_a_dead_device_is_not_dialled_every_interval(self):
        from opsgrid_agent.collectors.profinet import ProfinetCollector

        collector = ProfinetCollector(
            {"asset_id": "plc-1", "ip_address": "10.0.0.9", "poll_interval": 5}
        )
        collector._running = True
        attempts = itertools.count()
        slept: list[float] = []

        async def always_fails():
            next(attempts)
            raise ConnectionError("PLC unreachable")

        async def noop():
            return None

        async def fake_sleep(delay):
            slept.append(delay)
            if len(slept) >= 12:
                collector._running = False

        collector._collect = always_fails
        collector._disconnect = noop
        with patch("asyncio.sleep", fake_sleep):
            await collector._poll_loop()

        made = next(attempts)
        assert made < 12, (
            f"the loop ran 12 iterations and made {made} connection attempts — it is still "
            f"dialling a dead device once per iteration"
        )
        # The delays must GROW rather than repeat, which is what distinguishes a backoff
        # from a constant sleep of a different length.
        growing = [b for a, b in zip(slept, slept[1:]) if b > a]
        assert growing, f"the delays never increase: {slept}"
        assert max(slept) > 5, (
            f"no delay exceeded the 5s poll interval ({slept}), so nothing backed off"
        )


class TestTheUplinkIsAReconnectLoopToo:
    """The ninth one, and the only one that is not a collector (FS-756).

    Everything above scans `opsgrid_agent/collectors/`, which was the right scope when it
    was written — the defect was five collectors dialling dead PLCs. It meant the guard
    could never see `main.py`, where the agent holds the connection that matters most: the
    uplink to the broker.

    And that connection had no reconnect loop at all. `_init_kafka_producer` ran once from
    `start()`, and on failure set the producer to None and returned. `_backfill_worker`
    checks `if self.kafka_producer:` every cycle for the life of the process, so an agent
    that booted while the broker was unreachable buffered forever and drained nothing after
    the link came back. A collector that hammers a dead device is noisy; this one is
    silent, and it is the failure mode DDIL is entirely about.

    **A guard scoped to where a defect was found does not cover where the same defect can
    live.** These assertions read `main.py` for the same properties the collectors are held
    to, so the uplink cannot quietly go back to a bare `sleep()` or to no loop at all.
    """

    MAIN = Path(__file__).resolve().parent.parent / "opsgrid_agent" / "main.py"

    def test_the_file_is_where_this_thinks_it_is(self):
        assert self.MAIN.exists(), f"main.py moved: {self.MAIN}"
        assert "_init_kafka_producer" in self.MAIN.read_text(), (
            "main.py no longer initialises the uplink producer; this class is now "
            "measuring a file that does not do the thing it asserts about"
        )

    def test_the_uplink_has_a_supervising_reconnect_loop(self):
        source = self.MAIN.read_text()
        assert "_uplink_supervisor" in source, (
            "no uplink supervisor. `_init_kafka_producer` called once from start() means a "
            "broker that is down at boot is never retried, and the buffer never drains."
        )
        assert "while self._running" in source

    def test_it_uses_the_shared_policy_rather_than_its_own_numbers(self):
        source = self.MAIN.read_text()
        assert "ReconnectPolicy" in source, (
            "the uplink supervisor does not take its tuning from ReconnectPolicy. That "
            "class exists because the same four constants had been copied into eight "
            "collectors; a ninth copy in main.py is the same defect continuing."
        )
        hardcoded = [
            literal
            for literal in ("failure_threshold=", "cooldown_cap=", "initial_cooldown=")
            if literal in source
        ]
        assert not hardcoded, f"main.py sets {hardcoded} inline instead of via the policy"

    def test_the_supervisor_is_actually_started(self):
        """A loop nobody schedules is a loop that does not run — and would pass every
        source-level assertion above."""
        source = self.MAIN.read_text()
        assert "create_task(self._uplink_supervisor())" in source, (
            "the supervisor is defined and never scheduled"
        )
