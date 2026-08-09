"""Every branch that exists must be covered by the push gates (FS-389).

`quality-gates.yml` triggers pushes on an ALLOWLIST OF BRANCH NAMES:

    branches: [main, 'hamad/**', 'hridyansh/**', 'feature/**', htreinen, HARSH-CONTRIBUTION]

That list has been wrong twice in different directions. Its own comment records the first:
`develop` was listed for a long time and has never existed, so it gated nothing. The second
is the mirror and was live until today — **`alex` on origin matched no pattern at all**, so
that branch ran zero push CI. Its pull request was the only gate it ever met, and the four
ERP sandbox jobs were skipped on pull_request (FS-374), so vendor-facing coverage there was
nil.

WHY IT KEEPS HAPPENING. An allowlist of personal branch names goes stale the moment someone
creates a branch, and it fails **silently**: no job reports "this branch has no gates". The
only signal is an absence, which is the hardest thing to notice. Nobody reads a workflow
file to check whether their own branch is in it.

WHAT THIS DOES. Resolves the branches that actually exist on the remotes and asserts each
one matches a configured pattern. It is the only check here that needs the network, so it
degrades honestly: when `git ls-remote` cannot run the coverage assertion skips, but the
pattern-matching logic is verified unconditionally below — a skip must never mean the
matcher went untested, because then a later failure would be unreadable.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "quality-gates.yml"

#: Branches that legitimately have no push gates, with the reason.
EXEMPT = {
    # Long-lived integration branches belonging to other lanes are covered when they
    # merge; entries here are a deliberate choice, not an oversight.
    #
    # A PRESERVATION BRANCH, not a development one (2026-08-08). `rag-rewrite` is
    # htreinen's work as it existed on his laptop — three commits that were on NO remote
    # at all until they were pushed here, and a disjoint history with no merge base to
    # converged. Its three commits are cherry-picked onto the trunk and gated there; the
    # branch is the RECORD of where they came from, and gating a frozen record buys
    # nothing. It should be deleted once he confirms nothing else on it is wanted, and
    # this entry should go with it.
    "rag-rewrite",
}


def _patterns() -> list[str]:
    # `on` is parsed by PyYAML 1.1 rules as the boolean True, which is why this looks
    # for both — a plain `config["on"]` silently returns nothing and the test passes.
    config = yaml.safe_load(WORKFLOW.read_text())
    triggers = config.get("on", config.get(True))
    assert triggers, "could not read the `on:` block; PyYAML may have parsed `on` as True"
    return list(triggers["push"]["branches"])


def _matches(branch: str, pattern: str) -> bool:
    """GitHub branch-filter semantics: `*` stops at `/`, `**` crosses it."""
    regex = ""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern[index : index + 2] == "**":
                regex += ".*"
                index += 2
                continue
            regex += "[^/]*"
        else:
            regex += re.escape(char)
        index += 1
    return re.fullmatch(regex, branch) is not None


def _remote_branches() -> list[str] | None:
    names: set[str] = set()
    for remote in ("origin", "backup"):
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--heads", remote],
                cwd=REPO, capture_output=True, text=True, timeout=45,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            if "refs/heads/" in line:
                names.add(line.split("refs/heads/", 1)[1].strip())
    return sorted(names) or None


class TestTheMatcherIsCorrect:
    """Verified unconditionally, so a skipped coverage test never means the logic here
    is also unverified."""

    def test_double_star_crosses_a_slash(self):
        assert _matches("hamad/converged-pre-main", "hamad/**")
        assert _matches("hridyansh/edge-agent-retry-logic", "hridyansh/**")
        assert _matches("feature/RAG-Compliance-Doc-Pipeline", "feature/**")

    def test_single_star_does_not_cross_a_slash(self):
        assert not _matches("hamad/a/b", "hamad/*")
        assert _matches("hamad/a", "hamad/*")

    def test_a_bare_name_matches_exactly(self):
        assert _matches("htreinen", "htreinen")
        assert not _matches("htreinen-2", "htreinen")
        assert not _matches("alex", "htreinen")

    def test_it_would_have_caught_the_defect(self):
        """`alex` against the pattern set as it stood before FS-389."""
        before = ["main", "hamad/**", "hridyansh/**", "feature/**", "htreinen",
                  "HARSH-CONTRIBUTION"]
        assert not any(_matches("alex", p) for p in before), (
            "the matcher no longer reproduces the original gap, so the coverage "
            "assertion below is proving nothing"
        )


class TestTheWorkflowIsReadable:
    def test_patterns_are_present(self):
        patterns = _patterns()
        assert len(patterns) >= 5, f"only {len(patterns)} push branch patterns parsed"
        assert "main" in patterns


class TestEveryRemoteBranchIsGated:
    def test_no_branch_runs_zero_push_ci(self):
        branches = _remote_branches()
        if branches is None:
            pytest.skip("no network access to the remotes; the matcher is tested above")

        patterns = _patterns()
        uncovered = [
            b for b in branches
            if b not in EXEMPT and not any(_matches(b, p) for p in patterns)
        ]
        assert not uncovered, (
            "these branches exist on a remote and match NO push trigger, so they run "
            "zero CI. Nothing reports this — the signal is an absence. Add the branch (or "
            "a pattern covering it) to `on.push.branches` in quality-gates.yml, or record "
            "it in EXEMPT with a reason:\n  " + "\n  ".join(uncovered)
        )

    def test_the_check_saw_some_branches(self):
        """Vacuity guard: an ls-remote that returns nothing but exits 0 would make the
        assertion above pass over an empty list."""
        branches = _remote_branches()
        if branches is None:
            pytest.skip("no network access to the remotes")
        assert len(branches) >= 5, (
            f"only {len(branches)} remote branches resolved; the coverage check above is "
            "passing over almost nothing"
        )
