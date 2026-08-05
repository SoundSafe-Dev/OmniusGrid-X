"""A source file the docs point at must be in the repository.

The companion to `test_documented_endpoints_exist.py`. That one checks the API Reference;
this one checks every `path/to/file.py` the prose cites. Same class, same reason: a
document nobody executes drifts silently, and a reader who goes looking for a named file
and cannot find it has no way to tell whether it moved, was renamed, or never existed.

WHAT IT FOUND. The ERP project-structure listing named **`sap_correlation_patterns.py`**,
alongside its Oracle and Dynamics siblings, which both exist. It never has. SAP
correlation runs through the generic `app/services/erp_correlation_patterns.py`, and the
symmetry of the list made the gap invisible — three vendors, three bullets, one of them
fiction. The same pass found four real files the listing omitted (`intuit_connector.py`,
`intuit_qbo.py`, `netsuite_auth.py`, `oauth2.py`, `sap_batch.py`), which is the quieter
half: an inventory is only useful if it is complete in both directions.

SCOPE: the three top-level documents, and deliberately not `docs/**`. That tree was
swept by hand and came back clean, but its 50 files use three idioms this guard cannot
tell apart from a broken reference — "Create `configs/lora_config.json`:" (an instruction,
not a claim), "`network-policies.yaml`, which does not exist" (a deliberate absence note,
the same shape as the SAP one above), and unchecked checklist items for files not yet
written. Extending the guard there would produce eleven false positives on correct prose,
which is the fastest way to make a check worth ignoring.

HOW A NAME IS RESOLVED. Exact repo-relative path first, then a suffix match against
`git ls-files`, because the docs legitimately write `sap_connector.py` for
`backend/app/services/erp_connectors/sap_connector.py`. Only the file's *existence* is
asserted, never its location — tightening that would fail on every prose mention and
teach the reader to ignore this file.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
from typing import Dict, List, Set

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = [
    ROOT / "README.md",
    ROOT / "OMNIUSGRID_GLOSSARY.md",
    ROOT / "docs" / "engineering" / "defect-class-sweeps.md",
    # ADDED WHEN THE DELIVERY LOG MOVED OUT OF THE README (2026-08-02). Those 1,048 lines
    # cite source files heavily, and this list is scoped to top-level documents rather than
    # `docs/**` — so relocating them would have quietly dropped every one of those citations
    # from the check while the file count went UP. Moving prose out of a checked document
    # moves it out of the check unless the scope moves with it.
    ROOT / "docs" / "DELIVERY-LOG.md",
]

#: `` `something.py` `` — a backticked filename with a source extension.
#:
#: The leading `[A-Za-z0-9_]` is load-bearing (FS-443): without it, prose naming a bare
#: EXTENSION matched. "the sweep now skips `.d.ts` entirely" was reported as a missing file,
#: which is a sentence about a file-type, not a citation of a path. A basename is required
#: before the dot, so `.d.ts` and `.tsx` are prose and `foo.d.ts` is still a citation.
CITED = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|tsx?|sql|ya?ml))`")

#: Names the docs cite ON PURPOSE while they do not exist here, with the reason.
#: Not a convenience list — each entry is a claim that has to stay true.
DELIBERATELY_ABSENT: Dict[str, str] = {
    # The "superseded paths" table in the README compares Hridyansh's `integration`
    # branch against this one. Its LEFT column is his paths; they are supposed to be
    # missing here, and that is the point the table is making.
    "backend/app/api/keycloak_auth.py": "his branch's path; here it is app/api/sso.py + services/keycloak_service.py",
    "backend/app/services/audit_trail.py": "his branch's path; here it is services/audit.py + api/audit.py + middleware/audit.py",
    "infra/k8s/timescaledb-patroni.yml": "his branch's path; here infrastructure/k8s/database-ha/ + legacy-patroni/",
    "infra/k8s/pgbackrest-backup.yml": "his branch's path; here infrastructure/k8s/legacy-patroni/pgbackrest-backup.yml",
    "frontend/.../RealtimeStreamChart.tsx": "an elided path in that same table; referenced by nothing on either branch",
}


def _tracked() -> Set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return set(out.stdout.split())


TRACKED = _tracked()
CITATIONS: Set[str] = set()
for _doc in DOCS:
    if _doc.exists():
        CITATIONS |= set(CITED.findall(_doc.read_text()))


#: Directories that are on disk but are not the repository.
_IGNORED = ("node_modules", "venv", "__pycache__", ".git", "dist", "build", ".pytest_cache")


def _on_disk() -> Set[str]:
    """Basenames present in the working tree.

    `git ls-files` alone is NOT enough, and the omission failed this file on its own
    first run: a source file added in the same commit as the sentence describing it is
    not yet tracked, so the guard called the documentation wrong when the documentation
    was right. A check that cannot see new work punishes exactly the change it should be
    encouraging.
    """
    found: Set[str] = set()
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _IGNORED for part in path.parts):
            continue
        found.add(path.name)
    return found


ON_DISK = _on_disk()


def _resolves(name: str) -> bool:
    if name in TRACKED or (ROOT / name).exists():
        return True
    # The docs write a bare filename for a file that lives several directories down.
    if any(t == name or t.endswith("/" + name) for t in TRACKED):
        return True
    return name.split("/")[-1] == name and name in ON_DISK


UNRESOLVED: List[str] = sorted(
    name for name in CITATIONS if name not in DELIBERATELY_ABSENT and not _resolves(name)
)


class TestTheSweepIsNotVacuous:
    def test_it_reads_the_docs(self):
        assert len(CITATIONS) >= 80, (
            f"only {len(CITATIONS)} filenames cited across the docs; the pattern no "
            f"longer matches and this file would pass while checking nothing"
        )

    def test_it_reads_the_repository(self):
        assert len(TRACKED) >= 500, f"only {len(TRACKED)} tracked files found"

    def test_it_sees_a_file_that_is_not_committed_yet(self):
        """This file failed its own first run for this reason: it was new, so
        `git ls-files` did not list it, and the guard called the sentence describing it
        a broken reference. A check that cannot see uncommitted work fails the change it
        exists to support."""
        assert _resolves("test_documented_files_exist.py")

    def test_a_real_file_resolves_by_bare_name(self):
        """The docs say `sap_connector.py`, not the full path. If suffix matching
        breaks, every prose mention fails at once."""
        assert _resolves("sap_connector.py")

    def test_an_invented_file_does_not_resolve(self):
        """Proves the check can fail — and this is the exact name the ERP listing
        carried, between two siblings that do exist."""
        assert not _resolves("sap_correlation_patterns.py")

    def test_an_exemption_cannot_excuse_a_name_used_as_a_citation(self):
        """THE FIRST VERSION OF THIS FILE GOT THIS WRONG. `sap_correlation_patterns.py`
        was exempted by name, so re-adding it as a bullet in the ERP listing still
        passed — the exemption excused the fiction it was written to record. The
        sentence noting its absence now spells the name WITHOUT backticks, so the
        citation pattern does not see it and no exemption is needed. An exemption keyed
        on a bare name is a hole with a comment attached."""
        assert "sap_correlation_patterns.py" not in DELIBERATELY_ABSENT
        assert "sap_correlation_patterns.py" not in CITATIONS


class TestEveryCitedFileExists:
    def test_no_document_points_at_a_missing_file(self):
        assert not UNRESOLVED, (
            "These are named in the documentation and are not in the repository. A "
            "reader who goes looking cannot tell whether the file moved, was renamed, "
            "or never existed:\n  " + "\n  ".join(UNRESOLVED)
        )


class TestTheExemptionsStayHonest:
    def test_each_one_states_a_reason(self):
        for name, reason in DELIBERATELY_ABSENT.items():
            assert len(reason) > 25, f"{name} is exempted without a real reason"

    def test_none_of_them_has_quietly_appeared(self):
        """The other direction. An exemption for a file that now exists is a stale
        claim, and it hides that file from the check for as long as it sits there."""
        appeared = [n for n in DELIBERATELY_ABSENT if _resolves(n)]
        assert not appeared, (
            f"these are exempted as absent but now resolve: {appeared} — drop them from "
            f"DELIBERATELY_ABSENT so they are covered again"
        )

    def test_they_are_still_cited(self):
        """An exemption for a name the docs no longer mention is dead weight that
        outlives whatever it was protecting."""
        orphaned = [n for n in DELIBERATELY_ABSENT if n not in CITATIONS]
        assert not orphaned, f"exempted but no longer cited anywhere: {orphaned}"
