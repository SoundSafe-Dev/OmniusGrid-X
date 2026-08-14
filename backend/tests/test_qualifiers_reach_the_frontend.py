"""A qualifier the backend sends must be read by the frontend.

A *qualifier* is a boolean whose whole job is to say how far to trust the value beside
it — `quality_measured`, `simulated`, `availability_only`, `truncated`. Sending one and
ignoring it is worse than never sending it, because the backend author then believes the
caveat is being shown. Every consequence lands on the reader, who sees a confident number
with its footnote removed.

THIS CLASS HAS BITTEN TWICE, both times found by hand:

  * `SessionChatResponse.simulated` — the correlation chat's error fallback returns a
    reply that is not an analysis at all. The server said so; `analysisSessions.ts` did
    not declare the field, so the client dropped the sentence and rendered a confident
    answer.
  * `quality_measured` / `performance_measured` — `quality` reads 1.0 for an asset with
    no part counters, which is the neutral multiplier for OEE and NOT a measurement. The
    endpoint has flagged this since FS-234, with a comment saying a consumer "should
    render '—' rather than '100%'". `OEEMetrics` did not carry the fields, so every
    uninstrumented asset displayed flawless quality.

WHY BOOLEAN IS THE RULE. The first version of this sweep keyed on name stems alone and
matched `estimated_duration_hours`, `estimated_seconds` and `total_estimated_cost` —
business QUANTITIES, none of them a statement about trust. `estimated_X` names a number;
the qualifier form is a flag. Typing the rule on `boolean` removes that whole family
without an allowlist, which is the better fix: an allowlist of false positives is a list
of checks that no longer run.

COMMENTS ARE STRIPPED, and that was not a refinement — it decided the result. The first
version matched raw source, and `simulated` looked read because `fleetTracker.ts` carries
the comment "Mock vehicle positions (simulated GeoTab data)". An unrelated English
sentence about a different feature was standing in for a field nobody consumed, and the
mutation check proved it: against the real pre-fix frontend the sweep flagged the OEE pair
and MISSED the correlation flag. A guard that a passing comment can satisfy is a guard
whose result depends on prose.

WHAT THIS STILL CANNOT PROVE. That the frontend *displays* the qualifier, only that its
code names it. Parsing TSX to find rendered output would mismodel enough to manufacture
defects, so the display half is pinned per-instance instead — by
`test_provenance_flags_are_always_set.py` and the OEE page tests.
"""

from __future__ import annotations

import pathlib
import re
from typing import Dict, List, Set, Tuple

import pytest

from app.main import app

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"

#: Word stems that mark a field as a statement about trust rather than a measurement.
QUALIFIER_STEMS = (
    "measured",
    "simulated",
    "approximate",
    "partial",
    "degraded",
    "stale",
    "cached",
    "truncated",
    "capped",
    "fallback",
    "mock",
    "only",
    "incomplete",
    "unavailable",
    "sampled",
    "inferred",
    # Added with the verdict-from-emptiness work. These say a judgement WAS or was not
    # made — `drivers_assessed`, `detention_assessed`, `assessable`, `graded` — which is
    # the same job as `quality_measured`: telling the reader how far the number beside it
    # can be trusted. Naming them without adding them here would have left the newest
    # qualifiers outside the sweep written to catch exactly this.
    "assessed",
    "assessable",
    "graded",
)


def _is_qualifier_name(name: str) -> bool:
    """A flag ENDS with its stem: `availability_only`, `quality_measured`,
    `drivers_assessed`, `graded`.

    Matching the stem anywhere in the name pulled in `context_only_sections` and
    `context_only_tabs` — both LISTS of sections, named for what they contain rather than
    for how far to trust them. The schema half of this sweep filters on `boolean` and
    never had the problem; a raw dict key carries no type, so the shape of the NAME is
    the only signal available, and a trust flag puts its stem last.
    """
    lowered = name.lower()
    return any(lowered == stem or lowered.endswith("_" + stem) for stem in QUALIFIER_STEMS)


#: `"quality_measured": metrics.quality_measured` in a handler that returns a plain dict.
#: BOTH QUOTE STYLES. Matching only double quotes missed every payload in
#: `transportation_management.py`, which uses single throughout — including
#: `drivers_assessed`, added by the same work that extended this sweep. A detector that
#: knows one of two equally common spellings under-reports by construction.
DICT_KEY = re.compile(r'''["']([a-z][a-z0-9_]*)["']\s*:''')


