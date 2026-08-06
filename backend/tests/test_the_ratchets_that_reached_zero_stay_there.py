"""The four ratchets that reached zero stay at zero (FS-471).

A ratchet is a number a test allows and never raises: `MAX_UNSIGNALLED = 11` means eleven
endpoints may cap a list without saying so, and the test fails at twelve. It works because
the number only ever goes down.

**At zero it stops working.** There is no allowance left to lower, no failing test to argue
with, and raising it is a one-character edit in a file whose whole purpose is to prevent the
thing being re-allowed. The register that used to carry these figures is empty, so nothing
else names them either.

    MAX_UNFED_FIELDS            a declared field the server never populates
    MAX_UNSET_FIELDS            an adapter-built type with a field nothing sets
    MAX_UNSIGNALLED             a capped list that cannot say it was capped
    MAX_UNREAD_PHANTOM_FIELDS   a frontend field with no producer and no reader

Each reached zero by a different route, which is the part worth keeping. Two were closed by
building the missing half — `mark_truncated` on eleven endpoints, producers for 38 unfed
fields. One was closed by deleting: the registries nothing could fill are no longer created.
One turned out not to be debt at all — the last five "phantoms" described a server field
declared `Dict[str, Any]`, so the question had no answer and the sweep learned to stop asking
it.

WHAT THIS ASSERTS AND WHY IT IS SEPARATE. Not that the underlying sweeps work — each has its
own guard and its own mutation-verified detector. Only that the ALLOWANCES stay at zero, in
one file, so raising any of them fails here as well as wherever it is raised. A number that
four documents cite and nothing checks is how this repository got four wrong figures in a
single week.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

#: ratchet -> (file that declares it, what a non-zero value would mean)
AT_ZERO: dict[str, tuple[str, str]] = {
    "MAX_UNFED_FIELDS": (
        "test_frontend_types_match_their_own_payload.py",
        "a type declares a field its own endpoint never populates, so a template reads "
        "`undefined` and renders nothing",
    ),
    "MAX_UNSET_FIELDS": (
        "test_adapter_built_types_are_fed.py",
        "an adapter builds a type and leaves a field unset, which is the same defect one "
        "layer further in and invisible to the sweep above",
    ),
    "MAX_UNSIGNALLED": (
        "test_capped_lists_cannot_grow.py",
        "an endpoint caps a bare array and cannot say so, so a full page is "
        "indistinguishable from the complete set",
    ),
    "MAX_UNREAD_PHANTOM_FIELDS": (
        "test_frontend_fields_exist_on_the_wire.py",
        "a frontend field has no backend producer and no reader — a field waiting for a "
        "pane that mock mode will make look finished",
    ),
}


def _value(filename: str, name: str) -> int:
    source = (TESTS / filename).read_text()
    match = re.search(rf"^{name}\s*=\s*(\d+)", source, re.M)
    assert match, f"{name} is no longer declared in {filename}"
    return int(match.group(1))


class TestTheSweepCanSeeItsSubject:
    def test_every_named_file_exists(self):
        for name, (filename, _why) in AT_ZERO.items():
            assert (TESTS / filename).exists(), (
                f"{filename} is gone, so {name} is unpinned — deleting the file is the "
                f"other way to raise a ratchet"
            )

    def test_the_reader_finds_a_number(self):
        """Vacuity: a regex that matched nothing would make every assertion below pass."""
        for name, (filename, _why) in AT_ZERO.items():
            assert isinstance(_value(filename, name), int)


@pytest.mark.parametrize("name", sorted(AT_ZERO))
def test_the_ratchet_is_still_zero(name: str):
    filename, why = AT_ZERO[name]
    value = _value(filename, name)
    assert value == 0, (
        f"{name} is {value}, and it reached zero. Raising a ratchet re-permits the defect "
        f"it was counting: {why}.\n\n"
        f"If {value} instances genuinely exist again, that is a regression to fix rather "
        f"than a number to raise — the allowance existed to be spent down, and it has been."
    )


def test_the_readme_still_claims_four():
    """The pairing. The README says four ratchets are at zero; if a fifth joins them or one
    is removed, the prose and this file disagree and one of them is wrong."""
    readme = (TESTS.parent.parent / "README.md").read_text()
    assert "Four ratchets are at zero" in readme, (
        "the README no longer states how many ratchets are at zero, or states a different "
        "number than this file tracks"
    )
    assert len(AT_ZERO) == 4, (
        f"this file tracks {len(AT_ZERO)} ratchets and the README says four"
    )
