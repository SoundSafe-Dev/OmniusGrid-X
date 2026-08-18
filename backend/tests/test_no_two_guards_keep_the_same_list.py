"""No two guards keep private copies of the same subject list (FS-590).

THE CARRY-ACROSS. FS-492 found a sweep reading a private copy of the shared route list, and
the fix was to make it read the shared one. This applies that question to **the guards
themselves**: 86 module-level string collections live in `tests/`, and any two describing the
same fact will drift, because nothing compares them.

WHAT IT FOUND, AND THE FIRST ONE WAS MINE.

* **`ENGINES` vs `EXPECTED_DORMANT`** — `test_engine_status_says_whether_it_is_running.py`
  listed the four dormant engines, and `test_service_lifecycle_is_declared.py` had already
  declared exactly that set with better reasons, including the one that matters:
  `cloud_gateway` holds a 10,000-entry in-memory queue drained only by the `_flush_loop` its
  own `start()` launches. I wrote the duplicate hours before this sweep found it.

* **`OTHER_LANES` vs `_OTHER_LANES`** — two sweeps' idea of which routers belong to another
  dev. **They had already diverged**: one exempted `rag` and the other did not, silently, with
  neither file able to see it. Benign as a subset, and the next edit to either would have
  widened it.

* **`PUBLIC_PROBES` ⊂ `PUBLIC_REQUIRED_EXACT`** — checked and left alone. These answer
  different questions ("must not disclose" vs "must be reachable unauthenticated") and the
  subset relation between them is coherent rather than accidental. Recorded because *proven
  clean* and *never checked* look identical afterwards.

THE COST OF THE FIX, WHICH IS REAL. Deriving a list from another file removes the divergence
and hands the source control of the consumer's population. When a mutation test dropped
`cloud_gateway` from `EXPECTED_DORMANT`, the engine-status suite went from 16 tests to 14 **and
reported success** — it had silently stopped checking the one engine whose dormancy costs
something. Sharing a list is right; sharing it without asserting what you got back is how a
guard narrows to nothing one entry at a time. Both consumers now assert their population.
"""

from __future__ import annotations

import ast
import itertools
import pathlib
from typing import Dict, Set

import pytest

TESTS = pathlib.Path(__file__).resolve().parent

#: How many members two collections must share before they are treated as the same subject.
#: Three is low enough to catch a real duplicate and high enough that two unrelated lists
#: naming `/health` and `/metrics` do not collide.
OVERLAP_THRESHOLD = 3

