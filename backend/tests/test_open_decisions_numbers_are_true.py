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


class TestTheRegisterIsReadable:
    def test_it_exists_and_has_entries(self):
        # Vacuity: an empty or moved file would make every assertion below pass over
        # nothing, which is how a register quietly stops being checked.
        assert len(TEXT) > 2000, "the open-decisions register is missing or has been gutted"
        assert TEXT.count("\n## ") >= 5, "fewer entries than expected; has the file changed shape?"

    def test_every_entry_names_the_test_that_pins_it(self):
        """An entry without a pin is a note, and notes are what this document replaced."""
        entries = [
            block.splitlines()[0]
            for block in TEXT.split("\n## ")[1:]
            if not block.startswith("Not on this page")
        ]
        assert entries, "no entries parsed"
        for entry in entries:
            section = TEXT.split(f"\n## {entry}", 1)[1].split("\n## ", 1)[0]
            assert "Pinned by" in section or "pinned by" in section, (
                f"the entry '{entry}' names no test. An open decision nothing asserts is a "
                f"decision that will be discovered again rather than closed"
            )


class TestTheNumbersStillMatch:
    """Each figure the register states, against the thing it describes."""

    def test_the_capped_list_count(self):
        actual = _constant("tests/test_capped_lists_cannot_grow.py", "MAX_UNSIGNALLED")
        assert f"MAX_UNSIGNALLED = {actual}" in TEXT, (
            f"the register cites a capped-list count that is no longer {actual}. Lower it "
            f"there in the same commit that lowers the ratchet"
        )

    def test_the_phantom_field_count(self):
        actual = _constant(
            "tests/test_frontend_fields_exist_on_the_wire.py", "MAX_UNREAD_PHANTOM_FIELDS"
        )
        assert f"MAX_UNREAD_PHANTOM_FIELDS = {actual}" in TEXT, (
            f"the register cites a phantom-field count that is no longer {actual}"
        )

    def test_the_registry_counts(self):
        mapped, unfillable = _registry_counts()
        assert f"Of {mapped}:" in TEXT, (
            f"the register says the mapping has a different size; it now has {mapped} domains"
        )
        assert f"**{unfillable}**" in TEXT, (
            f"the register cites an unfillable-registry count that is no longer {unfillable}. "
            f"This is the figure that was written as 41 and is 38 — the five domains with "
            f"default items are a SUBSET of the eight extractable ones, not a separate group"
        )

    def test_the_ratchets_it_calls_closed_are_closed(self):
        """The register's last section names two ratchets as being at zero. If either moves,
        they are open decisions again and belong in the body rather than the footnote."""
        for relative, name in (
            ("tests/test_frontend_types_match_their_own_payload.py", "MAX_UNFED_FIELDS"),
            ("tests/test_adapter_built_types_are_fed.py", "MAX_UNSET_FIELDS"),
        ):
            assert _constant(relative, name) == 0, (
                f"{name} is no longer zero, but the register lists it under ratchets that "
                f"'are at zero and stay there by assertion'"
            )
            assert f"{name} = 0" in TEXT, f"the register no longer states {name} = 0"


def test_every_pinned_test_file_exists():
    """`test_documented_files_exist` already checks paths in this file. This checks the
    narrower thing that matters here: a pin that names a test which was deleted leaves an
    entry nothing enforces, and the register would still read as though something did."""
    cited = set(re.findall(r"`(backend/tests/[\w./]+\.py)`", TEXT))
    assert len(cited) >= 4, f"only {len(cited)} pinned test files cited; the parse is broken"
    missing = sorted(path for path in cited if not (ROOT / path).exists())
    assert not missing, f"these pinned tests no longer exist: {missing}"
