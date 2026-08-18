"""The one reader of the compliance control catalogue (FS-746).

WHY A SHARED LOADER RATHER THAN `yaml.safe_load` AT EACH CALL SITE. Four things will read
this catalogue — the registration guard, the evidence guard, the SSP/SoA/POA&M renderers,
and eventually a status endpoint. Every one of them needs the same answers to "where does it
live", "what is a valid status", and "what does a missing key mean". This codebase has the
scar from the alternative: `tests/_route_tree.py` exists because two guards hand-copied a
route walk and drifted, and `tests/_sweeps_document.py` for the same reason. A catalogue read
four ways is a catalogue that means four things.

THE VALIDATION IS DELIBERATELY STRICT, AND FAILS LOUD. An unknown key is an error, not a
warning — a typo'd `proved_by:` that silently becomes nothing would turn an evidenced control
into an unevidenced one while still reading as complete in the file. That is the precise
failure this whole catalogue exists to prevent, so the loader may not commit it.

STATUS IS PER DEPLOYMENT PROFILE, and that is not over-engineering. OmniusGrid ships to
commercial cloud, gov cloud, on-prem and air-gapped. Physical protection is `inherited` from
the provider in cloud and `organizational` on-prem; an identity control that leans on an IdP
round-trip is `implemented` online and `partial` air-gapped. One global status would have to
be wrong about at least one profile, and being wrong in a compliance artifact is the thing
that costs the credibility of everything beside it.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import yaml

#: The catalogue root. One definition, imported by everything that reads it.
CATALOG_DIR = pathlib.Path(__file__).resolve().parents[2] / "compliance" / "catalog"
CROSSWALK = CATALOG_DIR / "crosswalk.yaml"
OWNERS = CATALOG_DIR / "owners.yaml"

#: Deployment profiles a control's status is stated for. Every control must name all four:
#: a missing profile is an unanswered question, not a safe default.
PROFILES: Tuple[str, ...] = (
    "commercial-cloud",
    "gov-cloud",
    "on-prem",
    "air-gapped",
)

#: What a status may be, and what each obliges the author to supply.
#:
#:   implemented    the control operates here; `proved_by` must name tests that exist
#:   partial        it operates incompletely; needs `proved_by` AND a remediation entry
#:   absent         it does not operate here; needs a remediation entry
#:   organizational this cannot be satisfied by code; needs `why_code_cannot`
#:   inherited      a provider supplies it; needs `provider` and `crm_ref`
STATUSES: Tuple[str, ...] = (
    "implemented",
    "partial",
    "absent",
    "organizational",
    "inherited",
)

#: Statuses that assert the control actually works, and therefore owe evidence.
EVIDENCED_STATUSES = frozenset({"implemented", "partial"})

#: Statuses that owe a remediation entry with an owner and a date.
REMEDIABLE_STATUSES = frozenset({"partial", "absent"})

_ALLOWED_KEYS = frozenset(
    {
        "id",
        "title",
        "satisfies",
        "status",
        "implemented_by",
        "proved_by",
        "evidence",
        "owner",
        "remediation",
        "why_code_cannot",
        "provider",
        "crm_ref",
        "notes",
    }
)

_REQUIRED_KEYS = frozenset({"id", "title", "satisfies", "status", "owner"})


class CatalogError(ValueError):
    """A catalogue that cannot be trusted to mean what it says."""


@dataclass(frozen=True)
class Control:
    id: str
    title: str
    satisfies: Tuple[str, ...]
    status: Mapping[str, str]
    owner: str
    source_file: str
    implemented_by: Tuple[str, ...] = ()
    proved_by: Tuple[str, ...] = ()
    evidence: Tuple[str, ...] = ()
    remediation: Optional[Mapping[str, Any]] = None
    why_code_cannot: Optional[str] = None
    provider: Optional[str] = None
    crm_ref: Optional[str] = None
    notes: Optional[str] = None

    def statuses(self) -> Iterable[Tuple[str, str]]:
        """(profile, status) for each deployment profile."""
        return ((profile, self.status[profile]) for profile in PROFILES)

    def claims_to_work_anywhere(self) -> bool:
        return any(s in EVIDENCED_STATUSES for _p, s in self.statuses())

    def needs_remediation_anywhere(self) -> bool:
        return any(s in REMEDIABLE_STATUSES for _p, s in self.statuses())

    def practices(self, framework: str = "800-171") -> Tuple[str, ...]:
        prefix = f"{framework}:"
        return tuple(
            ref[len(prefix):] for ref in self.satisfies if ref.startswith(prefix)
        )


@dataclass(frozen=True)
class Crosswalk:
    framework: str
    revision: str
    total_practices: int
    families: Mapping[str, Mapping[str, Any]]
    practices: Mapping[str, str]


def load_crosswalk(path: pathlib.Path = CROSSWALK) -> Crosswalk:
    if not path.exists():
        raise CatalogError(f"crosswalk not found at {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    try:
        crosswalk = Crosswalk(
            framework=raw["framework"],
            revision=raw["revision"],
            total_practices=int(raw["total_practices"]),
            families=raw["families"],
            practices=raw["practices"],
        )
    except KeyError as exc:
        raise CatalogError(f"crosswalk is missing {exc}") from exc

    # The crosswalk is the denominator every other check measures against, so it has to be
    # self-consistent before anything is compared to it. A file that says 110 and lists 104
    # would silently shrink the population.
    if len(crosswalk.practices) != crosswalk.total_practices:
        raise CatalogError(
            f"crosswalk lists {len(crosswalk.practices)} practices and declares "
            f"{crosswalk.total_practices}"
        )
    declared = sum(int(f["count"]) for f in crosswalk.families.values())
    if declared != crosswalk.total_practices:
        raise CatalogError(
            f"family counts sum to {declared}, total_practices is "
            f"{crosswalk.total_practices}"
        )
    return crosswalk


def load_owners(path: pathlib.Path = OWNERS) -> Dict[str, Mapping[str, Any]]:
    if not path.exists():
        raise CatalogError(f"owners not found at {path}")
    return (yaml.safe_load(path.read_text()) or {}).get("owners", {})


def _validate(entry: Mapping[str, Any], source: str) -> Control:
    unknown = sorted(set(entry) - _ALLOWED_KEYS)
    if unknown:
        raise CatalogError(
            f"{source}: control {entry.get('id', '<no id>')} has unknown key(s) {unknown}. "
            f"A typo'd key is silently nothing, which turns an evidenced control into an "
            f"unevidenced one while still reading as complete."
        )
    missing = sorted(_REQUIRED_KEYS - set(entry))
    if missing:
        raise CatalogError(
            f"{source}: control {entry.get('id', '<no id>')} is missing {missing}"
        )

    status = entry["status"]
    if not isinstance(status, Mapping):
        raise CatalogError(
            f"{source}: {entry['id']} status must be a mapping of profile -> status, "
            f"not {type(status).__name__}. A single value cannot be true for "
            f"commercial cloud and an air-gapped enclave at once."
        )
    absent_profiles = sorted(set(PROFILES) - set(status))
    if absent_profiles:
        raise CatalogError(
            f"{source}: {entry['id']} does not state a status for {absent_profiles}. "
            f"An unnamed profile is an unanswered question, not a safe default."
        )
    unknown_profiles = sorted(set(status) - set(PROFILES))
    if unknown_profiles:
        raise CatalogError(f"{source}: {entry['id']} names unknown profile(s) {unknown_profiles}")
    bad = sorted({v for v in status.values() if v not in STATUSES})
    if bad:
        raise CatalogError(f"{source}: {entry['id']} has unknown status value(s) {bad}")

    control = Control(
        id=entry["id"],
        title=entry["title"],
        satisfies=tuple(entry["satisfies"]),
        status=dict(status),
        owner=entry["owner"],
        source_file=source,
        implemented_by=tuple(entry.get("implemented_by", ())),
        proved_by=tuple(entry.get("proved_by", ())),
        evidence=tuple(entry.get("evidence", ())),
        remediation=entry.get("remediation"),
        why_code_cannot=entry.get("why_code_cannot"),
        provider=entry.get("provider"),
        crm_ref=entry.get("crm_ref"),
        notes=entry.get("notes"),
    )

    # Obligations that follow from a status. Checked here rather than in a guard so that
    # every reader — renderer included — gets a catalogue that already holds them.
    for profile, value in control.statuses():
        if value == "organizational" and not control.why_code_cannot:
            raise CatalogError(
                f"{source}: {control.id} is organizational on {profile} and does not say "
                f"why code cannot satisfy it. Without that sentence the entry is "
                f"indistinguishable from an unfinished one."
            )
        if value == "inherited" and not (control.provider and control.crm_ref):
            raise CatalogError(
                f"{source}: {control.id} is inherited on {profile} and does not name both "
                f"a provider and a customer-responsibility reference"
            )
    return control


def load_controls(directory: pathlib.Path = CATALOG_DIR) -> List[Control]:
    """Every control across the family files, in file then document order."""
    if not directory.exists():
        raise CatalogError(f"catalogue directory not found at {directory}")

    controls: List[Control] = []
    seen: Dict[str, str] = {}
    for path in sorted(directory.glob("*.yaml")):
        if path.name in {"crosswalk.yaml", "owners.yaml"}:
            continue
        document = yaml.safe_load(path.read_text()) or {}
        for entry in document.get("controls", []) or []:
            control = _validate(entry, path.name)
            if control.id in seen:
                raise CatalogError(
                    f"{path.name}: control id {control.id} already defined in "
                    f"{seen[control.id]}"
                )
            seen[control.id] = path.name
            controls.append(control)
    return controls


def coverage(
    controls: Optional[Iterable[Control]] = None,
    crosswalk: Optional[Crosswalk] = None,
) -> Dict[str, List[str]]:
    """practice id -> the control ids claiming it. Practices with no claim map to []."""
    controls = list(controls if controls is not None else load_controls())
    crosswalk = crosswalk or load_crosswalk()
    result: Dict[str, List[str]] = {p: [] for p in crosswalk.practices}
    for control in controls:
        for practice in control.practices(crosswalk.framework):
            result.setdefault(practice, []).append(control.id)
    return result
