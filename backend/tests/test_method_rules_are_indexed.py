"""The method-rules list and the rule sections must agree.

`docs/engineering/defect-class-sweeps.md` records rules two ways: a numbered list under
*"Writing a sweep that is worth trusting"*, and — from rule 22 onward — a fuller `## Rule N`
section for each. The list is what anyone reads; the sections are where the reasoning lives.

**They have drifted apart three times.** Rules 22–27 were written as sections and the list
stopped at 21 until somebody noticed; then 28–31; then 33–43. Each time the fix was to fold
them in by hand, and each time the list silently stopped being the index it claims to be. Three
identical repairs is the signal from rule 39: a comment records a fix, only a guard prevents the
next one.

WHY THIS IS A BACKEND TEST. The repository already keeps documentation honest from the test
suite — `test_documented_endpoints_exist.py` checks every endpoint the README claims, and
`test_documented_files_exist.py` checks every filename three docs cite. A rules index is the
same kind of claim.

SPLIT ACROSS SIX FILES SINCE FS-584, and the split is exactly the kind of change that
quietly disables a guard like this one. The index kept the cited path; the sections moved into
`sweeps/part-*.md`. A guard that went on reading only the index would have found zero `## Rule
N` sections and passed every assertion below — reporting a perfectly consistent document while
checking nothing. `_text()` therefore reads the index AND every part, and
`test_it_reads_every_part_and_not_just_the_index` is what stops that failure mode returning.

SCOPED TO THE RULES SECTION, deliberately. Several prose sections in the same file enumerate
with the identical `1. **…**` formatting — the five maintenance-mode defects, the four things
the CI-quarantine guard asserts — so a file-wide regex reports duplicate rules 1–5 and is
useless. That mistake was made while writing this test and is the reason for the scoping.
"""

from __future__ import annotations

import pathlib
import re

from tests import _sweeps_document

DOC = (
    pathlib.Path(__file__).resolve().parents[2]
    / "docs"
    / "engineering"
    / "defect-class-sweeps.md"
)

#: The heading that opens the canonical numbered list.
LIST_HEADING = "## Writing a sweep that is worth trusting"

NUMBERED = re.compile(r"^(\d+)\. \*\*", re.M)
SECTION = re.compile(r"^## Rule (\d+)\b", re.M)

#: Sections exist only from this rule onward — 1–21 predate the convention and live in the
#: list alone. A section for a lower number would be fine; the asymmetry is just history.
FIRST_RULE_WITH_A_SECTION = 22


def _text() -> str:
    """The index and every part — see `_sweeps_document`, which both readers of this
    document share so that neither keeps a private idea of where it lives."""
    return _sweeps_document.text()


def _list_numbers() -> list[int]:
    """Rule numbers in the canonical list, which runs from its heading to the next `---`."""
    text = _text()
    start = text.index(LIST_HEADING)
    end = text.index("\n---\n", start)
    return [int(m.group(1)) for m in NUMBERED.finditer(text[start:end])]


def _section_numbers() -> list[int]:
    return [int(m.group(1)) for m in SECTION.finditer(_text())]


class TestTheCheckIsNotVacuous:
    def test_the_document_is_where_it_is_expected(self):
        assert DOC.exists(), f"{DOC} is gone; this guard is inspecting nothing"
        assert LIST_HEADING in _text(), "the canonical list's heading has moved or changed"

    def test_it_finds_a_substantial_list(self):
        numbers = _list_numbers()
        assert len(numbers) > 30, f"only {len(numbers)} numbered rules found"

    def test_it_finds_the_rule_sections(self):
        assert len(_section_numbers()) > 15

    def test_it_reads_every_part_and_not_just_the_index(self):
        """FS-584 moved every `## Rule N` section out of the cited file and into
        `sweeps/part-*.md`. A guard still reading only the index would find nothing and pass
        — the most comfortable failure there is, because a document that has stopped being
        checked and one that is perfectly consistent produce the same green tick."""
        found = _sweeps_document.parts()
        assert len(found) >= 5, f"only {len(found)} parts under {_sweeps_document.PARTS_DIR}"
        assert not list(SECTION.finditer(DOC.read_text())), (
            "a `## Rule N` section is back in the index file. Harmless in itself — but the "
            "index is the one file this guard read before the split, so a section here is "
            "the one place a drifted rule would still be found by accident."
        )

    def test_it_is_scoped_to_the_list(self):
        """A file-wide regex reports duplicate rules 1–5, because prose sections elsewhere
        enumerate with the same formatting — the five maintenance-mode defects and the four
        CI-quarantine assertions among them. This asserts the scoping actually excludes those,
        rather than trusting that it does."""
        whole_file = [int(m.group(1)) for m in NUMBERED.finditer(_text())]
        assert len(whole_file) > len(_list_numbers()), (
            "the scoped read is not narrower than the whole file, so the section boundary is "
            "not being applied"
        )


