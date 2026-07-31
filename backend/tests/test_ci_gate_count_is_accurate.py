"""The README's blocking-gate count must match the workflows.

The README advertised "13 blocking gates" for long enough that the real number had
reached 30. A count in prose has no way to notice that jobs were added, and a stale
number in the most-read file in the repo is worse than no number: it is the figure
someone quotes to a customer.

WHY THIS GUARD PARSES CAREFULLY. The first version of this count reported `api-contract`
and `load-test` as advisory when both had just been made blocking, because it grepped for
`continue-on-error: true` and found the phrase in the COMMENTS explaining that they used
to be advisory. A detector whose input includes prose about its own subject will confirm
whatever the prose says. Comments are stripped before parsing here for exactly that
reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
README = REPO / "README.md"

#: The workflows whose jobs the README's number describes.
COUNTED = ("quality-gates.yml", "ci-cd.yml")


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def _jobs(workflow: Path) -> tuple[list[str], list[str]]:
    """Return (blocking, advisory) job names for one workflow."""
    text = _strip_comments(workflow.read_text())
    names = re.findall(r"^  ([a-z0-9][\w-]*):\s*$", text, re.M)
    blocking: list[str] = []
    advisory: list[str] = []
    for name in names:
        match = re.search(
            rf"^  {re.escape(name)}:\s*$(.*?)(?=^  [a-z0-9][\w-]*:\s*$|\Z)", text, re.M | re.S
        )
        body = match.group(1) if match else ""
        if re.search(r"^\s*continue-on-error:\s*true", body, re.M):
            advisory.append(name)
        else:
            blocking.append(name)
    return blocking, advisory


def _counts() -> tuple[int, int]:
    blocking = advisory = 0
    for name in COUNTED:
        b, a = _jobs(WORKFLOWS / name)
        blocking += len(b)
        advisory += len(a)
    return blocking, advisory


def test_the_workflows_are_readable():
    """A guard that parses nothing passes for the wrong reason."""
    for name in COUNTED:
        assert (WORKFLOWS / name).exists(), f"{name} is gone; this guard checks nothing"
    blocking, advisory = _counts()
    assert blocking > 10, f"only {blocking} jobs parsed; the job-name regex has probably drifted"


def test_readme_blocking_job_count_matches_the_workflows():
    blocking, _ = _counts()
    claimed = re.search(r"\*\*(\d+) blocking jobs", README.read_text())
    assert claimed, (
        "README no longer states a blocking-job count in the expected form "
        '("**N blocking jobs and M advisory**"). Update this guard with it.'
    )
    assert int(claimed.group(1)) == blocking, (
        f"README claims {claimed.group(1)} blocking jobs; the workflows define {blocking}."
    )


def test_readme_advisory_count_matches_the_workflows():
    """The advisory number is the one worth watching.

    Blocking jobs get added; advisory ones accumulate quietly, and each is a gate that
    cannot fail. Two workflows spent weeks with jobs that were killed or ran against
    nothing while reporting green.
    """
    _, advisory = _counts()
    claimed = re.search(r"and (\d+) advisory", README.read_text())
    assert claimed, "README no longer states an advisory count; update this guard with it."
    assert int(claimed.group(1)) == advisory, (
        f"README claims {claimed.group(1)} advisory jobs; the workflows define {advisory}. "
        "If a job was just made advisory, say why in its comment and update the README."
    )


@pytest.mark.parametrize("workflow", COUNTED)
def test_every_advisory_job_carries_a_comment(workflow: str):
    """An advisory job must carry at least one comment.

    WHAT THIS DOES NOT DO, stated plainly because the first version of this docstring
    claimed it: it does not verify the comment EXPLAINS the advisory status. It checks
    only that prose exists on the job. Adding `continue-on-error: true` to a job that
    already had an unrelated comment passes this test — verified, by doing exactly that.

    A weak check honestly described is useful; the same check advertised as semantic
    would be worse than none, because it would be cited as proof of something it never
    established. The real enforcement against silent suppressions is the advisory COUNT
    above, which no comment can satisfy.
    """
    text = (WORKFLOWS / workflow).read_text()
    _, advisory = _jobs(WORKFLOWS / workflow)
    for job in advisory:
        match = re.search(rf"^  {re.escape(job)}:\s*$(.*?)(?=^  [a-z0-9][\w-]*:\s*$|\Z)",
                          text, re.M | re.S)
        body = match.group(1) if match else ""
        comment_lines = [l for l in body.splitlines() if l.strip().startswith("#")]
        assert comment_lines, (
            f"{workflow}: job '{job}' is advisory and carries no comment explaining why. "
            "A suppression with no stated reason is one nobody will revisit."
        )
