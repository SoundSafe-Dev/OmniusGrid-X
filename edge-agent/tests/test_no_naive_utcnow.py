"""Guard (FS-96, edge half): no naive datetime construction in the agent.

The naive-vs-aware class is nastier on the edge than in the backend: both instances found
originally were swallowed by defensive except-blocks and became SILENT data loss (backfill
lag reported as 0; collector readings dropped before forward). Aware
``datetime.now(timezone.utc)`` everywhere, with naive-input coercion at ISO-parse
boundaries.

**THIS GUARD CHECKED ONE SPELLING OF THE DEFECT AND THE DEFECT WAS IN THE OTHER** (FS-461).
It matched only ``datetime.utcnow(``, and found nothing for months while fourteen bare
``datetime.now()`` calls — equally naive — sat in the same tree. Five of them were
``timestamp_edge`` on collectors that emit to the cloud, and ``telemetry.time`` is
``timestamptz``: a naive stamp is stored as though it were UTC, so every reading from a
device outside UTC was wrong by exactly that device's offset. Silently, and forever.

The others were internal cutoffs and, in `local_oee.py`, elapsed-time arithmetic against
local wall-clock time — which is not monotonic. On a DST fall-back it steps backwards an
hour, so "time in Execute" goes negative and silently subtracts from operating time. Once a
year, on a number nobody would think to question.

The lesson is the rule: **a guard that greps for one form of a defect reports clean on
every other form,** and reports it in the confident voice of a check that ran. Both
spellings are matched now, and the sweep asserts it can still see its subject.
"""

import re
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1] / "opsgrid_agent"

#: Both ways to build a naive datetime. `utcnow()` is naive by definition; `now()` with no
#: argument returns naive LOCAL time, which is the more dangerous of the two because it
#: looks correct and is wrong by the host's UTC offset.
_NAIVE_CALL = re.compile(r"datetime\.utcnow\s*\(|datetime\.now\s*\(\s*\)")


def _code_lines(path):
    """Source lines with comments and string literals blanked out.

    Needed because the FS-461 fix left comments and docstrings QUOTING the old call to
    explain it — and a guard that fires on its own explanation is a guard someone deletes,
    or worse, works around by removing the explanation.

    Done with `tokenize` rather than by stripping `#` prefixes: the first attempt handled
    comments and not docstrings, and failed on the very docstring describing the defect.
    """
    import io
    import tokenize as _tok

    source = path.read_text()
    blanked = source.splitlines()
    try:
        tokens = list(_tok.generate_tokens(io.StringIO(source).readline))
    except (_tok.TokenError, IndentationError, SyntaxError):  # pragma: no cover
        # An unparseable module is a different failure; scan it raw rather than skip it,
        # because skipping is how a file stops being checked without anyone noticing.
        return list(enumerate(blanked, 1))

    drop = {_tok.COMMENT, _tok.STRING}
    for token in tokens:
        if token.type not in drop:
            continue
        (r1, c1), (r2, c2) = token.start, token.end
        for row in range(r1, r2 + 1):
            line = blanked[row - 1]
            start = c1 if row == r1 else 0
            end = c2 if row == r2 else len(line)
            blanked[row - 1] = line[:start] + " " * (end - start) + line[end:]
    return list(enumerate(blanked, 1))


def _agent_files():
    return [p for p in sorted(AGENT_ROOT.rglob("*.py")) if "__pycache__" not in p.parts]


def test_the_sweep_can_see_its_subject():
    """Vacuity. A glob that matches nothing passes the assertion below over an empty set,
    which is how this guard would report clean on a tree it never read."""
    files = _agent_files()
    assert len(files) > 25, f"only {len(files)} agent modules found; the glob is wrong"
    assert any("datetime" in p.read_text() for p in files), (
        "no agent module mentions datetime at all; the read is broken"
    )


def test_the_pattern_matches_both_spellings():
    """The regex itself, asserted. Widening it was the whole fix for FS-461, and a
    narrowed-back pattern would restore months of confident silence."""
    assert _NAIVE_CALL.search("x = datetime.utcnow()")
    assert _NAIVE_CALL.search("x = datetime.now()")
    assert _NAIVE_CALL.search("x = datetime.now( )")
    # And must NOT match the aware form, or every correct call becomes an offender.
    assert not _NAIVE_CALL.search("x = datetime.now(timezone.utc)")
    assert not _NAIVE_CALL.search("x = datetime.now(tz)")


def test_no_naive_datetime_calls_in_agent():
    offenders = []
    for path in _agent_files():
        for lineno, line in _code_lines(path):
            if _NAIVE_CALL.search(line):
                offenders.append(f"{path.relative_to(AGENT_ROOT.parent)}:{lineno}")
    assert not offenders, (
        "naive datetime construction found — use datetime.now(timezone.utc):\n  "
        + "\n  ".join(offenders)
        + "\n\n`datetime.now()` with no argument is LOCAL naive. It is the more dangerous "
        "spelling because it looks right: stored into a timestamptz column it is read as "
        "UTC, so the reading is wrong by the host's offset."
    )
