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
)


def _is_qualifier_name(name: str) -> bool:
    lowered = name.lower()
    return any(
        lowered == stem
        or lowered.endswith("_" + stem)
        or lowered.startswith(stem + "_")
        or ("_" + stem + "_") in lowered
        for stem in QUALIFIER_STEMS
    )


#: `"quality_measured": metrics.quality_measured` in a handler that returns a plain dict.
DICT_KEY = re.compile(r'"([a-z][a-z0-9_]*)"\s*:')


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
    api = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
    for path in sorted(api.glob("**/*.py")):
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
    if field not in SOURCE and _camel(field) not in SOURCE
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
