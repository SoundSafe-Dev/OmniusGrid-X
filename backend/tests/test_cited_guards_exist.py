"""A source comment citing a guard that does not exist (FS-686).

This codebase explains itself by cross-reference. Comments say *"asserted by X"*, *"the guard
that keeps this is Y"* — 48 test filenames are named in the source tree alone, and that habit is
most of what makes the reasoning followable a year later.

A citation that names nothing is worse than no citation. The reader follows it, finds nothing,
and must choose between concluding the protection was deleted and assuming they searched
wrongly. Two were live:

  * `fleet_health.py` said *"test_fleet_health_filters_in_sql.py asserts these reads do not
    loop"*. The property is real and held by `test_fleet_health_query_shape.py`.
  * `test_the_geotab_gate_actually_holds.py` said *"test_production_settings_are_validated.py
    refuses GEOTAB_SIMULATED in production"*. That file has never existed; the refusal lives in
    `app/core/config.py::validate_settings`.

Both guards were real and only the trail was broken, which is the failure that costs an
afternoon and teaches a reader to stop trusting the comments.

THE DOCUMENTATION HALF ALREADY EXISTED, and I did not look before building this.
`test_documented_files_exist.py` has checked every backticked path in the documents since
FS-513, complete with a `DELIBERATELY_ABSENT` register for names the prose must mention while
they do not exist. Rule 141, again: the mechanism was there, one directory over, and the
shortest route to this guard was to read it first. The two are complementary rather than
duplicate — that one reads `docs/`, this one reads source comments — and
`test_no_two_guards_keep_the_same_list.py` agrees they keep different lists.

It also caught me. Writing up this defect meant naming the missing files in the delivery log,
and the existing guard failed on that prose immediately, which is rule 37 arriving from a new
direction: a document explaining a stale filename matches a detector for stale filenames
exactly. The three names went into its register with reasons, which is what the register is
for.

SCOPE: SOURCE ONLY, AND THAT IS THE WHOLE DESIGN. A source comment naming a test file is a
claim about the present. A test file or a document may legitimately narrate history — "this
was once checked by X", "the name Y never existed" — and the first draft of this guard flagged
thirteen such lines, including its own docstring explaining the defect, and including the very
sentence in the geotab file that corrects the citation. That is rule 37 in its purest form: the
prose describing a defect matches the detector for the defect. Narrowed rather than papered
over with an exclusion list that would grow with every explanation anyone writes.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Trees whose comments are claims about the present.
SOURCE = ("backend/app", "edge-agent/opsgrid_agent", "frontend/src")

#: Everywhere a cited file might legitimately live.
ANYWHERE = ("backend", "edge-agent", "frontend/src", "docs")

#: A python test file, or a frontend one whose name may carry dotted segments
#: (`geofencing.realmode.test.ts`). The dot must be inside the class: without it the pattern
#: captures only `realmode.test.ts` and reports four existing files as missing.
CITATION = re.compile(r"\b((?:test_[A-Za-z0-9_]+\.py)|(?:[A-Za-z0-9_.]+\.test\.tsx?))\b")


def _walk(roots, suffixes):
    for root in roots:
        base = REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            text = str(path)
            if "node_modules" in text or "/venv/" in text or "/.git/" in text:
                continue
            yield path


def _existing() -> set[str]:
    return {p.name for p in _walk(ANYWHERE, {".py", ".ts", ".tsx", ".md"})}


def _citations():
    existing = _existing()
    for path in _walk(SOURCE, {".py", ".ts", ".tsx"}):
        if ".test." in path.name or path.name.startswith("test_"):
            continue
        for match in CITATION.finditer(path.read_text()):
            name = match.group(1)
            yield str(path.relative_to(REPO)), name, name in existing


class TestTheSweepIsReal:
    def test_it_finds_citations(self):
        found = list(_citations())
        assert len(found) >= 30, (
            f"only {len(found)} source citations found; the pattern has stopped matching "
            f"and the assertion below is about nothing"
        )

    def test_dotted_frontend_names_are_matched_whole(self):
        """The first draft captured only the tail of a dotted name and reported four
        existing files as missing."""
        for name in (
            "geofencing.realmode.test.ts",
            "ERPIntegrations.sync.test.tsx",
            "analysisSessions.truncation.test.ts",
        ):
            match = CITATION.search(f"see `{name}` for the rest")
            assert match and match.group(1) == name

    def test_most_citations_resolve(self):
        """Negative control. If this collapses the guard is calling correct prose broken."""
        assert len([c for c in _citations() if c[2]]) >= 30


def test_every_guard_cited_by_source_exists():
    broken = sorted({f"{where} cites `{name}`" for where, name, exists in _citations() if not exists})
    assert not broken, (
        f"{broken}\n\n"
        f"Each names a test file that does not exist. A reader following the citation finds "
        f"nothing and must choose between concluding the protection was deleted and assuming "
        f"they searched wrongly — and in both cases that prompted this guard, the guard was "
        f"real and only the name was stale."
    )
