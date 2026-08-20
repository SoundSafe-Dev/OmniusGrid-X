"""A skipped gate and a passing gate are the same green tick (FS-808).

Eleven test modules open with a guarded import of `testcontainers`, because they need a
Docker daemon and a developer without one should not be blocked. In CI that reasoning
inverts: `pytest` exits 0 whether a suite ran or skipped itself, so a workflow that stops
providing the dependency reports success for work that never happened.

THE ONE THAT MATTERS MOST is `test_backup_restore_drill.py`. Its docstring says, of the
nightly backup, "this drill is what stops it from becoming the same kind of fiction: a
backup nobody restores is not a backup". A drill that silently skips is that fiction one
level up — the gate is green and nobody has restored anything. The claim the drill backs is
a customer-facing RPO, which FS-799 has just finished correcting by a factor of a hundred.

WHAT WAS ALREADY THERE, and why it was not enough. `backend-realdb` runs a preflight
`import testcontainers.postgres` step that fails the job if the dependency is missing. That
covers the case it was written for. It does not cover the preflight itself being renamed,
reordered or dropped in a workflow edit — after which all eleven suites skip and the job
stays green, which is precisely the failure the preflight exists to prevent, one level of
indirection out. A guarantee that lives beside the tests rather than in them is only as
durable as the file it lives in.

So `REQUIRE_REALDB=1` makes the skip a hard error, and this file asserts CI still sets it.
Removing it from the workflow is now itself a test failure, which is the property the
preflight lacked.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from tests._realdb import REQUIRE_ENV

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
TESTS = pathlib.Path(__file__).resolve().parent
WORKFLOW = REPO / ".github" / "workflows" / "quality-gates.yml"
JOB = "backend-realdb"
STEP = "Real-DB guard suite"

#: Suites permitted to keep a bare `importorskip` on testcontainers, with why. Empty, and
#: meant to stay that way — an entry is a statement that this suite may vanish in CI.
MAY_STILL_SKIP: dict[str, str] = {}


def _guarded_suites() -> list[str]:
    return sorted(
        p.name for p in TESTS.glob("*.py")
        if "require_testcontainers()" in p.read_text() and p.name != "_realdb.py"
    )


def _bare_importorskips() -> list[str]:
    found = []
    for p in TESTS.glob("*.py"):
        if p.name in {"_realdb.py"} | set(MAY_STILL_SKIP):
            continue
        if re.search(r'importorskip\(\s*["\']testcontainers', p.read_text()):
            found.append(p.name)
    return sorted(found)


def _step() -> dict:
    document = yaml.safe_load(WORKFLOW.read_text())
    job = document["jobs"][JOB]
    for step in job["steps"]:
        if step.get("name") == STEP:
            return step
    raise AssertionError(f"{JOB} has no step named {STEP!r}")


class TestTheMeasurementIsReal:
    def test_it_found_the_guarded_suites(self):
        suites = _guarded_suites()
        assert len(suites) >= 10, f"only {len(suites)} suites use the guard: {suites}"
        assert "test_backup_restore_drill.py" in suites, (
            "the restore drill is the reason this file exists"
        )

    def test_the_workflow_parses(self):
        step = _step()
        assert "pytest" in str(step.get("run", "")), step


def test_no_realdb_suite_keeps_a_bare_importorskip():
    bare = _bare_importorskips()
    assert not bare, (
        f"these suites still call `pytest.importorskip(\"testcontainers\")` directly: "
        f"{bare}.\n\nThat skips silently in CI, where a skip and a pass produce the same "
        f"exit code. Use `require_testcontainers()` from tests/_realdb.py, which skips on "
        f"a laptop and FAILS when REQUIRE_REALDB=1."
    )


def test_ci_forbids_the_realdb_suites_from_skipping():
    step = _step()
    env = step.get("env") or {}
    assert str(env.get(REQUIRE_ENV, "")).strip().lower() in {"1", "true", "yes"}, (
        f"the {STEP!r} step does not set {REQUIRE_ENV}=1 (env is {env!r}).\n\n"
        f"Without it, every real-DB suite — including the backup restore drill — skips "
        f"silently if testcontainers is unavailable, and the job reports success for work "
        f"that never ran. The drill's own docstring calls that 'the same kind of fiction' "
        f"it exists to prevent."
    )


def test_the_drill_is_still_in_the_job():
    """A suite removed from the job's file list is as absent as one that skipped, and
    leaves no trace at all — no `s` in the output, no skip reason, nothing."""
    run = str(_step().get("run", ""))
    assert "tests/test_backup_restore_drill.py" in run, (
        "the restore drill is no longer listed in the backend-realdb job. It is the only "
        "thing standing between the nightly backup and an untested claim."
    )


@pytest.mark.parametrize("suite", _guarded_suites())
def test_every_guarded_suite_imports_the_helper(suite: str):
    source = (TESTS / suite).read_text()
    assert "from tests._realdb import require_testcontainers" in source, (
        f"{suite} calls require_testcontainers() without importing it — the module will "
        f"raise NameError at collection, which fails loudly, but says nothing useful."
    )
