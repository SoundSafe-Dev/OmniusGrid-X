"""The compliance catalogue describes the real control set, and only ever grows (FS-746).

WHAT THIS FILE DEFENDS. A control catalogue is read by an assessor as a statement of fact,
and its failure mode is not a crash — it is a sentence that stops being true while still
reading well. Two compliance documents were deleted from this repository in FS-745 for
exactly that: 314 control claims, zero citations, six measurably false. This catalogue is the
replacement, so it has to be held to the standard those failed.

THREE PROPERTIES, and they fail differently:

  * **Structure** — every control parses, has all four deployment profiles, and claims only
    practices that exist. Enforced mostly in `app/core/compliance_catalog.py` so that every
    reader (renderers included) gets a catalogue that already holds, rather than each one
    re-checking and one of them forgetting.
  * **Honesty of the denominator** — 110 practices is the population, and coverage is
    reported against it. A catalogue that quietly measures itself against the practices it
    happens to cover always reads 100%.
  * **Monotonicity** — coverage ratchets. The catalogue is populated family by family, so
    partial coverage is expected and fine; coverage going DOWN is not, and is otherwise
    invisible because a deleted control simply stops appearing.

WHY A RATCHET RATHER THAN A TARGET. The same instrument as `scripts/contract_ratchet.py`,
for the same reason its header gives: a gate that demands perfection on day one gets
disabled, and a gate that demands nothing gets ignored. The floor moves up as families are
populated and may never move down.
"""

from __future__ import annotations

import collections

import pytest

from app.core.compliance_catalog import (
    EVIDENCED_STATUSES,
    PROFILES,
    REMEDIABLE_STATUSES,
    Control,
    coverage,
    load_controls,
    load_crosswalk,
    load_owners,
)

#: Practices claimed by at least one control. RAISE THIS as families are populated; it may
#: never fall. Measured 2026-08-17 with 3.3 (Audit and Accountability) complete.
#:
#: 9 of 110 is not a coverage claim — it is the honest starting point of an incrementally
#: built catalogue, and the number an assessor should see rather than a blank page or an
#: aspirational one.
COVERAGE_FLOOR = 9

#: Controls in the catalogue. Same rule.
CONTROL_FLOOR = 7


def _controls() -> list[Control]:
    return load_controls()


class TestTheMeasurementIsReal:
    """Vacuity first. Every assertion below compares the catalogue to the crosswalk, and
    both of those are files on disk — a loader that finds nothing would pass every one."""

    def test_the_crosswalk_is_the_full_population(self):
        crosswalk = load_crosswalk()
        assert crosswalk.total_practices == 110, (
            f"the crosswalk declares {crosswalk.total_practices} practices; NIST SP 800-171 "
            f"Rev 2 has 110. The denominator is the one number an assessor will check first."
        )
        assert len(crosswalk.practices) == 110

    def test_the_catalogue_is_not_empty(self):
        controls = _controls()
        assert len(controls) >= CONTROL_FLOOR, (
            f"{len(controls)} controls loaded, floor is {CONTROL_FLOOR}. Either controls "
            f"were deleted or the loader stopped seeing the catalogue directory — and a "
            f"loader that reads one file, or none, reports a clean catalogue over nothing."
        )

    def test_more_than_one_family_file_is_read(self):
        """The FS-584 trap: a glob that matches a single file looks like it works."""
        files = {control.source_file for control in _controls()}
        assert files, "no family files were read at all"
        assert "crosswalk.yaml" not in files and "owners.yaml" not in files, (
            "the loader is treating the crosswalk or the owners file as a family file"
        )


