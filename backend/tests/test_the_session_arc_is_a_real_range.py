"""The FS range the sweeps document claims is the range that exists (FS-471).

`defect-class-sweeps.md` closes with "FS-431 to FS-471 — forty-one items, no gaps". That is
three claims: a floor, a ceiling, and the absence of holes. All three are checkable, and the
first draft got the count wrong — it said "forty", a number nobody had counted, in a paragraph
whose subject is four wrong figures written in a single week.

WHY IT MATTERS MORE THAN IT LOOKS. An FS number is how this repository cross-references
itself: a comment saying "the same shape as FS-457" is only useful if FS-457 exists and is
findable. A gap in the range means either an item that was planned and dropped, or a reference
to something that was never written — and both read identically to someone following the
trail.

WHAT IT DOES NOT ASSERT. That every item was a good idea, or that the range should not grow.
Only that the sentence describing it is true today.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SWEEPS = ROOT / "docs" / "engineering" / "defect-class-sweeps.md"

#: Where an FS reference can legitimately live: source comments, guard docstrings, and the
#: engineering documents. Deliberately not the delivery log alone — an item recorded only
#: there is an item with no guard.
SEARCH_ROOTS = (
    ROOT / "backend" / "app",
    ROOT / "backend" / "tests",
    ROOT / "edge-agent" / "opsgrid_agent",
    ROOT / "edge-agent" / "tests",
    ROOT / "frontend" / "src",
    ROOT / "docs",
)

CLAIM = re.compile(r"\*\*FS-(\d+) to FS-(\d+) — ([a-z-]+) items, no gaps\*\*")

#: Written out because the claim is written out. The table is extended as the range grows
#: rather than pre-filled: a word missing here FAILS rather than passing unchecked, which is
#: the behaviour that matters — an unverifiable count is how "forty" got written for
#: forty-one in the first place.
_WORDS = {
    "thirty-nine": 39, "forty": 40, "forty-one": 41, "forty-two": 42,
    "forty-three": 43, "forty-four": 44, "forty-five": 45, "forty-six": 46,
    "forty-seven": 47, "forty-eight": 48, "forty-nine": 49, "fifty": 50,
}


def _referenced() -> set[int]:
    found: set[int] = set()
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".md", ".yml"}:
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                found |= {int(n) for n in re.findall(r"FS-(\d{3})", path.read_text())}
            except (UnicodeDecodeError, OSError):  # pragma: no cover
                continue
    return found


def test_the_claim_is_present_and_parseable():
    match = CLAIM.search(SWEEPS.read_text())
    assert match, (
        "the sweeps document no longer states its FS range in the expected form, so the "
        "assertions below would check nothing"
    )


def test_the_range_has_no_gaps():
    match = CLAIM.search(SWEEPS.read_text())
    low, high = int(match.group(1)), int(match.group(2))
    referenced = _referenced()
    missing = [n for n in range(low, high + 1) if n not in referenced]
    assert not missing, (
        f"the document claims FS-{low} to FS-{high} with no gaps, and these are referenced "
        f"nowhere in the tree: {missing}. Either the item was dropped and the range should "
        f"not span it, or it exists only in a commit message — which is not somewhere "
        f"anyone following a cross-reference will look."
    )


def test_the_count_matches_the_range():
    match = CLAIM.search(SWEEPS.read_text())
    low, high, word = int(match.group(1)), int(match.group(2)), match.group(3)
    assert word in _WORDS, (
        f"the count is written as {word!r}, which this test cannot check. Spell it as a "
        f"word in the table above or the figure goes unverified — which is how 'forty' "
        f"got written for forty-one."
    )
    assert _WORDS[word] == high - low + 1, (
        f"the document says {word} ({_WORDS[word]}) items across FS-{low} to FS-{high}, "
        f"which spans {high - low + 1}"
    )


def test_the_sweep_reads_a_plausible_number_of_references():
    """Vacuity. A broken walk returns an empty set, and every gap check above would then
    fail loudly rather than silently — but the count check would still pass, so the read
    is asserted on its own."""
    referenced = _referenced()
    assert len(referenced) > 100, (
        f"only {len(referenced)} FS references found across the tree; the walk is broken"
    )
