"""Every e2e spec is executed by some CI job (FS-443).

Playwright collects `e2e/*.spec.ts` automatically, so a new spec *appears* to be wired up
the moment it is written. But the live-backend job invokes files **by name**:

    npx playwright test e2e/authenticated.spec.ts e2e/data-reaches-the-screen.spec.ts

and a live-backend spec is `test.skip`-ped without `E2E_LIVE_BACKEND=1`. So a new one that
CI does not name is collected everywhere, skipped on every laptop for want of a backend, and
**executed nowhere** — green in the local run, absent from CI, and indistinguishable from a
passing test in both.

That is the same failure `test_ci_quarantine_expires.py` guards one layer down, and the same
one FS-365 recorded when `compliance-assistant.visual.ts` turned out not to be collected at
all. The difference here is that collection is not the question: execution is.

WHY THIS LIVES IN THE BACKEND SUITE. It needs no browser and no Node, so it runs in the
cheapest job there is, on every push. A guard that only fires where Playwright is installed
would be absent from exactly the runs that matter.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
E2E_DIR = ROOT / "frontend" / "e2e"
WORKFLOWS = ROOT / ".github" / "workflows"

#: A spec that gates itself on a live backend. These are the ones that must be named
#: explicitly, because a bare `npx playwright test` in a job without a backend runs them as
#: skips and reports success.
_LIVE_GATE = "E2E_LIVE_BACKEND"


def _spec_files() -> list[Path]:
    # `auth.setup.ts` is not matched by `*.spec.ts` and needs no entry: Playwright runs it
    # as a project DEPENDENCY, so it fires even when the job names individual files. Noted
    # because the naming is the only thing keeping it out of this sweep, and a future
    # `auth.setup.spec.ts` would be reported as an unrun spec while running every time.
    return sorted(p for p in E2E_DIR.glob("*.spec.ts"))


def _workflow_text() -> str:
    return "\n".join(p.read_text() for p in sorted(WORKFLOWS.glob("*.yml")))


SPECS = _spec_files()
WORKFLOW_TEXT = _workflow_text()


class TestTheSweepIsNotVacuous:
    def test_it_finds_the_specs(self):
        assert len(SPECS) >= 3, (
            f"only {len(SPECS)} e2e specs found at {E2E_DIR}; the glob is wrong and every "
            f"assertion below would pass over nothing"
        )

    def test_it_reads_the_workflows(self):
        assert "playwright" in WORKFLOW_TEXT.lower(), (
            "no workflow mentions playwright; the workflow read is broken"
        )


@pytest.mark.parametrize("spec", _spec_files(), ids=lambda p: p.name)
def test_a_live_backend_spec_is_named_by_a_workflow(spec: Path):
    """A spec that skips without a backend must be invoked somewhere that has one."""
    if _LIVE_GATE not in spec.read_text():
        pytest.skip(f"{spec.name} does not gate on a live backend")

    named = spec.name in WORKFLOW_TEXT or "playwright test\n" in WORKFLOW_TEXT
    assert named, (
        f"{spec.name} gates itself on {_LIVE_GATE} and no workflow names it. It is "
        f"collected by Playwright, skipped everywhere without a backend, and therefore "
        f"executed NOWHERE — a test that exists and never runs. Add it to the live-backend "
        f"job's file list."
    )


def test_a_non_gated_spec_is_covered_by_the_smoke_job():
    """The smoke specs run without a backend, so a bare `npx playwright test` reaches them.
    Asserted so that narrowing that job to named files does not silently drop one."""
    ungated = [s.name for s in SPECS if _LIVE_GATE not in s.read_text()]
    assert ungated, "no ungated spec found; the smoke suite has disappeared"
    assert re.search(r"run:\s*npm run e2e|playwright test\s*$", WORKFLOW_TEXT, re.M), (
        f"no workflow runs the whole e2e suite, so the ungated specs {ungated} may not run "
        f"anywhere. Either restore `npm run e2e` or name them explicitly."
    )


def test_the_setup_project_is_wired_as_a_dependency():
    """The one login the whole suite shares (FS-452).

    `auth.setup.ts` authenticates once and writes the state every spec inherits. It is not a
    `*.spec.ts`, so the sweep above cannot see it — and if the `dependencies: ['setup']`
    wiring were removed, every authenticated spec would fail with a login redirect rather
    than with anything explaining why.

    Asserted here rather than in the frontend suite because this file already owns the
    question "does the e2e configuration actually run what it claims to".
    """
    config = (ROOT / "frontend" / "playwright.config.ts").read_text()
    assert "auth\\.setup\\.ts" in config or "auth.setup.ts" in config, (
        "playwright.config.ts no longer registers the setup project, so nothing writes the "
        "shared authentication state"
    )
    assert "dependencies: ['setup']" in config, (
        "the chromium project no longer depends on 'setup', so the shared state is never "
        "created and every authenticated spec fails on a login redirect"
    )
    assert "storageState: 'e2e/.auth/user.json'" in config, (
        "the chromium project no longer loads the shared state; each spec would have to log "
        "in again, and the suite hit AUTH_LOGIN_RATE_LIMIT twice doing exactly that"
    )