#: Pairs that overlap and are NOT duplicates, with why. An entry is a claim somebody
#: compared them and found the overlap meaningful rather than accidental.
DIFFERENT_QUESTIONS: Dict[frozenset, str] = {
    frozenset({
        "test_edge_ingest_quarantine_retention.py::GOOD",
        "test_the_uplink_framing_survives_a_mixed_fleet.py::READING",
    }): (
        "Neither is a list of things being guarded. Both are a single well-formed uplink "
        "message written as a dict literal, and the four 'shared members' this sweep found "
        "are the field NAMES of the telemetry envelope — `asset_id`, `timestamp_edge`, "
        "`payload`, `sequence_num` — which any valid message must carry. The detector is "
        "keying on dict keys, and for a sample message the keys are the schema rather than "
        "an inventory somebody curated. GOOD exists to be contrasted with MALFORMED by the "
        "quarantine gateway, which never sees bytes; READING exists to be serialised, "
        "framed, compressed and decoded, and its shape matters only in that it is realistic "
        "enough for the 5x shrink assertion to mean something. Deriving either from the "
        "other would couple a framing test to a quarantine fixture so that changing one "
        "test's sample breaks an unrelated one — the opposite of what this register is for "
        "(FS-759)."
    ),
    frozenset({
        "test_correlation_routes_serialize_their_models.py::ROUTES",
        "test_route_auth_walk.py::AUTHENTICATED_OPERATIONAL_MUTATIONS",
    }): (
        "Three correlation routes appear in both, and the lists cannot be derived from "
        "each other in either direction. The auth register is an inventory: EVERY mutating "
        "route in the app, carrying no request bodies, and it must stay complete or a new "
        "mutation slips in unreviewed. ROUTES is a chosen sample that each carries a valid "
        "REQUEST BODY, and half of it is GETs — which the auth register can never contain. "
        "Deriving the sample from the inventory would give the serialisation smoke a set of "
        "paths it has no way to call; deriving the inventory from the sample would let an "
        "unreviewed mutation land the moment somebody declined to write a body for it. The "
        "overlap is three routes that happen to be both mutating and cheap to call."
    ),
    frozenset({
        "test_a_tenant_reference_is_refused_realdb.py::CROSS_TENANT_WRITES",
        "test_what_can_be_created_can_be_corrected.py::PAIRS",
    }): (
        "Both name driver, shipment and trailer, and neither could be derived from the "
        "other. PAIRS is a SCHEMA comparison — for every Create/Update pair in the tree, is "
        "there a field settable once and never correctable — and its members are model "
        "classes, with no route, method or field among them. CROSS_TENANT_WRITES is a list "
        "of HTTP calls: a verb, a path template, one field, and which seeded row it must "
        "not reach. The three shared words are entity names, and the entity is the only "
        "thing the two have in common: PAIRS would gain nothing from knowing a path, and "
        "the tenancy walk covers `dock_door` and `carrier` targets that have no "
        "Create/Update pair to compare. Derived either way, one of them would shrink to the "
        "other's population and stop asking its own question (FS-737)."
    ),
    frozenset({
        "test_no_unapproved_primitive_is_reachable.py::ROOTS",
        "test_every_alert_watches_a_series_something_exports.py::CODE_ROOTS",
    }): (
        "Both name source trees to walk, and the overlap is path components rather than "
        "subject matter — one sweeps for exported metric series, the other for "
        "cryptographic primitives. Critically the POPULATIONS differ: the crypto guard "
        "walks only `backend/app` and `edge-agent/opsgrid_agent`, because an unapproved "
        "primitive in a test fixture or a script is not a shipped one, while the metrics "
        "guard must read everything that could export a series. Deriving either from the "
        "other would silently widen or narrow a security sweep to suit a monitoring one."
    ),
    frozenset({
        "test_no_unapproved_primitive_is_reachable.py::ROOTS",
        "test_the_session_arc_is_a_real_range.py::SEARCH_ROOTS",
    }): (
        "Same reasoning as the pair above: shared path components, unrelated questions. "
        "The session-arc guard searches documentation ranges; this one asks which "
        "algorithms application code can reach."
    ),
    frozenset({
        "test_every_alert_watches_a_series_something_exports.py::CODE_ROOTS",
        "test_the_session_arc_is_a_real_range.py::SEARCH_ROOTS",
    }): (
        "Both enumerate the repo's code roots, because both sweeps must read the whole "
        "tree — one collects exported metric series, the other verifies documentation "
        "ranges. The overlap is path components, not subject matter: neither list could "
        "be derived from the other without coupling a metrics guard to a docs guard."
    ),
    frozenset({
        "test_service_lifecycle_is_declared.py::EXPECTED_STARTED",
        "test_a_started_service_is_a_service_somebody_watches.py::UNWATCHED",
    }): (
        "Different questions about the same services, and NEITHER is a copy of the other. "
        "EXPECTED_STARTED declares which services boot is expected to start, and fails when "
        "that drifts. UNWATCHED asks which of the services boot ACTUALLY starts are named in "
        "no health check, and carries per-service reasons — what would have to be true to "
        "drop the entry — which the first list has no place for. Critically, the second does "
        "not read the first: it parses `main.py` for `await <name>.start()` directly, so a "
        "service added to boot appears in its denominator whether or not anybody updated a "
        "declaration. The overlap is 7 of 8 because 7 of the 8 started services are "
        "unwatched, which is the finding rather than a duplication (FS-693)."
    ),
    frozenset({
        "test_public_probes_do_not_disclose.py::PUBLIC_PROBES",
        "test_route_auth_walk.py::PUBLIC_REQUIRED_EXACT",
    }): (
        "Different questions about the same routes. PUBLIC_PROBES asks what a probe must "
        "not leak; PUBLIC_REQUIRED_EXACT asks what must answer without a token. The first "
        "is a strict subset of the second, which is coherent — a probe that must not "
        "disclose is necessarily reachable — and NOT a copy: the second also carries the "
        "auth endpoints and /metrics, which are not probes."
    ),
    frozenset({
        "test_route_auth_walk.py::PUBLIC_REQUIRED_EXACT",
        "test_route_auth_walk.py::CREDENTIAL_MUTATIONS",
    }): "Same file, adjacent concerns: what is public, and which public routes take credentials.",
    frozenset({
        "test_route_auth_walk.py::ADMIN_ROUTE_INVENTORY",
        "test_route_auth_walk.py::ADMIN_UI_BACKED_ROUTES",
    }): "Same file: every admin route, and the subset a UI actually calls.",
    frozenset({
        "test_service_lifecycle_is_declared.py::EXPECTED_DORMANT",
        "test_service_lifecycle_is_declared.py::CLOUD_GATEWAY_PRODUCERS",
    }): (
        "Same file, and the overlap is the finding: the producers that queue into "
        "cloud_gateway are themselves dormant, which is why a dormant gateway costs "
        "nothing today. Merging them would delete that argument."
    ),
    frozenset({
        "test_provenance_flags_are_always_set.py::PROVENANCE_FIELDS",
        "test_qualifiers_reach_the_frontend.py::QUALIFIER_STEMS",
    }): (
        "Fields versus word stems. One names response keys a producer must set; the other "
        "names substrings a frontend sweep looks for. They overlap because a qualifier is "
        "often spelled like its field, and neither can be derived from the other."
    ),
    frozenset({
        "test_route_auth_walk.py::AUTHENTICATED_OPERATIONAL_MUTATIONS",
        "test_write_endpoints_reject_cleanly_realdb.py::SKIP_EXACT",
    }): (
        "A route can be both operationally significant and unsafe for a walk to call. The "
        "overlap is the edge ingest surface, and the two lists exist for opposite reasons."
    ),
    frozenset({
        "test_fleet_logistics_tenant_isolation_realdb.py::LISTS",
        "test_route_auth_walk.py::AUTHENTICATED_OPERATIONAL_MUTATIONS",
    }): "List endpoints that are also operational mutations elsewhere; different verbs.",
    frozenset({
        "test_engine_status_says_whether_it_is_running.py::ENGINES",
        "test_service_lifecycle_is_declared.py::CLOUD_GATEWAY_PRODUCERS",
    }): (
        "ENGINES is now DERIVED from EXPECTED_DORMANT in the same file as "
        "CLOUD_GATEWAY_PRODUCERS, so this overlap is the derivation showing through rather "
        "than a copy."
    ),
    frozenset({
        "test_engine_status_says_whether_it_is_running.py::ENGINES",
        "test_service_lifecycle_is_declared.py::EXPECTED_DORMANT",
    }): (
        "Resolved: ENGINES is derived from EXPECTED_DORMANT. The overlap is total by "
        "construction, which is the fix rather than the defect."
    ),
    frozenset({
        "test_engine_status_says_whether_it_is_running.py::_INSTANCES",
        "test_service_lifecycle_is_declared.py::EXPECTED_DORMANT",
    }): (
        "`_INSTANCES` is the literal half of the derivation — it maps a name to the "
        "singleton object, which EXPECTED_DORMANT cannot hold. `ENGINES` is the "
        "intersection, and a test asserts the two match so the derived set cannot shrink "
        "silently."
    ),
    frozenset({
        "test_engine_status_says_whether_it_is_running.py::_INSTANCES",
        "test_service_lifecycle_is_declared.py::CLOUD_GATEWAY_PRODUCERS",
    }): "Same derivation showing through; see the entry above.",

    # --- FOUND AND LEFT, with what was found ------------------------------------------
    frozenset({
        "test_declared_media_types_are_honest.py::DYNAMIC",
        "test_declared_media_types_match_what_is_returned.py::_EMITTERS",
    }): (
        "TWO MEDIA-TYPE GUARDS, TWO LISTS OF RESPONSE CLASSES, AND THEY DIFFER — each is "
        "missing entries the other has. `DYNAMIC` carries `RedirectResponse`; `_EMITTERS` "
        "carries `PlainTextResponse`, `HTMLResponse` and two `_secure_*` helpers. They are "
        "not quite the same question — one asks which classes make a content type "
        "unknowable statically, the other which call sites emit a response at all — but "
        "`PlainTextResponse` and `HTMLResponse` set their own content type and are absent "
        "from the first, which looks like a gap rather than a distinction. "
        "NOT MERGED HERE. Both files belong to a media-type sweep I have not read in full, "
        "and merging two lists on a resemblance is how a guard quietly widens or narrows. "
        "Recorded so the next person to touch either one sees the other."
    ),
}


