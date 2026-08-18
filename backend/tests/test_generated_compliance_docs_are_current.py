"""The published compliance documents match the catalogue they claim to come from (FS-751).

WITHOUT THIS FILE THE RENDERERS ARE DECORATION. A generated document is only trustworthy
while it matches its source; the moment the catalogue moves and nobody re-runs `make
compliance`, the SSP an assessor reads becomes a snapshot of a system that no longer exists —
and it will still look authoritative, because generated documents always do.

That is precisely the failure mode of the two files deleted in FS-745. They were plausible,
detailed, formatted like compliance documents, and wrong. The only structural difference here
is that these can be *checked*, so this file checks them.

HOW: re-render in memory and compare byte for byte. Not "does it parse", not "does it mention
each control" — byte equality, because any weaker check has to decide which differences
matter, and the differences that matter are exactly the ones nobody anticipated.

THIS IS ALSO THE DETERMINISM TEST. The renderers deliberately record no wall-clock time, no
hostname and no run id; if one were added, this guard would fail on every run, be labelled
flaky, and be deleted — after which the documents drift silently. So a failure here means one
of two things, and the message says which to look for: the catalogue changed and the
documents were not regenerated, or something non-deterministic crept into the renderer.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
GENERATED = REPO / "docs" / "compliance" / "generated"

sys.path.insert(0, str(BACKEND / "scripts"))

from compliance.render import (  # noqa: E402
    render_poam,
    render_soa,
    render_ssp,
)
from app.core.compliance_catalog import (  # noqa: E402
    load_controls,
    load_crosswalk,
    load_owners,
)


def _rendered() -> dict[str, str]:
    controls = load_controls()
    crosswalk = load_crosswalk()
    owners = load_owners()
    return {
        "system-security-plan.md": render_ssp(controls, crosswalk),
        "statement-of-applicability.md": render_soa(controls),
        "poam.csv": render_poam(controls, owners),
    }


class TestTheMeasurementIsReal:
    def test_the_documents_exist(self):
        missing = [name for name in _rendered() if not (GENERATED / name).exists()]
        assert not missing, (
            f"{missing} have never been generated. Run `make compliance`. A compliance "
            f"package with no SSP is not a package."
        )

    def test_they_are_not_trivially_small(self):
        """A renderer that produced an empty file would satisfy byte-equality against an
        empty file. Both sides have to be real."""
        for name, body in _rendered().items():
            assert len(body) > 2000, f"{name} rendered to {len(body)} bytes"


class TestTheyMatchTheCatalogue:
    @pytest.mark.parametrize("name", sorted(_rendered()))
    def test_the_published_file_is_current(self, name: str):
        published = (GENERATED / name).read_text()
        expected = _rendered()[name]
        assert published == expected, (
            f"docs/compliance/generated/{name} does not match the catalogue.\n\n"
            f"Either the catalogue changed and the documents were not regenerated — run "
            f"`make compliance` and commit the result — or something non-deterministic was "
            f"added to the renderer, in which case this guard will fail on every run and "
            f"must be fixed rather than skipped. Nothing here may record a timestamp, a "
            f"hostname or a run id."
        )


class TestTheDocumentsDoNotOverclaim:
    """The renderers inherit the catalogue's honesty. These pin the specific places where a
    generated document could quietly become a stronger claim than its data supports."""

    def test_the_ssp_states_that_covered_is_not_implemented(self):
        body = (GENERATED / "system-security-plan.md").read_text()
        assert "Covered is not implemented" in body, (
            "the SSP reports coverage without the qualifier. '110 of 110' read alone is a "
            "score, and it is the number an assessor will quote back."
        )

    def test_the_soa_admits_it_is_partial(self):
        body = (GENERATED / "statement-of-applicability.md").read_text()
        assert "partial SoA" in body, (
            "the Statement of Applicability does not say it is partial. A complete SoA "
            "states applicability for EVERY Annex A control including exclusions with "
            "justification, which needs the ISMS scope — an organizational decision. A "
            "full-looking SoA generated from partial data is the FS-745 failure again."
        )

    def test_every_poam_row_has_an_owner_and_a_date(self):
        import csv

        with (GENERATED / "poam.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        assert rows, "the POA&M is empty"
        undated = [
            r["POAM ID"] for r in rows
            if not r["Scheduled completion"].strip() or not r["Owner"].strip()
        ]
        assert not undated, (
            f"{undated[:5]} have no owner or no date. A POA&M line without both is a "
            f"decision nobody has to make again, which is how a POA&M becomes a list that "
            f"is never revisited."
        )
