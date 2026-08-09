"""The numbers in the open-decisions register are still true (FS-453).

`docs/engineering/open-decisions.md` exists so somebody deciding can see the open items
together, and every entry carries a figure: eleven capped lists, thirty-eight unfillable
registries, five declared fields on shapes the server never defines.

**Those figures are claims, and this week produced four wrong ones** — a registry count of 41
that was 38, a class heading reading forty-seven beside a document numbering sixty, a rule
range of 21–75 beside an index of 78, and a README class count I derived from the highest
heading rather than the numbering. Three were caught by a test; one sat wrong for weeks
because nothing compared the pair.

A register nobody can trust is worse than no register: it is read once, found wrong, and
then discounted — including the entries that were right.

WHAT THIS ASSERTS AND WHAT IT DOES NOT. Not the prose, not the reasoning, not whether an
entry still deserves to be open. Only that each **number** the document states still matches
the thing it describes. When a ratchet moves, this fails and the register gets updated in the
same commit — which is the only way a document like this stays worth reading.

The pairing is deliberate and matches `test_method_rules_are_indexed`: two things that must
agree are a pair, and a pair needs a guard.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTER = ROOT / "docs" / "engineering" / "open-decisions.md"


def _constant(relative: str, name: str) -> int:
    """Read `NAME = <int>` out of a test module without importing it."""
    source = (Path(__file__).resolve().parent.parent / relative).read_text()
    match = re.search(rf"^{name}\s*=\s*(\d+)", source, re.M)
    assert match, f"{name} not found in {relative}"
    return int(match.group(1))


def _registry_counts() -> tuple[int, int]:
    """(mapped domains, domains nothing can populate)."""
    from app.services.correlation_registry_integration import (
        DOMAIN_REGISTRY_MAPPING,
        correlation_registry_integration as integration,
    )

    pattern = r'"([A-Z_]+)":\s*\['
    extractable = set(
        re.findall(pattern, inspect.getsource(integration._extract_domains_from_analysis))
    )
    with_defaults = set(
        re.findall(pattern, inspect.getsource(integration._get_default_items_for_domain))
    )
    mapped = set(DOMAIN_REGISTRY_MAPPING)
    return len(mapped), len(mapped - extractable - with_defaults)


TEXT = REGISTER.read_text()

#: Section titles that are not open decisions.
#: Headings that are the page's furniture rather than an open decision. "None open" stays
#: after the register gained an entry again (FS-574): the phrase is what an emptied register
#: says about itself, and deleting it here would make the day it empties again a test
#: failure rather than good news.
_NOT_ENTRIES = (
    "Not on this page",
    "Closed, and what closing one cost",
    "None open",
    "Everything else here was closed",
)


def _open_entries(text: str | None = None) -> list[str]:
    """Titles of the open-decision sections, excluding the page's own furniture."""
    source = TEXT if text is None else text
    return [
        block.splitlines()[0]
        for block in source.split("\n## ")[1:]
        if not block.startswith(_NOT_ENTRIES)
    ]


class TestTheRegisterIsReadable:
    def test_it_exists_and_still_says_something(self):
        # Vacuity: a gutted or moved file would make every assertion below pass over
        # nothing, which is how a register quietly stops being checked.
        assert len(TEXT) > 2000, "the open-decisions register is missing or has been gutted"
        assert "## Closed, and what closing one cost" in TEXT, (
            "the closed-items section is gone; with no open entries it is the only thing "
            "on this page carrying information"
        )

    def test_every_entry_names_the_test_that_pins_it(self):
        """An entry without a pin is a note, and notes are what this document replaced.

        THE REGISTER IS EMPTY (2026-08-05), so this iterates nothing — and that is why the
        parse is asserted separately below rather than inferred from a non-empty result.
        A test that passes over an empty list looks identical whether the list is empty
        because the work is done or because the parser broke.
        """
        entries = _open_entries()
        for entry in entries:
            section = TEXT.split(f"\n## {entry}", 1)[1].split("\n## ", 1)[0]
            assert "Pinned by" in section or "pinned by" in section, (
                f"the entry '{entry}' names no test. An open decision nothing asserts is a "
                f"decision that will be discovered again rather than closed"
            )

    def test_the_parser_would_see_an_entry_if_there_were_one(self):
        """The vacuity guard for the test above, since the register is at zero.

        Without this, deleting `_open_entries`' logic and returning `[]` would look exactly
        like a page with nothing open.
        """
        sample = "# T\n\n## 1. A thing that is open\n\nPinned by `x`\n\n## Not on this page\n"
        assert _open_entries(sample) == ["1. A thing that is open"]

    def test_an_empty_register_says_so_in_words(self):
        """A page with no headings could be an empty register or a broken one. The
        difference has to be written down, because a reader cannot tell by looking."""
        if not _open_entries():
            assert "## None open" in TEXT, (
                "no entries are open and the page does not say so, which reads as a "
                "register somebody forgot rather than one somebody emptied"
            )


class TestTheNumbersStillMatch:
    """Each figure the register states, against the thing it describes.

    Most of these moved into the closed section as the entries closed. They are still
    checked there: a closed entry describing the state that made it worth closing is a
    claim like any other, and "38 registries nothing could fill" stops being true the day
    someone gives those domains keywords.
    """

    def test_the_ratchets_it_calls_closed_are_closed(self):
        """The register names four ratchets as being at zero. If any moves, the page is
        describing a past that is no longer the present."""
        for relative, name in (
            ("tests/test_frontend_types_match_their_own_payload.py", "MAX_UNFED_FIELDS"),
            ("tests/test_adapter_built_types_are_fed.py", "MAX_UNSET_FIELDS"),
            ("tests/test_capped_lists_cannot_grow.py", "MAX_UNSIGNALLED"),
            ("tests/test_frontend_fields_exist_on_the_wire.py", "MAX_UNREAD_PHANTOM_FIELDS"),
        ):
            assert _constant(relative, name) == 0, (
                f"{name} is no longer zero, and the register lists it among the ratchets "
                f"that reached zero"
            )

    def test_the_registry_figures_in_the_closed_note_are_true(self):
        mapped, unfillable = _registry_counts()
        assert f"{unfillable} registries nothing could fill" in TEXT, (
            f"the closed note cites an unfillable-registry count that is no longer "
            f"{unfillable}. If those domains gained extractor keywords that is good news "
            f"and the note should say the new number"
        )


def test_every_pinned_test_file_exists():
    """`test_documented_files_exist` already checks paths in this file. This checks the
    narrower thing that matters here: a pin that names a test which was deleted leaves an
    entry nothing enforces, and the register would still read as though something did."""
    cited = set(re.findall(r"`(backend/tests/[\w./]+\.py)`", TEXT))
    assert len(cited) >= 4, f"only {len(cited)} pinned test files cited; the parse is broken"
    missing = sorted(path for path in cited if not (ROOT / path).exists())
    assert not missing, f"these pinned tests no longer exist: {missing}"
