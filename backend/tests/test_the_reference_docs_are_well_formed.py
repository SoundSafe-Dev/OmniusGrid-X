"""A malformed table row renders as garbage and no guard had an opinion (FS-764).

`OMNIUSGRID_GLOSSARY.md` carried this for weeks, in its security section:

    +(d1031146, 6d8893b3, b7d2e2c6)| **API Key Hash** | SHA256 hash of API key ... |

A `+` and three commit SHAs prepended to a table row — the residue of a conflict resolved by
pasting, arriving in `fa6bb72f` and rendering as a broken row ever since, in the document
people are pointed at to learn the vocabulary.

**Nothing in the suite could have caught it.** `test_docs_links.py` checks that links resolve
and `test_documented_files_exist.py` checks that cited filenames exist; neither has any
opinion about whether a Markdown table is a Markdown table. The repository has a great deal
of documentation-as-contract machinery and none of it asked whether the document is
well-formed.

This is the cheap structural check underneath all of that: the rows are rows, the table of
contents points at headings that exist, and no conflict residue is anywhere in the file. It
would have caught the artifact on the day it landed.

SCOPED TO THE REFERENCE DOCUMENTS, deliberately. The delivery log and the sweeps are prose
with occasional tables and are read linearly; the glossary and the README are looked up, and
a broken row in a lookup document is found by the person who needed that row.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Documents people look things UP in, as opposed to read through.
REFERENCE_DOCS = [
    "OMNIUSGRID_GLOSSARY.md",
    "README.md",
]

#: Residue of a conflict or a bad paste. `<<<<<<<` and friends are the obvious ones; a line
#: beginning with `+(` and a hex run is the shape that actually occurred here — a diff
#: fragment carrying commit SHAs.
CONFLICT_RESIDUE = re.compile(
    r"^(<{7}|>{7}|={7}$|\+\([0-9a-f]{6,}[,)])",
    re.M,
)

TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
SEPARATOR_ROW = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _cells(row: str) -> list[str]:
    """Split a table row on its DELIMITERS, which is not the same as splitting on `|`.

    Two kinds of pipe are content rather than structure, and the first version of this
    guard reported both as ragged rows:

      * escaped — `synced \\| holdover \\| unsynced`, how a glossary writes alternatives
      * inside an inline code span — `` `mode=section|document|table` ``

    A structural check that cannot parse the structure produces false positives, and a
    guard that cries wolf on its first run is one people learn to skip.
    """
    without_code = re.sub(r"`[^`]*`", "`x`", row)
    return re.split(r"(?<!\\)\|", without_code.strip().strip("|"))


def _lines(name: str) -> list[str]:
    path = ROOT / name
    assert path.exists(), f"{name} moved; this guard is measuring nothing"
    return path.read_text().splitlines()


def _outside_code_fences(lines: list[str]):
    """Yield (line_number, text) for lines not inside a ``` fence.

    Mermaid blocks and shell examples contain pipes and angle brackets that are not tables
    and not conflict markers, so scanning them produces noise that trains people to ignore
    this test."""
    fenced = False
    for number, text in enumerate(lines, 1):
        if text.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            yield number, text


class TestTheSweepHasSubjects:
    @pytest.mark.parametrize("name", REFERENCE_DOCS)
    def test_it_finds_tables_to_check(self, name):
        """Vacuity. A parser that matches no rows passes every assertion below over an
        empty set, which is how a structural guard becomes decoration."""
        rows = [t for _, t in _outside_code_fences(_lines(name)) if TABLE_ROW.match(t)]
        assert len(rows) > 50, (
            f"only {len(rows)} table rows found in {name}; the row parser is broken, "
            "not the document"
        )


class TestNoConflictResidue:
    @pytest.mark.parametrize("name", REFERENCE_DOCS)
    def test_no_merge_marker_or_diff_fragment(self, name):
        found = [
            f"{name}:{number}: {text[:90]}"
            for number, text in _outside_code_fences(_lines(name))
            if CONFLICT_RESIDUE.search(text)
        ]
        assert not found, (
            "conflict residue in a reference document:\n  " + "\n  ".join(found)
            + "\n\nThis is what `+(d1031146, 6d8893b3, b7d2e2c6)| **API Key Hash** |` looked "
              "like, and it sat in the glossary for weeks because every documentation guard "
              "here checks meaning and none checked shape."
        )

    def test_the_pattern_would_catch_the_original(self):
        """A positive control. A regex that matches nothing passes every file forever."""
        assert CONFLICT_RESIDUE.search(
            "+(d1031146, 6d8893b3, b7d2e2c6)| **API Key Hash** | SHA256 hash |"
        )
        assert CONFLICT_RESIDUE.search("<<<<<<< HEAD")
        assert CONFLICT_RESIDUE.search(">>>>>>> branch")
        assert not CONFLICT_RESIDUE.search("| **API Key Hash** | SHA256 hash | Backend |")
        assert not CONFLICT_RESIDUE.search("- item (see a1b2c3d)")


class TestTablesAreTables:
    @pytest.mark.parametrize("name", REFERENCE_DOCS)
    def test_every_row_in_a_table_starts_the_row(self, name):
        """A line that contains a table row but does not START with the pipe is the exact
        shape of the defect: Markdown renders it as a paragraph containing pipes."""
        offenders = []
        previous_was_row = False
        for number, text in _outside_code_fences(_lines(name)):
            looks_like_row = "|" in text and text.count("|") >= 2
            if looks_like_row and not TABLE_ROW.match(text) and previous_was_row:
                offenders.append(f"{name}:{number}: {text[:90]}")
            previous_was_row = bool(TABLE_ROW.match(text))
        assert not offenders, (
            "line(s) mid-table that do not begin with `|` and will not render as rows:\n  "
            + "\n  ".join(offenders)
        )

    @pytest.mark.parametrize("name", REFERENCE_DOCS)
    def test_column_counts_are_consistent_within_a_table(self, name):
        """A row with the wrong number of cells silently loses its last column, which for a
        glossary means the term is there and its definition is not."""
        offenders = []
        expected = None
        header_line = 0
        for number, text in _outside_code_fences(_lines(name)):
            if not TABLE_ROW.match(text):
                expected = None
                continue
            if SEPARATOR_ROW.match(text):
                continue
            cells = _cells(text)
            if expected is None:
                expected, header_line = len(cells), number
            elif len(cells) != expected:
                offenders.append(
                    f"{name}:{number}: {len(cells)} cells, table starting line "
                    f"{header_line} has {expected} — {text[:70]}"
                )
        assert not offenders, "ragged table row(s):\n  " + "\n  ".join(offenders)


class TestTheGlossaryIndexResolves:
    def test_every_table_of_contents_entry_points_at_a_real_heading(self):
        """The glossary's contents list is an index, and an index that points at a heading
        somebody renamed is worse than none: the reader concludes the term is undocumented."""
        lines = _lines("OMNIUSGRID_GLOSSARY.md")
        anchors = set()
        for _, text in _outside_code_fences(lines):
            if text.startswith("#"):
                heading = text.lstrip("#").strip()
                slug = re.sub(r"[^\w\s-]", "", heading.lower()).strip().replace(" ", "-")
                anchors.add(slug)

        entries = re.findall(r"^- \[.+?\]\(#([\w-]+)\)", "\n".join(lines), re.M)
        assert len(entries) > 10, f"only {len(entries)} contents entries parsed"
        missing = sorted({e for e in entries if e not in anchors})
        assert not missing, (
            f"contents entries with no matching heading: {missing}\n"
            "A reader following one of these concludes the term is undocumented."
        )