def _collections() -> Dict[str, Set[str]]:
    """Module-level upper-case constants in `tests/`, by their literal string members.

    Only literals. A collection built from a comprehension or an import is already derived
    from something, which is the state this file is trying to reach.
    """
    found: Dict[str, Set[str]] = {}
    for path in sorted(TESTS.glob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in tree.body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, ast.AnnAssign) else []
            )
            name = next(
                (t.id for t in targets if isinstance(t, ast.Name) and t.id.isupper()), None
            )
            if not name or node.value is None:
                continue
            # A `Path` expression is not a subject list. `WORKFLOW = REPO / ".github" /
            # "workflows" / "quality-gates.yml"` shares three "members" with any other
            # constant pointing at the same file — two guards reading the same workflow is
            # correct, and reporting it as a duplicated list is noise of exactly the kind
            # that stops a sweep being read.
            if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Div):
                continue
            members = {
                child.value
                for child in ast.walk(node.value)
                if isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and len(child.value) > 6
                and " " not in child.value
            }
            if len(members) >= OVERLAP_THRESHOLD:
                found[f"{path.name}::{name}"] = members
    return found


def _overlapping_pairs() -> list[tuple[frozenset, int]]:
    collections = _collections()
    pairs = []
    for a, b in itertools.combinations(sorted(collections), 2):
        shared = collections[a] & collections[b]
        if len(shared) >= OVERLAP_THRESHOLD:
            pairs.append((frozenset({a, b}), len(shared)))
    return pairs


