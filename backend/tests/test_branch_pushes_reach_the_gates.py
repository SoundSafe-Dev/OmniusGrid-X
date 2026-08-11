"""A gate in a workflow that branch pushes never reach is not a gate (FS-657).

THE SHAPE. `ci-cd.yml` has carried a blocking `npx tsc --noEmit` since FS-53 and a blocking
`npm run lint` since FS-54, and it triggers on `push: branches: [main]` plus `pull_request`.
`quality-gates.yml` is the workflow that fires on every developer branch — `hamad/**`,
`hridyansh/**`, `htreinen`, `HARSH-CONTRIBUTION`, `alex` — and it had neither.

So every branch in this repository ran with no typecheck and no lint until somebody opened a
pull request. The consequence was not hypothetical when this was written:

  * a test file committed on 2026-08-11 was green under `vitest run` and **did not compile** —
    `vitest` transpiles and discards types, so a green suite is not a compile;
  * **fifteen lint errors** had accumulated across e2e specs, adapter tests and page tests,
    every one of them enough to fail the gate the moment a PR opened;
  * and the first run of the backend's `flake8 --select=E9,F63,F7,F82` after wiring the
    frontend equivalents found **`F821 undefined name 'driver_id'`** in
    `api/transportation.py` — on the SUCCESS path of a live dispatch route, after the service
    had already committed. See `test_dispatch_reports_the_dispatch_it_made.py`.

This is the same class as two defects already recorded here. The coverage thresholds in
`vitest.config.ts` were enforced by no job in either workflow for weeks — `npm run test` is
`vitest run` without `--coverage` — and they had already gone false. And `develop` sat in this
workflow's branch list for months without existing on any remote, so the dev branches that did
exist ran zero CI. **A gate that is never reached and a gate that does not exist are the same
gate**, and neither announces itself.

WHY THIS TEST IS IN THE BACKEND SUITE. It is a repository-invariant check, not a frontend one,
and it needs to run wherever the rest of the gate-shape guards run — beside
`test_ci_gate_count_is_accurate.py`, which counts the same two files.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
BRANCH_PUSH = WORKFLOWS / "quality-gates.yml"
MAIN_ONLY = WORKFLOWS / "ci-cd.yml"

#: Checks that must run on a branch push, with the command that performs each. Keyed by what
#: the check IS rather than by step name, so renaming a step cannot silently drop one.
#:
#: Matched as a substring of the step's `run:`, which is deliberately loose — `npm run lint`
#: and `npx eslint .` are the same gate, and a guard that insists on one spelling fails the
#: next time somebody changes the script name for a good reason.
REQUIRED_ON_BRANCH_PUSH = {
    "a typecheck": ("tsc --noEmit",),
    "a lint": ("npm run lint", "eslint"),
    "vitest with its coverage thresholds": ("npm run coverage",),
    "flake8 at error level": ("flake8 app", "--select=E9"),
    "the production build": ("vite build",),
}


def _document(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


def _push_branches(document: dict) -> list[str]:
    # PyYAML reads a bare `on:` key as the boolean True, which is why this is not
    # `document["on"]` — a mistake that would make every assertion below vacuous.
    triggers = document.get(True) or document.get("on") or {}
    push = triggers.get("push") or {}
    return list(push.get("branches") or [])


def _run_commands(document: dict) -> list[str]:
    return [
        step["run"]
        for job in (document.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if "run" in step
    ]


class TestTheMeasurementIsReal:
    def test_both_workflows_parse(self):
        for path in (BRANCH_PUSH, MAIN_ONLY):
            assert _document(path).get("jobs"), f"{path.name} produced no jobs"

    def test_the_branch_push_workflow_really_covers_dev_branches(self):
        """Vacuity. If this workflow stopped triggering on branch pushes, every assertion
        below would be about a workflow nobody runs — and the checks would be *correctly*
        present in a file that no longer matters."""
        branches = _push_branches(_document(BRANCH_PUSH))
        assert any(b not in ("main", "master") for b in branches), (
            f"{BRANCH_PUSH.name} no longer triggers on any non-main branch ({branches}). "
            f"Every check it carries is now unreachable from a developer's push."
        )

    def test_the_other_workflow_is_still_main_and_pr_only(self):
        """The premise. If `ci-cd.yml` started running on branch pushes this guard would be
        redundant rather than wrong — but silently redundant, which is its own problem."""
        branches = _push_branches(_document(MAIN_ONLY))
        assert branches in ([], ["main"], ["main", "master"]), (
            f"{MAIN_ONLY.name} now pushes on {branches}. Re-derive which workflow is the "
            f"branch-push gate before trusting the assertions below."
        )


class TestEveryBranchPushCheckIsReachable:
    @pytest.mark.parametrize("what,spellings", sorted(REQUIRED_ON_BRANCH_PUSH.items()))
    def test_it_runs_on_a_branch_push(self, what: str, spellings: tuple[str, ...]):
        commands = " \n".join(_run_commands(_document(BRANCH_PUSH)))
        assert any(s in commands for s in spellings), (
            f"{BRANCH_PUSH.name} does not run {what}, and it is the only workflow that fires "
            f"on a developer branch. A gate that is never reached and a gate that does not "
            f"exist are the same gate: this exact hole let a non-compiling test file and "
            f"fifteen lint errors onto a branch, with every job green."
        )

    def test_a_check_in_the_main_only_workflow_is_not_enough(self):
        """The reasoning, asserted rather than left in a comment.

        `ci-cd.yml` carries all three checks and always has. That was the state of the world
        while branches went unchecked, so 'the repository has a typecheck' was true and
        useless. If somebody removes a check from the branch-push workflow because it is
        'already covered', this is the test that should stop them.
        """
        main_only = " \n".join(_run_commands(_document(MAIN_ONLY)))
        for what, spellings in REQUIRED_ON_BRANCH_PUSH.items():
            if not any(s in main_only for s in spellings):
                continue
            branch = " \n".join(_run_commands(_document(BRANCH_PUSH)))
            assert any(s in branch for s in spellings), (
                f"{what} exists in {MAIN_ONLY.name} and not in {BRANCH_PUSH.name}. That is "
                f"the arrangement this guard exists to refuse."
            )
