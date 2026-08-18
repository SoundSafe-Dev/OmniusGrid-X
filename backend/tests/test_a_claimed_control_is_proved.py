"""A control that claims to operate names a test that exists and runs (FS-746).

THIS IS THE ONE THAT MAKES THE CATALOGUE WORTH READING. Everything else about a compliance
document is prose an author controls. This file is the reason `implemented` means something
here: a control claiming to operate must name tests, those tests must exist, and pytest must
be able to collect them. **Delete a guard and the compliance build fails**, naming the
control that just lost its evidence.

That inverts the usual failure. Ordinarily a control narrative is written once, the code
underneath drifts for two years, and the drift surfaces during an assessment when somebody
asks to see it work. Here the narrative cannot outlive its evidence by more than one CI run.

WHY COLLECTION AND NOT JUST FILE EXISTENCE. A path check passes for a file that exists and
contains nothing, or whose tests were renamed, or that errors on import. Collection is the
cheapest signal that a named test is a test pytest will actually run — which is the property
the word "proved" is claiming. A file that fails to import is worse than a missing one,
because the catalogue looks satisfied.

WHAT THIS CANNOT DO, said plainly so nobody mistakes its scope: it does not check that the
test PASSES (the suite does that), nor that the test is relevant to the control (only a
reader can judge that). It closes the gap between "a control cites evidence" and "that
evidence exists at all", which is the gap the deleted SOC 2 document lived in — 314 claims,
not one citing a file.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from functools import lru_cache

import pytest

from app.core.compliance_catalog import (
    EVIDENCED_STATUSES,
    Control,
    load_controls,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _evidenced() -> list[Control]:
    return [c for c in load_controls() if c.claims_to_work_anywhere()]


@lru_cache(maxsize=1)
def _collected_node_ids() -> frozenset[str]:
    """Every test pytest can collect, as `path` and `path::Class::test` forms.

    Collected once per session — this shells out, and doing it per control would make the
    guard slower than the suite it guards.
    """
    # `-o addopts=` CLEARS THE INI OPTIONS, and without it this guard reports every
    # citation as missing. `pytest.ini` sets `addopts = -v --tb=short`; ini options are
    # prepended, so a trailing `-q` nets back to default verbosity and collection prints
    # the `<Module>`/`<Function>` tree instead of node ids — no line contains `::`, the id
    # set comes back empty, and all seven controls read as having lost their tests.
    #
    # The vacuity check below is what turned that into "collection is broken" rather than
    # a false accusation against the catalogue, which is the whole reason it is there.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "--collect-only", "-q", "tests/"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=600,
    )
    ids: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "::" not in line:
            continue
        ids.add(line)
        # Also index the file and file::Class prefixes, so a control may cite a whole file
        # rather than a single test — citing a file is usually the honest granularity for a
        # control, which is proved by several tests together.
        path = line.split("::", 1)[0]
        ids.add(path)
        parts = line.split("::")
        if len(parts) >= 3:
            ids.add("::".join(parts[:2]))
    return frozenset(ids)


class TestTheMeasurementIsReal:
    def test_collection_succeeded(self):
        """If collection breaks, every citation below is 'not found' and this guard turns
        into noise that gets disabled. Fail on the collector instead."""
        ids = _collected_node_ids()
        assert len(ids) > 1000, (
            f"pytest collected {len(ids)} node ids; this suite has thousands. Collection "
            f"is broken, so citations cannot be checked — fix that before trusting any "
            f"result from this file."
        )

    def test_a_known_test_is_collected(self):
        """A positive control: if the id format ever changes, this fails rather than every
        citation failing at once and looking like a catalogue problem."""
        assert "tests/test_config_validation.py" in _collected_node_ids()

    def test_there_is_something_to_check(self):
        assert _evidenced(), (
            "no control claims to be implemented or partial anywhere, so this file is "
            "asserting nothing"
        )


class TestEveryClaimNamesRealEvidence:
    def test_every_evidenced_control_cites_a_test(self):
        silent = [
            f"{c.id} ({c.source_file})"
            for c in _evidenced()
            if not c.proved_by
        ]
        assert not silent, (
            "these controls claim to operate and cite no test:\n  "
            + "\n  ".join(silent)
            + "\n\nAn uncited control is the shape of the 314 claims deleted in FS-745. "
            "Either name the test that proves it, or lower the status to `absent` with a "
            "remediation date."
        )

    def test_every_cited_test_can_be_collected(self):
        ids = _collected_node_ids()
        missing = []
        for control in _evidenced():
            for citation in control.proved_by:
                if citation not in ids:
                    missing.append(f"{control.id} -> {citation}")
        assert not missing, (
            "these controls cite tests pytest cannot collect:\n  "
            + "\n  ".join(missing)
            + "\n\nThe test was renamed, deleted, or its module fails to import. The "
            "control is now unevidenced while still reading as proved — which is exactly "
            "what this catalogue exists to make impossible."
        )

    def test_every_cited_implementation_file_exists(self):
        missing = []
        for control in _evidenced():
            for path in control.implemented_by:
                if not (REPO / path).exists() and not (BACKEND / path).exists():
                    missing.append(f"{control.id} -> {path}")
        assert not missing, (
            "these controls name implementation files that do not exist:\n  "
            + "\n  ".join(missing)
            + "\n\nA reader following the citation finds nothing, and concludes the "
            "catalogue is decorative."
        )


class TestTheGuardWouldNoticeALostTest:
    """Mutation, in-process. Without this the check above could be comparing two empty sets
    and reporting success — the failure mode every sweep in this repository has a rule
    about."""

    def test_a_deleted_citation_is_detected(self):
        ids = _collected_node_ids()
        invented = "tests/test_a_control_citation_that_was_deleted.py::TestGone::test_gone"
        assert invented not in ids, "the fixture id unexpectedly exists"

        # The same comparison the real check makes, against a control that cites it.
        missing = [c for c in [invented] if c not in ids]
        assert missing == [invented], (
            "the citation check does not notice a test that cannot be collected, so "
            "deleting a guard would leave its control still reading as proved"
        )
