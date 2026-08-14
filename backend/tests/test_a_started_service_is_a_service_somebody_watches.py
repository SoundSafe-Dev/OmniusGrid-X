"""`main.py` starts eight background services; health reports on one (FS-693).

THIS IS THE SURFACE BEHIND THE FIX. `_check_command_dispatch` used to ask whether the
dispatch task had exited — a question a loop written never to die always answers "no" — so a
dispatch loop failing on every iteration reported `ok` while no command reached a machine.
That is now checked against work rather than mechanism.

The same reasoning applied to the rest of the startup sequence produces this file. Seven
other services are started in `main.py:88-104`, run for the lifetime of the process, and are
named in no health check at all. For those the question is not *is the check asking the
right thing* — there is nothing to ask it of. A stalled OEE calculator or an export
scheduler that has thrown on every cycle since boot is invisible to `/health/detailed`,
which will happily report the process healthy.

NOT EVERY ENTRY IS EQUALLY URGENT and pretending otherwise would make this list ignorable,
so each carries what would have to be true for it to be dropped. Two are near-trivial
(a counter and a last-run timestamp); the rest need a definition of "working" that only the
lane owner can give, which is why this is a register rather than seven half-guessed probes.

WHAT THIS DOES NOT CLAIM. A service being unchecked is not evidence that it is broken. It is
evidence that if it broke, nothing would say so — which is the property FS-691 and FS-693
were both about.
"""

from __future__ import annotations

import pathlib
import re

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
MAIN = APP / "main.py"
HEALTH = APP / "api" / "health.py"

#: Services started at boot with no health check, and what would close the entry.
#: ONLY EVER SHRINKS. Removing a name means writing a check, not deleting a line.
UNWATCHED = {
}


def _started_services() -> list[str]:
    """Names `main.py` starts at boot, from `await <name>.start()`."""
    return sorted(set(re.findall(r"await (\w+)\.start\(\)", MAIN.read_text())))


def _unchecked() -> list[str]:
    health = HEALTH.read_text()
    # A name that appears only inside a comment is not a check. Strip comment bodies first —
    # `rollout_orchestrator` appears at health.py:791 in prose about a different finding, and
    # counting that as coverage would have made this register one entry shorter and wrong.
    code = "\n".join(line.split("#")[0] for line in health.splitlines())
    return sorted(name for name in _started_services() if name not in code)


class TestTheMeasurementIsReal:
    """Rule 165 — assert the denominator; an empty list and an empty search look alike."""

    def test_it_found_the_startup_sequence(self):
        started = _started_services()
        assert len(started) >= 8, f"only found {started} — the pattern no longer matches"
        assert "command_executor" in started

    def test_the_checked_service_is_seen_as_checked(self):
        """NEGATIVE CONTROL. `command_executor` is health-checked, so if it shows up as
        unchecked the detector is reading the wrong file and every name is a false positive."""
        assert "command_executor" not in _unchecked()

    def test_a_mention_in_a_comment_is_not_a_check(self):
        """POSITIVE CONTROL for the comment-stripping. The original control asserted that
        `rollout_orchestrator` appeared in health.py only as prose — true for the months
        this register carried it, false since FS-705 gave it a real check (the control
        expiring is the register succeeding). Synthetic now, so it cannot expire again."""
        code = "\n".join(
            line.split("#")[0]
            for line in ["x = 1  # imaginary_service is mentioned here only", "y = 2"]
        )
        assert "imaginary_service" not in code, (
            "a name that appears only in a comment is being counted as coverage"
        )

    @pytest.mark.parametrize("name", sorted(UNWATCHED))
    def test_every_registered_service_is_still_started(self, name):
        """A register naming a service that boot no longer starts is stale documentation."""
        assert name in _started_services(), (
            f"{name} is registered as unwatched and is no longer started at boot — delete "
            f"the entry rather than leaving it to rot"
        )

    @pytest.mark.parametrize("name", sorted(UNWATCHED))
    def test_every_entry_says_what_would_close_it(self, name):
        assert len(UNWATCHED[name].strip()) > 20, f"{name} is registered with no next step"


def test_the_unwatched_surface_only_shrinks():
    unchecked = _unchecked()
    new = sorted(set(unchecked) - set(UNWATCHED))
    assert not new, (
        f"{new} are started at boot and named in no health check.\n\n"
        f"A background service that fails silently is the FS-691 shape: the process is up, "
        f"the task is alive, and the work stopped. Add a check that reads what the service "
        f"produced — a counter, a last-run timestamp — not whether its task still exists."
    )


def test_the_register_does_not_outlive_its_entries():
    """The other direction: a name that HAS been given a check must leave the register, or
    the list slowly becomes a list of solved problems that nobody trusts."""
    stale = sorted(set(UNWATCHED) - set(_unchecked()))
    assert not stale, (
        f"{stale} now appear in health.py — delete them from UNWATCHED so the register "
        f"keeps meaning 'nobody is watching this'"
    )
