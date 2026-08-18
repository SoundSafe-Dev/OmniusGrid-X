#!/usr/bin/env python3
"""Render the SSP, Statement of Applicability and POA&M from the control catalogue (FS-751).

WHY GENERATED AND NOT WRITTEN. Two compliance documents were deleted from this repository in
FS-745 for making 314 control claims with zero citations, six of them measurably false. The
catalogue replaced them, and the guards make a claim impossible to hold without a test that
exists. These renderers are what stops that discipline being lost at the last step: the
documents an assessor reads are *derived* from the same data the guards check, so a narrative
cannot drift from its evidence — there is nowhere for it to drift to.

ONE MODULE, THREE RENDERERS, rather than three scripts. They share the loader, the status
vocabulary, the profile ordering and the "generated" header, and this codebase has the scar
from the alternative three times over — `_route_tree.py`, `_sweeps_document.py` and
`compliance_catalog.py` all exist because two consumers hand-copied a traversal and drifted.
Three scripts would be three ideas of what `partial` means.

**THE OUTPUT IS DETERMINISTIC, AND THAT IS A DESIGN CONSTRAINT, NOT A NICETY.** Nothing here
records a wall-clock time, a hostname or a run id. `test_generated_compliance_docs_are_current.py`
re-renders in memory and compares byte for byte, so a timestamp would make the guard fail on
every run and it would be deleted within a week — at which point the documents quietly stop
matching the catalogue, which is the exact failure the guard exists to prevent. Provenance
comes from git: the commit that changed the catalogue is the commit that changed these files,
in the same diff.

Everything is sorted. A dict iteration order that changes between Python versions would show
up as a spurious diff, and a spurious diff teaches people to regenerate without reading.
"""

from __future__ import annotations

import csv
import io
import pathlib
import sys
from collections import defaultdict
from typing import Dict, Iterable, List

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.core.compliance_catalog import (  # noqa: E402
    PROFILES,
    Control,
    Crosswalk,
    load_controls,
    load_crosswalk,
    load_owners,
)

REPO = pathlib.Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO / "docs" / "compliance" / "generated"

GENERATED_HEADER = (
    "<!-- GENERATED FROM backend/compliance/catalog/ — DO NOT EDIT.\n"
    "     Regenerate with `make compliance`. Edits here are overwritten and, worse, are\n"
    "     invisible to the guards that keep control claims tied to tests. Change the\n"
    "     catalogue instead. -->\n"
)

#: How a status reads in a document meant for an assessor. The catalogue's vocabulary is
#: for engineers; these are the words an assessment uses.
STATUS_LABEL = {
    "implemented": "Implemented",
    "partial": "Partially implemented",
    "absent": "Not implemented",
    "organizational": "Organizational (not satisfiable by code)",
    "inherited": "Inherited from provider",
}


def _by_family(controls: Iterable[Control], crosswalk: Crosswalk) -> Dict[str, List[Control]]:
    grouped: Dict[str, List[Control]] = defaultdict(list)
    for control in controls:
        families = {p.rsplit(".", 1)[0] for p in control.practices(crosswalk.framework)}
        for family in families:
            grouped[family].append(control)
    return {family: sorted(items, key=lambda c: c.id) for family, items in grouped.items()}


def _status_summary(control: Control) -> str:
    """One line per control, collapsing profiles that agree.

    Four identical statuses print once. That is not cosmetic: a reader scanning 59 controls
    needs the DIFFERENCES to stand out, and the differences are the interesting part — a
    control that is inherited in cloud and organizational on-prem, or absent only air-gapped,
    is telling them something a uniform row is not.
    """
    values = {profile: control.status[profile] for profile in PROFILES}
    if len(set(values.values())) == 1:
        return STATUS_LABEL[next(iter(values.values()))]
    return "; ".join(
        f"{profile}: {STATUS_LABEL[values[profile]]}" for profile in PROFILES
    )