def _qualifier_fields() -> Dict[str, Set[str]]:
    """field name -> where it is declared.

    TWO SOURCES, because the schemas alone are not the wire. Roughly half of these
    endpoints return a plain dict with no `response_model`, so nothing about them
    reaches `components.schemas` — `/dashboard/assets/{id}/oee` is one, and it is where
    `quality_measured` lives. Reading only the schemas made this sweep look clean while
    missing the very defect it was written for; the vacuity check below is what caught
    that, and it is why the check exists.

    The `boolean` filter applies only to the schema half — a raw dict key carries no
    type. That is safe because the stems are all flag-shaped: the quantity family that
    forced the type rule was `estimated_*`, and `estimated` is deliberately not a stem.
    """
    found: Dict[str, Set[str]] = {}
    app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
    # api AND services: a response payload is just as often assembled in a service and
    # returned verbatim by a thin handler. Scanning only `app/api` kept
    # `drivers_assessed` and `detention_assessed` out of view — both introduced by the
    # verdict-from-emptiness work, both exactly what this file exists to check.
    sources = sorted(app_root.glob("api/**/*.py")) + sorted(app_root.glob("services/**/*.py"))
    for path in sources:
        for match in DICT_KEY.finditer(path.read_text()):
            if _is_qualifier_name(match.group(1)):
                found.setdefault(match.group(1), set()).add(f"{path.name} (raw dict)")
    for schema_name, schema in app.openapi().get("components", {}).get("schemas", {}).items():  # noqa: E501
        for field, spec in (schema.get("properties") or {}).items():
            if not _is_qualifier_name(field):
                continue
            # `anyOf` covers Optional[bool].
            types = {spec.get("type")} | {
                option.get("type") for option in spec.get("anyOf", [])
            }
            if "boolean" in types:
                found.setdefault(field, set()).add(schema_name)
    return found


#: `//` to end of line, and `/* … */`. Applied before matching so that prose about an
#: unrelated feature cannot stand in for code that reads the field.
COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


#: A qualifier is exempt only while the FIELD IT QUALIFIES is itself unread. That is the
#: honest reason: `graded` tells a caller whether `efficiency_grade` means anything, and
#: no screen renders the grade, so nothing is being dropped — there is no caveat to lose
#: because there is no claim being made.
#:
#: Each entry names that field, and `TestTheExemptionsStayHonest` asserts it is still
#: unread. The moment somebody renders the verdict, the exemption fails and the qualifier
#: has to be wired with it. An allowlist that cannot expire is how a real finding gets
#: parked forever.
QUALIFIES_AN_UNREAD_FIELD: Dict[str, str] = {
    "graded": "efficiency_grade",
    "drivers_assessed": "overall_compliant",
    # "assessable": "is_compliant" — REMOVED 2026-08-02 (FS-395). The exemption claimed
    # `is_compliant` was not rendered either; `getDriverHOS` now declares BOTH on `DriverHOS`,
    # so the claim stopped being true and this guard said so. `assessable` is carried on the
    # client type, which is what the exemption existed to defer — the caveat travels with the
    # verdict now, and the main sweep below checks it stays that way.
    # "detention_assessed": "detention_charge" — REMOVED 2026-08-04 (FS-426). The exemption
    # claimed `detention_charge` was not rendered; `DriverWaitTime` now declares it, so the
    # claim stopped being true and this guard failed on the commit that made it so. The
    # server publishes the flag from `DriverWaitTimeResponse` too, computed exactly as the
    # dwell-times path computes it, and the client carries it — so the caveat travels with
    # the number on both endpoints that report it. Same shape as the `assessable` release
    # above, two days later.
    "appointments_assessed": "sync_status_breakdown",
    # Intake lane's scenario builder; its output is not rendered by any page today.
    "degraded": "scenario_confidence",
    # Same route, same reason, arriving with the correlation-engine merge:
    # `POST /nlp/intake/cross-correlate` has NO frontend caller at all, so the samples the
    # flag bounds are not on any screen. Declaring a client type for an endpoint nothing
    # calls is the "declared and never produced" defect this repository sweeps for, written
    # by the person sweeping — so the flag waits for the feature. The four qualifiers that
    # arrived WITH a rendered surface (`groups_truncated`, `rollups_truncated`, `sampled`,
    # `input_truncated`) were wired instead, onto `EvidenceEntityRollups` and
    # `OperationalAnalyticsResult`, and IntakeInbox renders the caveat.
    "scenario_sampled": "scenario_samples",
    # "assets_unavailable": "avg_oee" — REMOVED 2026-08-14 (page-enhancement arc). The
    # exemption read: "/oee/dashboard/summary has NO frontend consumer at all … the
    # moment anything renders the aggregate, this fails and has to be wired with it."
    # The Dashboard's new Fleet OEE tile renders `avgOee`, and this guard failed on the
    # commit that made it so — third time an exemption here has expired exactly as its
    # own comment predicted (`assessable`, `detention_assessed`, now this).
    #
    # The caveat travels with the verdict: the tile's tooltip reads "N of M assets
    # measured" and names `assetsUnavailable` when any asset could not be read, so an
    # operator sees a fleet OEE computed over eight of ten machines as exactly that.
    # The main sweep below now checks it stays that way.
}