class TestTheCatalogueIsWellFormed:
    def test_every_claimed_practice_exists(self):
        crosswalk = load_crosswalk()
        unknown = sorted(
            {
                practice
                for control in _controls()
                for practice in control.practices(crosswalk.framework)
                if practice not in crosswalk.practices
            }
        )
        assert not unknown, (
            f"controls claim practice ids that are not in the crosswalk: {unknown}. Either "
            f"the id is a typo — in which case the control satisfies nothing and the "
            f"catalogue overstates coverage — or the crosswalk is incomplete."
        )

    def test_no_practice_is_claimed_by_two_controls_in_conflict(self):
        """Two controls may both address a practice — the failure is when they disagree
        about whether it works, because the SSP then has two answers to one question."""
        by_practice: dict[str, list[Control]] = collections.defaultdict(list)
        for control in _controls():
            for practice in control.practices():
                by_practice[practice].append(control)

        conflicts = []
        for practice, controls in by_practice.items():
            if len(controls) < 2:
                continue
            for profile in PROFILES:
                verdicts = {c.status[profile] in EVIDENCED_STATUSES for c in controls}
                if len(verdicts) > 1:
                    conflicts.append(
                        f"{practice} on {profile}: "
                        + ", ".join(f"{c.id}={c.status[profile]}" for c in controls)
                    )
        assert not conflicts, (
            "these practices are claimed by controls that disagree about whether they "
            "operate:\n  " + "\n  ".join(conflicts)
        )

    def test_every_owner_resolves(self):
        owners = load_owners()
        unknown = sorted(
            {c.owner for c in _controls() if c.owner not in owners}
        )
        assert not unknown, (
            f"controls name owner(s) {unknown} that owners.yaml does not define. An owner "
            f"is the routing field on a POA&M line; an unroutable one means nobody receives "
            f"the finding."
        )

    def test_every_remediable_control_has_a_dated_plan(self):
        """`partial` and `absent` are the POA&M. A POA&M line with no date is a decision
        nobody has to make again — the thing `test_ci_quarantine_expires.py` exists for."""
        import datetime

        undated = []
        for control in _controls():
            if not control.needs_remediation_anywhere():
                continue
            remediation = control.remediation or {}
            due = remediation.get("due")
            if not due:
                undated.append(f"{control.id} (no remediation.due)")
                continue
            try:
                datetime.date.fromisoformat(str(due))
            except ValueError:
                undated.append(f"{control.id} (unparseable due date {due!r})")
        assert not undated, (
            "these controls are partial or absent somewhere and carry no usable date:\n  "
            + "\n  ".join(undated)
        )

    def test_an_organizational_control_claims_no_test(self):
        """A control code cannot satisfy must not name a test that 'proves' it — that is
        the shape of the claims deleted in FS-745."""
        offenders = [
            c.id
            for c in _controls()
            if any(s == "organizational" for _p, s in c.statuses()) and c.proved_by
        ]
        assert not offenders, (
            f"{offenders} are organizational on some profile and name `proved_by` tests. "
            f"A test cannot prove personnel screening or physical protection; citing one "
            f"claims evidence that does not exist."
        )


class TestCoverageOnlyGrows:
    def test_coverage_has_not_regressed(self):
        claimed = [p for p, ids in coverage().items() if ids]
        assert len(claimed) >= COVERAGE_FLOOR, (
            f"{len(claimed)} of 110 practices are claimed by a control; the floor is "
            f"{COVERAGE_FLOOR}. Coverage fell, which happens silently — a deleted control "
            f"just stops appearing. If this is deliberate, lower the floor in the same "
            f"commit and say why."
        )

    def test_the_floor_is_honest(self):
        """A floor set above the real number would pass forever without measuring anything;
        one set far below it stops being a ratchet. Kept within sight of the truth."""
        claimed = [p for p, ids in coverage().items() if ids]
        assert COVERAGE_FLOOR <= len(claimed) <= COVERAGE_FLOOR + 20, (
            f"coverage is {len(claimed)} and the floor is {COVERAGE_FLOOR}. Raise the floor "
            f"to lock the gain in — an unraised floor is how a ratchet quietly stops "
            f"ratcheting."
        )

    @pytest.mark.parametrize("profile", PROFILES)
    def test_every_control_states_this_profile(self, profile: str):
        missing = [c.id for c in _controls() if profile not in c.status]
        assert not missing, f"{missing} do not state a status for {profile}"