def render_ssp(controls: List[Control], crosswalk: Crosswalk) -> str:
    out = io.StringIO()
    out.write(GENERATED_HEADER)
    out.write("\n# System Security Plan — control implementation\n\n")
    out.write(
        f"Framework: **NIST SP 800-171 {crosswalk.revision}**, "
        f"{crosswalk.total_practices} practices.\n\n"
    )
    out.write(
        "Status is stated **per deployment profile**. OmniusGrid ships to commercial cloud, "
        "gov cloud, on-premises and air-gapped environments, and a control is a property of "
        "code *in a place*: physical protection is inherited from a provider in cloud and "
        "organizational on-premises; clock discipline is partial online and absent "
        "air-gapped. A single status would have to be wrong about at least one profile.\n\n"
    )

    counts = defaultdict(int)
    for control in controls:
        counts[control.status["commercial-cloud"]] += 1
    out.write("## Summary (commercial cloud profile)\n\n")
    out.write("| Status | Controls |\n|---|---|\n")
    for status in ("implemented", "partial", "absent", "organizational", "inherited"):
        out.write(f"| {STATUS_LABEL[status]} | {counts[status]} |\n")
    out.write(
        f"\n{len(controls)} controls covering all {crosswalk.total_practices} practices. "
        f"**Covered is not implemented** — every practice has an honest answer, and the "
        f"answers are above.\n"
    )

    grouped = _by_family(controls, crosswalk)
    for family in sorted(grouped):
        name = crosswalk.families.get(family, {}).get("name", family)
        out.write(f"\n---\n\n## {family} — {name}\n")
        for control in grouped[family]:
            out.write(f"\n### {control.id} — {control.title}\n\n")
            out.write(f"**Status.** {_status_summary(control)}\n\n")
            practices = ", ".join(sorted(control.practices(crosswalk.framework)))
            out.write(f"**Practices.** {practices}\n\n")
            other = sorted(
                ref for ref in control.satisfies
                if not ref.startswith(f"{crosswalk.framework}:")
            )
            if other:
                out.write(f"**Also satisfies.** {', '.join(other)}\n\n")
            out.write(f"**Owner.** {control.owner}\n\n")

            if control.why_code_cannot:
                out.write(f"**Why this is not a code control.** {control.why_code_cannot.strip()}\n\n")
            if control.provider:
                out.write(
                    f"**Inherited from.** {control.provider} "
                    f"(customer responsibility matrix: {control.crm_ref})\n\n"
                )
            if control.notes:
                out.write(f"**Implementation.** {control.notes.strip()}\n\n")
            if control.remediation and control.remediation.get("note"):
                out.write(
                    f"**Assessment.** {str(control.remediation['note']).strip()}\n\n"
                )
                out.write(f"**Planned completion.** {control.remediation.get('due')}\n\n")
            if control.implemented_by:
                out.write("**Implemented by.**\n\n")
                for path in sorted(control.implemented_by):
                    out.write(f"- `{path}`\n")
                out.write("\n")
            if control.proved_by:
                out.write("**Evidence — automated tests, run on every build.**\n\n")
                for path in sorted(control.proved_by):
                    out.write(f"- `{path}`\n")
                out.write("\n")
    return out.getvalue()


def render_soa(controls: List[Control]) -> str:
    """ISO 27001 Statement of Applicability, from the Annex A references controls carry."""
    by_annex: Dict[str, List[Control]] = defaultdict(list)
    for control in controls:
        for ref in control.satisfies:
            if ref.startswith("ISO27001:"):
                by_annex[ref.split(":", 1)[1]].append(control)

    out = io.StringIO()
    out.write(GENERATED_HEADER)
    out.write("\n# Statement of Applicability — ISO/IEC 27001 Annex A\n\n")
    out.write(
        "Derived from the Annex A references carried by each OmniusGrid control. **This is "
        "a partial SoA and says so**: it lists the Annex A controls this system's technical "
        "controls map to, not the full Annex A set. A complete SoA must state applicability "
        "for every Annex A control including those excluded, with justification, and that "
        "requires the ISMS scope — which is an organizational decision, not a repository "
        "one. Generating a full-looking SoA from partial data would be the same class of "
        "claim that got two documents deleted in FS-745.\n\n"
    )
    out.write("| Annex A | Applicable | Implementing control | Status (commercial cloud) |\n")
    out.write("|---|---|---|---|\n")
    for annex in sorted(by_annex):
        for control in sorted(by_annex[annex], key=lambda c: c.id):
            out.write(
                f"| {annex} | Yes | {control.id} — {control.title} "
                f"| {STATUS_LABEL[control.status['commercial-cloud']]} |\n"
            )
    return out.getvalue()


def render_poam(controls: List[Control], owners: Dict[str, dict]) -> str:
    """Plan of Action and Milestones, as CSV — the format an assessor works in.

    One row per (control, profile) that is not implemented, rather than one per control. A
    control absent only on air-gapped is a different piece of work from one absent
    everywhere, and collapsing them hides which deployment is exposed.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "POAM ID", "Control", "Title", "Deployment profile", "Status",
        "Practices", "Weakness / remaining work", "Owner", "Owner lane",
        "Scheduled completion",
    ])
    rows = []
    for control in controls:
        for profile in PROFILES:
            status = control.status[profile]
            if status not in ("partial", "absent"):
                continue
            remediation = control.remediation or {}
            rows.append([
                f"{control.id}-{profile}",
                control.id,
                control.title,
                profile,
                STATUS_LABEL[status],
                " ".join(sorted(control.practices())),
                " ".join(str(remediation.get("note", "")).split()),
                control.owner,
                owners.get(control.owner, {}).get("lane", "unassigned"),
                remediation.get("due", ""),
            ])
    for row in sorted(rows, key=lambda r: (r[9], r[0])):
        writer.writerow(row)
    return buffer.getvalue()


def main() -> int:
    controls = load_controls()
    crosswalk = load_crosswalk()
    owners = load_owners()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "system-security-plan.md": render_ssp(controls, crosswalk),
        "statement-of-applicability.md": render_soa(controls),
        "poam.csv": render_poam(controls, owners),
    }
    for name, body in artifacts.items():
        (OUTPUT_DIR / name).write_text(body)
        print(f"wrote {OUTPUT_DIR.relative_to(REPO) / name} ({len(body):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