def _frontend_source() -> str:
    text: List[str] = []
    for pattern in ("**/*.ts", "**/*.tsx"):
        for path in FRONTEND.glob(pattern):
            if ".test." in path.name:
                continue
            text.append(COMMENT.sub(" ", path.read_text()))
    return "\n".join(text)


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(word.title() for word in tail)


QUALIFIERS = _qualifier_fields()
SOURCE = _frontend_source()
UNREAD: List[Tuple[str, List[str]]] = sorted(
    (field, sorted(schemas))
    for field, schemas in QUALIFIERS.items()
    if field not in SOURCE
    and _camel(field) not in SOURCE
    and field not in QUALIFIES_AN_UNREAD_FIELD
)


class TestTheSweepIsNotVacuous:
    def test_it_discovers_qualifiers(self):
        assert len(QUALIFIERS) >= 3, (
            f"only {len(QUALIFIERS)} qualifier fields found on the wire; the sweep is "
            f"not reaching the schemas and would pass while checking nothing"
        )

    def test_the_two_known_instances_are_in_scope(self):
        """Both defects this class exists for must be inside what it examines,
        otherwise a green run says nothing about either."""
        assert "simulated" in QUALIFIERS, "the correlation chat flag is not being swept"
        assert "quality_measured" in QUALIFIERS, "the OEE flags are not being swept"

    def test_the_frontend_source_was_actually_loaded(self):
        assert len(SOURCE) > 100_000, (
            f"only {len(SOURCE)} characters of frontend source read; every field would "
            f"look unread and the failure message would be nonsense"
        )

    def test_comments_are_stripped(self):
        """The strip is load-bearing: an unrelated comment in `fleetTracker.ts` about
        "simulated GeoTab data" made a field nobody consumed look consumed."""
        assert "simulated GeoTab data" not in SOURCE, (
            "comments are reaching the match; prose about one feature can satisfy the "
            "check for another"
        )
        assert "simulated?: boolean" in SOURCE, (
            "the strip removed code as well as comments"
        )

    def test_a_quantity_is_not_mistaken_for_a_qualifier(self):
        """`estimated_duration_hours` is a number, not a statement about trust. Keying
        on name stems alone matched three such fields; requiring `boolean` is what
        removed them, and this pins that it still does."""
        assert "estimated_duration_hours" not in QUALIFIERS
        assert "total_estimated_cost" not in QUALIFIERS

    def test_the_name_rule_can_reject(self):
        assert _is_qualifier_name("quality_measured")
        assert _is_qualifier_name("availability_only")
        assert not _is_qualifier_name("organization_id")


class TestEveryQualifierIsReadByTheFrontend:
    def test_none_are_dropped_at_the_client_boundary(self):
        assert not UNREAD, (
            "These booleans exist to tell the caller how far to trust the value beside "
            "them, and no frontend file mentions them — so the number is rendered "
            "without its caveat while the backend believes the caveat is shown. Declare "
            "the field on the TypeScript type and render it, or drop it server-side:\n  "
            + "\n  ".join(f"{field} (from {', '.join(schemas)})" for field, schemas in UNREAD)
        )


class TestTheExemptionsStayHonest:
    """An exemption here is a claim: "the field this qualifies is not rendered either".

    Claims rot. These assertions make each one re-prove itself on every run, so the list
    cannot quietly become a place where findings go to be forgotten.
    """

    def test_each_exemption_names_the_field_it_qualifies(self):
        for qualifier, qualified in QUALIFIES_AN_UNREAD_FIELD.items():
            assert qualified and qualified != qualifier, (
                f"{qualifier} is exempted without naming what it qualifies"
            )

    def test_the_qualified_field_is_still_unread(self):
        """The exemption expires by itself. If a page starts rendering
        `efficiency_grade`, `graded` stops being optional and this fails."""
        now_read = [
            f"{q} (qualifies {field}, which the frontend now reads)"
            for q, field in QUALIFIES_AN_UNREAD_FIELD.items()
            if field in SOURCE or _camel(field) in SOURCE
        ]
        assert not now_read, (
            "these qualifiers were exempted because the field they qualify was not "
            "rendered; it is now, so the caveat has to be wired too:\n  "
            + "\n  ".join(now_read)
        )

    def test_every_exemption_is_still_a_qualifier_on_the_wire(self):
        """An entry for a field the backend no longer emits is dead weight."""
        stale = [q for q in QUALIFIES_AN_UNREAD_FIELD if q not in QUALIFIERS]
        assert not stale, f"exempted but no longer emitted: {stale}"
