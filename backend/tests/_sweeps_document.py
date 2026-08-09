"""One reader for the sweeps document, which is now six files (FS-584).

`docs/engineering/defect-class-sweeps.md` reached 7,239 lines and was split: the index kept
the path everything cites, and the sections moved into `sweeps/part-*.md`.

**Two guards read that document, and the split silently disabled both.** They each opened the
index alone, found none of what they check, and reported a consistent document — which is the
worst available failure, because a check that has stopped looking and a document with nothing
wrong produce the same green tick. `test_method_rules_are_indexed.py` found zero `## Rule N`
sections; `test_the_session_arc_is_a_real_range.py` found no FS-range claim and at least had
the decency to fail on its own vacuity check.

So the reader lives here rather than in either file. Two guards holding private copies of how
to read one document is the defect `test_no_two_guards_keep_the_same_list.py` exists to
prevent, and it would have been introduced by the commit that split the document.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The index. Keeps the cited path, carries the class table and the list of parts.
INDEX = ROOT / "docs" / "engineering" / "defect-class-sweeps.md"

#: Where the sections went. Globbed, not enumerated — adding a part is a routine edit and a
#: hand-kept list here is one more thing to forget.
PARTS_DIR = INDEX.parent / "sweeps"


def parts() -> list[Path]:
    return sorted(PARTS_DIR.glob("part-*.md"))


def text() -> str:
    """The whole document as it reads: index first, then every part in order."""
    return "\n".join([INDEX.read_text()] + [part.read_text() for part in parts()])