class TestTheSweepHasSubjects:
    def test_it_finds_the_collections(self):
        """Vacuity. A parse returning nothing passes this file over an empty set while every
        duplicated list in the suite drifts — which is the failure it exists to prevent,
        applied to itself."""
        assert len(_collections()) > 40, (
            f"only {len(_collections())} module-level collections found in tests/; the AST "
            f"walk is broken, not the suite"
        )

    def test_it_would_notice_a_duplicate(self):
        """A positive control. If the overlap comparison stopped working, this file would
        report zero pairs and read as a clean suite."""
        assert _overlapping_pairs(), (
            "no overlapping pairs at all — including the ones recorded below as different "
            "questions. The comparison is broken."
        )


class TestNoUnexaminedDuplicate:
    def test_every_overlapping_pair_has_been_compared(self):
        unexamined = sorted(
            f"{sorted(pair)[0]}  ~  {sorted(pair)[1]}  ({count} shared)"
            for pair, count in _overlapping_pairs()
            if pair not in DIFFERENT_QUESTIONS
        )
        assert not unexamined, (
            "these two guards each keep a private list naming the same things. Nothing "
            "compares them, so they drift — `OTHER_LANES` and `_OTHER_LANES` had already "
            "diverged by one entry before anyone looked, and the engine list was a copy of "
            "a declaration that already existed with better reasons.\n\n  "
            + "\n  ".join(unexamined)
            + "\n\nDerive one from the other, or record here why the overlap is two "
            "different questions rather than one fact written twice."
        )

    @pytest.mark.parametrize("pair", sorted(DIFFERENT_QUESTIONS, key=sorted))
    def test_each_recorded_pair_still_overlaps(self, pair: frozenset):
        """A stale entry excuses a comparison nobody is making any more."""
        overlapping = {p for p, _ in _overlapping_pairs()}
        collections = _collections()
        if not all(name in collections for name in pair):
            return  # one side was renamed or removed; nothing to excuse
        assert pair in overlapping, (
            f"{sorted(pair)} no longer overlap; delete the entry"
        )
