"""The other-lane 5xx allowlist has to end (FS-363).

Ten endpoints across two real-DB walks are permitted to return 5xx because they belong to
another lane. Both lists were already asserted BOTH ways — a new 5xx outside the list
fails, an entry that starts passing also fails — so neither could rot silently.

What they could not do is END. `test_ci_quarantine_expires.py` puts the problem exactly:

    a flag in a workflow file has no expiry, no owner and no record of what would have to
    be true to remove it. It is a suppression, and this repository has spent a long time
    learning what suppressions do: they convert a defect into a survivable condition, and
    survivable conditions are never revisited.

That register went from five entries to one, and the reason is instructive: the belief
that the excluded tests encoded unbuilt behaviour dissolved the moment somebody checked.
An expiry is what makes somebody check.

WHY THIS FILE HAS NO DATABASE FIXTURE, which is the whole design. Both walks are gated on
`pytest.importorskip("testcontainers")` and skip wherever Docker is absent — including
every developer machine without it. An expiry that only fires when Docker is available is
an expiry that does not fire. This reads the registry as data and runs everywhere.

WHAT AN EXPIRY MEANS. Not a commitment by the owner; those are not mine to make. It is the
day the repository asks again, with the diagnosis attached so answering is cheap.
Re-dating an entry with a fresh reason is a perfectly good outcome. Letting it sit
unexamined for a year is not.
"""

from __future__ import annotations

import datetime

import pytest

from tests._lane_failures import GET_FAILURES, WRITE_FAILURES

ALL_ENTRIES = [
    (path, entry) for path, entry in GET_FAILURES.items()
] + [
    (f"{method} {path}", entry) for (method, path), entry in WRITE_FAILURES.items()
]

#: A far-future date is an expiry in name only. Nothing here should outrun the horizon a
#: person can hold in mind; the quarantine register uses the same scale.
MAX_HORIZON_DAYS = 120


class TestTheRegistryIsIntact:
    def test_the_registers_still_exist(self):
        """Vacuity guard, rewritten when the registry reached zero (FS-431).

        It asserted `len(ALL_ENTRIES) >= 8` — right while entries existed, because an
        emptied file would have made every assertion below pass over nothing. That number
        cannot survive the entries being fixed, and re-asserting a smaller one is the same
        guard waiting to fail again for the same good reason.

        WHAT REPLACED IT IS NOT THIS TEST. An empty register proves nothing by itself, and
        the two walks that would prove it are real-database tests that SKIP without Docker —
        so "gutted" and "worked down" look identical on a laptop. The evidence lives in
        `test_lane_failure_root_causes_stay_fixed.py`, which asserts the structural facts
        that closed these entries and needs no database to do it.

        This keeps the shape: both names exist and both are dicts, so a walk importing them
        cannot fail into a permissive state.
        """
        assert isinstance(GET_FAILURES, dict)
        assert isinstance(WRITE_FAILURES, dict)

    @pytest.mark.parametrize("key,entry", ALL_ENTRIES, ids=[k for k, _ in ALL_ENTRIES])
    def test_every_entry_names_an_owner_a_reason_and_a_fix(self, key, entry):
        assert entry.owner.strip(), f"{key}: no owner — nobody to route it to"
        assert len(entry.reason.strip()) > 20, (
            f"{key}: the reason is too short to save the owner a reproduction"
        )
        assert len(entry.fix.strip()) > 20, (
            f"{key}: no stated fix. 'What would have to be true to remove this' is the "
            "field that makes the expiry answerable rather than just noisy"
        )


class TestNothingIsSuppressedForever:
    @pytest.mark.parametrize("key,entry", ALL_ENTRIES, ids=[k for k, _ in ALL_ENTRIES])
    def test_the_entry_has_not_expired(self, key, entry):
        today = datetime.date.today()
        assert entry.expiry_date >= today, (
            f"{key} has been allowed to 5xx since before {entry.expires}.\n\n"
            f"  owner:  {entry.owner}\n"
            f"  reason: {entry.reason}\n"
            f"  fix:    {entry.fix}\n\n"
            "Fix it, or re-date the entry with a reason that is true today. Re-dating is a "
            "fine answer; leaving it unexamined is what the date exists to prevent."
        )

    @pytest.mark.parametrize("key,entry", ALL_ENTRIES, ids=[k for k, _ in ALL_ENTRIES])
    def test_the_expiry_is_within_a_horizon_someone_can_hold(self, key, entry):
        """A date far enough away is the same as no date. This is the assertion that stops
        an expiring entry being 'fixed' by pushing it to 2030."""
        horizon = (entry.expiry_date - datetime.date.today()).days
        assert horizon <= MAX_HORIZON_DAYS, (
            f"{key} expires in {horizon} days, beyond the {MAX_HORIZON_DAYS}-day horizon. "
            "An expiry nobody will live to see is not an expiry."
        )


class TestTheRegistryMatchesTheWalks:
    """The registry is now the single source; these assert the walks still read it, so a
    future edit that re-inlines a list somewhere is caught rather than silently doubling
    the number of places an entry can hide."""

    def test_the_get_walk_reads_the_registry(self):
        from tests import test_realdb_endpoint_smoke as walk

        assert set(walk.KNOWN_LANE_FAILURES) == set(GET_FAILURES), (
            "the GET walk's allowlist no longer matches the registry"
        )

    def test_the_write_walk_reads_the_registry(self):
        from tests import test_write_endpoints_reject_cleanly_realdb as walk

        assert set(walk.KNOWN_LANE_FAILURES) == set(WRITE_FAILURES), (
            "the write walk's allowlist no longer matches the registry"
        )

    def test_the_shared_root_cause_is_traceable_while_it_has_entries(self):
        """Four of the ten were one defect: a read endpoint INSERTing a default row on an
        unbound tenant session. Recorded once and referenced, so fixing it did not mean
        finding four separately-worded copies — it was one dependency swap, exactly as the
        shared wording predicted.

        Now conditional (FS-431): with the registry empty there is nothing to trace, and
        asserting `>= 4` unconditionally would require the defect to come back.
        """
        write_on_read = [
            key for key, entry in ALL_ENTRIES
            if "GUC is not bound" in entry.reason
        ]
        if not write_on_read:
            return
        assert len(write_on_read) >= 4, (
            "the shared write-on-read root cause is no longer traceable across its "
            f"entries (found {len(write_on_read)}); it is one fix, not four"
        )
