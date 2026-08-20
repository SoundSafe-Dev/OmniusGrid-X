r"""The README's blocking-gate count must match the workflows.

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

AND IT HAPPENED A THIRD TIME (FS-797). Job names were collected with

    re.findall(r"^  ([a-z0-9][\w-]*):\s*$", text, re.M)

— every two-space-indented key, which in a GitHub workflow includes the TRIGGERS under
`on:`. `pull_request:` and `push:` were counted as jobs in both workflows, so the total
ran four high: the README said **31 blocking** where 27 are defined, and the guard
enforced that number against the parser that invented it. Precisely the failure this
docstring already warned about, in a third disguise.

The lesson took: this now parses the workflow as YAML and reads `jobs` by key. The
structure is the authority on what a job is, and a regex over indentation is a guess
about it. The vacuity test below cross-checks the two so a future regex cannot creep
back in unnoticed.
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
    """Return (blocking, advisory) job names for one workflow.

    Job names come from the parsed `jobs` mapping. Advisory status is still read from
    the comment-stripped TEXT rather than the parsed body, because `continue-on-error`
    must be distinguished by INDENTATION — four spaces is the job itself, six or more is
    a single step — and that distinction is flattened by the time PyYAML has built the
    step list.
    """
    import yaml

    text = _strip_comments(workflow.read_text())
    document = yaml.safe_load(workflow.read_text()) or {}
    names = list((document.get("jobs") or {}).keys())
    blocking: list[str] = []
    advisory: list[str] = []
    for name in names:
        match = re.search(
            rf"^  {re.escape(name)}:\s*$(.*?)(?=^  [a-z0-9][\w-]*:\s*$|\Z)", text, re.M | re.S
        )
        body = match.group(1) if match else ""
        # EXACTLY FOUR SPACES — job level, not step level.
        #
        # `^\s*continue-on-error` matched at ANY depth, so a single fail-safe STEP marked
        # its whole job advisory. A job is not advisory because one step of it may fail;
        # every other step still fails the build. Two of the three occurrences in these
        # workflows are step-level (`quality-gates.yml` starting a broker best-effort,
        # `ci-cd.yml`), and both were being miscounted.
        #
        # THE README INHERITED THE ERROR. Its "30 blocking and 2 advisory" was read off
        # this parser, so the guard was enforcing a number its own bug produced — the
        # second instance of the confounded-detector problem this file's header describes,
        # this time with the wrong number written down in between.
        if re.search(r"^    continue-on-error:\s*true", body, re.M):
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


def test_a_fail_safe_step_does_not_make_its_job_advisory():
    """The distinction the parser above exists to make, pinned directly.

    Both shapes are legitimate and they mean opposite things: a job-level
    `continue-on-error` is a gate that cannot fail the build, a step-level one is a single
    optional step inside a gate that still can. Counting them together made the advisory
    number — the one this file says is "the one worth watching" — unwatchable.
    """
    job_level = """
  a-real-gate:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - run: echo hi
  another-gate:
    runs-on: ubuntu-latest
    steps:
      - name: best effort
        continue-on-error: true
        run: echo hi
      - run: echo this one still fails the build
"""
    names = re.findall(r"^  ([a-z0-9][\w-]*):\s*$", job_level, re.M)
    assert names == ["a-real-gate", "another-gate"]

    advisory = []
    for name in names:
        match = re.search(
            rf"^  {re.escape(name)}:\s*$(.*?)(?=^  [a-z0-9][\w-]*:\s*$|\Z)",
            job_level, re.M | re.S,
        )
        if re.search(r"^    continue-on-error:\s*true", match.group(1), re.M):
            advisory.append(name)
    assert advisory == ["a-real-gate"], (
        "a step-level continue-on-error is being counted as an advisory JOB; the advisory "
        "total then rises every time someone adds a legitimately optional step"
    )


def test_the_workflows_are_readable():
    """A guard that parses nothing passes for the wrong reason."""
    for name in COUNTED:
        assert (WORKFLOWS / name).exists(), f"{name} is gone; this guard checks nothing"
    blocking, advisory = _counts()
    assert blocking > 10, f"only {blocking} jobs parsed; the job-name regex has probably drifted"


def test_no_trigger_is_counted_as_a_job():
    """FS-797, pinned. The predecessor collected every two-space key, so the `on:`
    triggers `pull_request:` and `push:` were counted as jobs — four phantom gates
    across the two workflows, and the README was updated to match them."""
    import yaml

    for name in COUNTED:
        document = yaml.safe_load((WORKFLOWS / name).read_text()) or {}
        real = set((document.get("jobs") or {}).keys())
        counted = set(_jobs(WORKFLOWS / name)[0]) | set(_jobs(WORKFLOWS / name)[1])
        assert counted == real, (
            f"{name}: counted {sorted(counted - real)} that are not jobs, and missed "
            f"{sorted(real - counted)}. The count must come from the parsed `jobs` "
            f"mapping, not from indentation."
        )
        triggers = document.get(True) or document.get("on") or {}
        if isinstance(triggers, dict):
            assert not (set(triggers) & counted), (
                f"{name}: a workflow trigger is being counted as a job again."
            )


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
