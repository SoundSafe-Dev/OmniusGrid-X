"""Every `.gitignore` pattern says what it hides and why (FS-740).

WRITTEN BECAUSE THIS FILE WAS AN ATTACK SURFACE. The 2026-08-15 compromise changed exactly
two files. One was `frontend/postcss.config.js`, which got the payload. The other was
`.gitignore`, which got three lines:

    temp_auto_push.bat
    temp_interactive_push.bat
    branch_structure.json

That is the attacker's own tooling, hidden from `git status` so an operator looking at their
working tree would see nothing new. It is the cheapest possible concealment and it needs no
privileges beyond the write access they already had.

Three plausible-looking lines in a file nobody reads is a very good hiding place. This makes
the file readable by requiring what the repository already does by convention: **every
pattern sits in a block with a comment explaining it.** Measured when this was written — 87
patterns, 87 explained, zero exceptions — so the standard costs nothing to keep and an
unexplained addition now stands out at review instead of blending in.

WHAT THIS IS AND IS NOT. It is not malware detection: an attacker who writes a convincing
comment passes. It raises the price of the cheap version — three bare filenames appended to
the end — and, far more often, it catches the honest case where somebody hides a build
artifact and the next person cannot tell whether it matters. The FS-730 build-config guard
covers the payload half of that commit; this covers the concealment half.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
GITIGNORE = REPO / ".gitignore"

#: Patterns allowed to stand without a comment, with the reason each is exempt. Empty, and
#: it should stay that way — the point is that the file reads as prose.
EXEMPT: dict[str, str] = {}


def _blocks() -> list[tuple[list[str], bool, int]]:
    """(patterns, whether the block carries a comment, line number of its first pattern).

    A "block" is a run of non-blank lines. The convention in this file is a comment,
    then the patterns it describes, then a blank line — so the comment governs the block
    it heads, and a pattern appended after a blank line starts a block of its own with no
    explanation, which is exactly the shape the attacker used.
    """
    out: list[tuple[list[str], bool, int]] = []
    patterns: list[str] = []
    explained = False
    first_line = 0
    for number, raw in enumerate(GITIGNORE.read_text().splitlines() + [""], start=1):
        line = raw.strip()
        if not line:
            if patterns:
                out.append((patterns, explained, first_line))
            patterns, explained, first_line = [], False, 0
            continue
        if line.startswith("#"):
            explained = True
            continue
        if not patterns:
            first_line = number
        patterns.append(line)
    return out


class TestTheMeasurementIsReal:
    def test_the_file_is_read(self):
        assert GITIGNORE.exists(), f"{GITIGNORE} does not exist"
        blocks = _blocks()
        total = sum(len(p) for p, _e, _n in blocks)
        assert total > 50, (
            f"only {total} patterns parsed from .gitignore; the block parser has broken "
            f"and every assertion below would pass over almost nothing"
        )

    def test_a_bare_pattern_is_detected(self):
        """The parser must actually distinguish explained from unexplained, or this file
        asserts a tautology. The shape checked is the one the attacker used: patterns
        appended after a blank line, with no comment."""
        blocks = []
        patterns, explained, first = [], False, 0
        for number, raw in enumerate(
            ["# a real block", "build/", "", "temp_auto_push.bat", ""], start=1
        ):
            line = raw.strip()
            if not line:
                if patterns:
                    blocks.append((patterns, explained, first))
                patterns, explained, first = [], False, 0
                continue
            if line.startswith("#"):
                explained = True
                continue
            if not patterns:
                first = number
            patterns.append(line)
        assert [(p, e) for p, e, _n in blocks] == [
            (["build/"], True),
            (["temp_auto_push.bat"], False),
        ], "the parser cannot tell an explained block from a bare one"


class TestNothingIsHiddenWithoutASaying:
    def test_every_pattern_is_explained(self):
        bare = [
            f".gitignore:{number}: {', '.join(patterns)}"
            for patterns, explained, number in _blocks()
            if not explained and not all(p in EXEMPT for p in patterns)
        ]
        assert not bare, (
            "these `.gitignore` patterns hide something and do not say what:\n  "
            + "\n  ".join(bare)
            + "\n\nAdd a comment above the block. This is not bureaucracy: the 2026-08-15 "
            "compromise appended three bare filenames here to keep its own tooling out of "
            "`git status`, and three plausible lines in a file nobody reads is a very good "
            "hiding place. Every other pattern in this file carries its reason."
        )

    @pytest.mark.parametrize("pattern", sorted(EXEMPT))
    def test_every_exemption_states_a_reason(self, pattern: str):
        assert len(EXEMPT[pattern].strip()) > 30, f"{pattern} is exempt with no reason"

    def test_the_attackers_own_entries_are_not_present(self):
        """A direct check for the three lines from the incident. If a restore or a merge
        ever reintroduces them, this says so in the words of the incident rather than as a
        generic style failure."""
        # PATTERNS ONLY, NOT PROSE. The first version searched the whole file and failed
        # immediately — on the comment in `.gitignore` that names those three files while
        # explaining why this guard exists. A detector that cannot tell a rule from a
        # sentence about a rule reports the documentation as the attack.
        patterns = {
            line.strip()
            for line in GITIGNORE.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        found = sorted(
            patterns
            & {"temp_auto_push.bat", "temp_interactive_push.bat", "branch_structure.json"}
        )
        assert not found, (
            f"{found} are back in .gitignore. These are the entries the 2026-08-15 "
            f"force-push added to conceal its own tooling — see "
            f"SECURITY-INCIDENT-2026-08-15.md. Their presence means a compromised tree was "
            f"merged or restored."
        )
