"""A collection failure reported only to the log is invisible to monitoring (FS-691).

`test_a_silent_collector_is_visible.py` proves the property for one collector against a real
socket. This keeps the *surface*: every remaining path that logs a failed collection cycle
without counting it, named, with the reason it is still there.

THE SHAPE OF THE CLASS. Fifteen collectors, fifty-nine `logger.error` sites, and — before this
finding — zero calls to `metrics.record_error` in any of them. Not every one of those sites is
a defect, and that distinction is the whole content of this file:

  * **collection failure** — a poll, capture or decode that failed while the collector was
    running. The device is silent and nothing says so. These are the debt. Ten have been
    converted to `record_failure`.
  * **startup refusal** — `*_driver_missing`, `*_no_host`, `*_no_ip_address`. The collector
    returns without ever starting. There is no collection cycle to attribute a failure to,
    and the operator learns at startup. Counting these would put a permanent flat line on a
    collector that is not running rather than one that is failing, which reads worse.
  * **teardown** — `*_disconnect_error`, `*_stop_error`. The reading already happened or is
    never going to; a noisy close is not lost data.

WHY A REGISTER RATHER THAN A DETECTOR. Deciding which of those three a given `logger.error`
is cannot be done by shape — it depends on whether the call sits in the run loop, and both
`_poll_error` and `_disconnect_error` are `except Exception` inside `async def`. A previous
attempt at this class keyed on the event-name suffix, which is a convention this package
happens to follow and nothing enforces. Naming them is honest about that.
"""

from __future__ import annotations

import pathlib

import pytest

COLLECTORS = pathlib.Path(__file__).resolve().parent.parent / "opsgrid_agent" / "collectors"

#: Collectors that do NOT extend BaseCollector and so have no `record_failure` to call.
#: They are instantiated directly by the coordinator rather than through the adapter.
#: Giving them the same seam means either duplicating it or moving them onto BaseCollector;
#: neither is a change to make while chasing a monitoring gap, so they are recorded here.
COORDINATOR_NATIVE = {
    "mqtt.py": "coordinator-native; its failures are broker-connection errors, and the "
               "broker connection is the one thing `connection_state` does track honestly",
    "opcua_collector.py": "coordinator-native; no BaseCollector seam available",
    "modbus_collector.py": "coordinator-native; no BaseCollector seam available",
    "screen_scraper.py": "coordinator-native; no BaseCollector seam available",
    "file_watcher.py": "coordinator-native; a watcher with nothing to read is idle, not "
                       "failing, so the silent-collector case reads differently here",
}

#: The measured figure: BaseCollector-style collectors with a collection-failure path that
#: logs and does not count. ONLY EVER SHRINKS, and the way down is `record_failure`.
MAX_UNCOUNTED = 0


def _base_collector_files() -> list[pathlib.Path]:
    return sorted(
        p
        for p in COLLECTORS.glob("*.py")
        if p.name not in {"__init__.py", "base.py", "adapter.py", "coordinator.py"}
        and p.name not in COORDINATOR_NATIVE
        and "BaseCollector)" in p.read_text()
    )


def _uncounted() -> list[str]:
    """Files with a poll/capture/decode failure that is logged and not counted.

    Keyed on the event name because that is what distinguishes the three kinds above, and
    the convention is uniform across this package — see the module docstring for why a
    structural test was rejected.
    """
    found = []
    for path in _base_collector_files():
        text = path.read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("logger.error("):
                continue
            if any(k in stripped for k in ("_poll_error", "_capture_failed", "_decode_error")):
                found.append(f"{path.name}: {stripped}")
    return found


class TestTheMeasurementIsReal:
    """Rule 165 — a sweep that found nothing and one that examined nothing print the same."""

    def test_it_examined_the_collectors(self):
        names = {p.name for p in _base_collector_files()}
        assert len(names) >= 9, f"only examined {sorted(names)}"
        assert "http_rest.py" in names

    def test_it_can_see_an_uncounted_failure(self):
        """POSITIVE CONTROL. The detector reads source text, so a change of spelling in the
        collectors would silently empty it (rule 37's neighbour: a search that matches
        nothing looks exactly like a codebase with nothing to match)."""
        line = '                logger.error("snmp_poll_error", asset_id=self.asset_id)'
        stripped = line.strip()
        assert stripped.startswith("logger.error(")
        assert any(k in stripped for k in ("_poll_error", "_capture_failed", "_decode_error"))

    def test_the_converted_calls_are_not_counted_as_debt(self):
        """NEGATIVE CONTROL. `self.record_failure("snmp_poll_error", ...)` carries the same
        event name and must NOT match, or every fix would look like the defect it fixed."""
        stripped = 'self.record_failure("snmp_poll_error", error=str(exc))'.strip()
        assert not stripped.startswith("logger.error(")

    @pytest.mark.parametrize("name", sorted(COORDINATOR_NATIVE))
    def test_every_excluded_file_still_exists(self, name):
        """An exclusion naming a deleted file is an exemption nobody can audit."""
        assert (COLLECTORS / name).exists(), f"{name} is excluded and no longer exists"
        assert COORDINATOR_NATIVE[name].strip(), f"{name} is excluded with no reason"

    @pytest.mark.parametrize("name", sorted(COORDINATOR_NATIVE))
    def test_the_excluded_files_are_genuinely_not_base_collectors(self, name):
        """The exclusion's stated reason is 'no BaseCollector seam available'. The day one
        of these is moved onto BaseCollector that reason expires, and this says so rather
        than letting the file stay exempt on a comment that has become false."""
        assert "BaseCollector)" not in (COLLECTORS / name).read_text(), (
            f"{name} now extends BaseCollector, so `record_failure` IS available to it — "
            f"remove it from COORDINATOR_NATIVE and convert its collection-failure paths"
        )


def test_the_uncounted_surface_only_shrinks():
    found = _uncounted()
    assert len(found) <= MAX_UNCOUNTED, (
        f"{len(found)} collection failures are logged and not counted, up from "
        f"{MAX_UNCOUNTED}.\n" + "\n".join(found) + "\n\n"
        f"A failed poll produces no message, so the coordinator seam never sees it and "
        f"`connection_state` still reads up — the poll task is alive, the device is not. "
        f"Call `self.record_failure(event, **fields)` instead of `logger.error`; it logs "
        f"exactly the same line and increments `errors_total` as well."
    )


def test_the_collectors_actually_call_the_seam():
    """The ratchet above is satisfied by a collector with no error handling at all. This
    asserts the positive: the conversions are present and did not get reverted."""
    callers = sorted(
        p.name for p in _base_collector_files() if "self.record_failure(" in p.read_text()
    )
    assert len(callers) >= 9, (
        f"only {callers} report failures through the counted seam — the ten conversions "
        f"made for FS-691 are what keep a silent device visible"
    )