class TestTheListIsAnIndex:
    def test_the_numbers_are_contiguous_from_one(self):
        numbers = _list_numbers()
        expected = list(range(1, len(numbers) + 1))
        assert numbers == expected, (
            f"the rule list is not 1..{len(numbers)} in order — got {numbers}"
        )

    def test_no_rule_is_listed_twice(self):
        numbers = _list_numbers()
        duplicated = sorted({n for n in numbers if numbers.count(n) > 1})
        assert not duplicated, f"these rules appear more than once in the list: {duplicated}"

    def test_every_section_has_a_list_entry(self):
        """THE ASSERTION THIS FILE EXISTS FOR, and the drift it has caught three times: a rule
        written as a section while the list stops short of it."""
        missing = sorted(set(_section_numbers()) - set(_list_numbers()))
        assert not missing, (
            f"rules {missing} have a `## Rule N` section but no entry in the numbered list "
            f"under '{LIST_HEADING}'. Add a one-line entry pointing at the section — the list "
            "is what people read, and a rule that is not in it does not exist for them."
        )

    def test_every_recent_rule_has_a_section(self):
        """The other direction. A one-line entry with no fuller account is a rule nobody can
        apply — the reasoning is the useful part, and rules from 22 on are where it lives."""
        listed = {n for n in _list_numbers() if n >= FIRST_RULE_WITH_A_SECTION}
        missing = sorted(listed - set(_section_numbers()))
        assert not missing, (
            f"rules {missing} are listed but have no `## Rule N` section explaining them"
        )


class TestTheReadmeAgreesOnTheCount:
    def test_the_readme_cites_the_real_range(self):
        """The README states a rule range in two places. Both drifted during this session — the
        list said 21–38 while the doc had reached 41 — so the range is asserted rather than
        maintained by hand."""
        readme = (DOC.parents[2] / "README.md").read_text()
        highest = max(_list_numbers())
        assert f"Rules 21–{highest} are recorded in" in readme, (
            f"the README does not cite the current rule range (highest is {highest})"
        )

    def test_the_class_count_agrees_too(self):
        """THE RULES WERE GUARDED AND THE CLASSES WERE NOT (FS-445).

        This class checked the rule range and nothing checked the class count, so the
        document's own heading read "The forty-seven classes" while its highest class number
        was **60** — stale by thirteen, in the first heading a reader meets.

        The count is the NUMBERING, deliberately: classes 30–51 have no sections of their
        own (they are rows in the summary table), so counting headings gives a different and
        equally defensible number. Seeing 65 as the highest heading and writing "sixty-five
        classes" into the README is exactly the mistake this now prevents — asserting the
        numbering is what makes the phrase checkable against the document.
        """
        import re

        doc = _text()
        numbers = {int(m) for m in re.findall(r"^## (\d+)\.", doc, re.M)}
        numbers |= {int(m) for m in re.findall(r"^## Class (\d+)", doc, re.M)}
        assert numbers, "no class sections found; the heading patterns have drifted"
        highest = max(numbers)

        readme = (DOC.parents[2] / "README.md").read_text()
        phrase = f"{_spell(highest)} numbered classes"
        for name, text in (("the sweeps index", DOC.read_text()), ("the README", readme)):
            assert phrase in text, (
                f"{name} does not say '{phrase}'. The highest class number is {highest}, and "
                f"a count stated in prose beside a document that contradicts it is worse "
                f"than no count — this heading was wrong by thirteen for weeks"
            )


def _spell(n: int) -> str:
    """Just the range this document is plausibly in. A wrong word fails loudly, which is
    the point — the alternative is a digit nobody reads."""
    tens = {50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}
    units = ["", "-one", "-two", "-three", "-four", "-five", "-six", "-seven", "-eight",
             "-nine"]
    if n in tens:
        return tens[n]
    base = (n // 10) * 10
    if base in tens:
        return tens[base] + units[n % 10]
    raise AssertionError(f"class count {n} is outside the range this speller covers")
