"""A body field the schema declares and the handler never reads (FS-663).

THE CLASS. `POST /yard/checkpoints` declared `inspector_id` and `metadata`, returned them, had
columns for both, and passed neither to the service — accepted, discarded, echoed back as the
default. Three more turned up the same day, and the last one was not merely lossy:

    get_carrier_compliance:  is_valid = certified AND expires_at AND expires_at > now

`POST /carriers` passed `ctpat_certified` and dropped `ctpat_expires_at`, so every carrier
created through the API reported its certification **invalid**. A wrong answer computed from
the dropped field, with a 200 on the way in.

TWO TIERS, because the severities are not comparable.

**Absolute** — no route may pass a boolean and drop the field that bounds it (rule 143). A
certification with no expiry, a seal with no status, an inspection with no inspector: each is
a positive claim that cannot be checked, and each is the more reassuring of the two possible
readings. This set is empty and may not gain a member.

**Ratcheted** — the general case, where a declared field never reaches the service. Nine routes
carry one, most in other lanes, and several are lifecycle fields wrongly declared on a Create
schema rather than data loss. Recording them separates a decision from an oversight without
demanding work from lanes that did not ask for it; the register only shrinks.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
API_DIR = REPO / "backend" / "app" / "api"
MODEL_DIR = REPO / "backend" / "app" / "models"

#: The file is SPLIT on the decorator rather than matched across it. A single regex spanning
#: decorator-to-next-decorator needs a bounded body window, and a handler longer than that
#: window fails to match — taking the FOLLOWING decorator with it, because `finditer` resumes
#: past the failed attempt. That silently hid nine of yard's twelve routes, including the one
#: this guard uses as its control, and the sweep still looked plausible.
ROUTE_HEAD = re.compile(
    r'^@router\.(post|put|patch)\("([^"]*)"', re.M
)
BODY_PARAM = re.compile(r"\b(\w+)\s*:\s*(\w+(?:Create|Update|Request|Input|In))\b")

#: Field-name shapes that QUALIFY a boolean: when does it lapse, who did it, what state is it
#: in. Deliberately narrow — a wide pattern would drag in every id on every schema and the
#: absolute tier below would become a second ratchet.
QUALIFIER = re.compile(r"(_expires_at|_at$|_by$|_status$|_id$|_reason$|_note)")

#: Routes with a declared field the handler never reads, and why each is tolerated.
#: **Only ever shrinks.** Measured 2026-08-12.
UNREAD: dict[str, list[str]] = {
    "kanban:POST /rules": ["organization_id"],
    "logistics_correlation:POST /load-quality": [
        "claim_amount", "claim_filed", "manufacturing_correlation_score", "metadata",
        "resolved_at", "root_cause_asset", "root_cause_operation", "trailer_id",
    ],
    "transportation:POST /shipments": [
        "actual_delivery", "actual_pickup", "metadata", "priority", "route_id", "status",
        "temperature_max", "temperature_min",
    ],
    #: WIRING-SIDE, and the strongest remaining case. `total_distance_miles` is read by
    #: `transportation_management.py:939` and `estimated_duration_hours` by `:356` — real
    #: creation input with readers that depend on it, the carrier's shape. Next after the
    #: driver fix, and left here rather than done in the same pass because it needs its own
    #: look at whether a route's distance is operator-supplied or derived from its stops.
    "transportation:POST /routes": [
        "estimated_duration_hours", "fuel_cost_estimate", "is_active", "toll_cost_estimate",
        "total_distance_miles",
    ],
    "transportation:POST /load-plans": [
        "executed_at", "is_executed", "metadata", "temperature_zones",
    ],
    "transportation:POST /freight-charges": [
        "approved_at", "approved_by", "billed_at", "currency", "invoice_number", "is_billed",
        "metadata",
    ],
    "yard:POST /dock/appointments": [
        "actual_end", "actual_start", "compliance_required", "driver_id", "metadata", "status",
    ],
    "yard:POST /moves": ["duration_seconds", "metadata"],
    #: SCHEMA-SIDE, and confirmed by reading the reader — the opposite conclusion to the
    #: carrier and the driver, from the same question.
    #:
    #: `total_wait_minutes`, `detention_minutes`, `detention_charge`, `demurrage_minutes` and
    #: `demurrage_charge` are all COMPUTED by `close_driver_wait_time` at checkout from the
    #: two timestamps and the two rates. `check_out_at`, `docked_at` and `unloaded_at` are
    #: lifecycle stamps set as they happen. None of them is creation input.
    #:
    #: So dropping them is right, and honouring them would be worse than the defect: an
    #: operator could post their own `detention_charge` on create and the system would bill
    #: it. The fix here is to take them OFF `DriverWaitTimeCreate`, which is a contract change
    #: with clients to check — not to wire them through.
    "yard:POST /driver-wait-times": [
        "check_out_at", "demurrage_charge", "demurrage_minutes", "detention_charge",
        "detention_minutes", "docked_at", "is_billed", "metadata", "total_wait_minutes",
        "unloaded_at",
    ],

    # --- DELIBERATE: the handler is right to ignore these ---------------------------------
    #: `status` on a check-in is the one declared field this route SHOULD drop. The service
    #: sets 'checked_in'; honouring a caller's status would let somebody check a trailer
    #: straight to 'checked_out' without it ever entering the yard. The SCHEMA is wrong here,
    #: not the handler — the same shape `organization_id` carries on every Create model.
    "yard:POST /trailers/checkin": ["status"],
    "kanban:POST /tasks": ["status"],

    # --- other lanes ---------------------------------------------------------------------
    "analysis_sessions:POST /{session_id}/correlate": ["auto_integrate"],
    "nlp_correlation:POST /intake/cross-correlate": ["auto_integrate"],

    #: `transportation:POST /drivers` WAS HERE and is fixed (FS-664). Kept as a note rather
    #: than an entry, because what it cost is the argument for this register existing.
    #:
    #: It dropped four DOT-regulated HOS figures. `check_compliance` reports "cannot be
    #: assessed" when any is None and `dispatch_shipment` refuses on that verdict, so every
    #: driver created through the API was permanently undispatchable. Two of the four
    #: (`hos_cycle_hours`, `current_hos_status`) have NO writer anywhere but the demo seeder —
    #: which is why the seeded fleet dispatches and a real one would not.
    #:
    #: It sat in this register for one pass with the reason "HOS has a second writer, the ELD
    #: sync, and which one wins on create is a decision". That was wrong: create sets what the
    #: operator knows, the webhook overwrites it when the ELD reports, and there is no race.
    #: A register entry is a place to put a decision, not a place to put a doubt — the doubt
    #: took ten minutes to resolve once somebody looked at the writers.
}

#: Why the register has members, recorded once rather than nine times. The two kinds are worth
#: telling apart because the fix differs:
#:
#:   * LIFECYCLE STATE on a Create schema — `approved_at`, `billed_at`, `is_executed`,
#:     `actual_start`. The handler is right to ignore them; the SCHEMA is wrong, and an API
#:     that accepts values it will never honour is its own small lie. Fixing means removing
#:     them from the Create model, which is a contract change with clients to check.
#:   * GENUINE CREATION INPUT being lost — `temperature_min`/`max` on a shipment,
#:     `duration_seconds` on a yard move. That is data loss and the fix is wiring.
#:
#: Four of the nine are in Harsh's lane (kanban, logistics_correlation). The rest are recorded
#: rather than fixed in one pass because each needs its own decision about which kind it is.
REGISTER_REASON = "see the module docstring and the note above"


def _schemas() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    fields: dict[str, list[str]] = {}
    bases: dict[str, list[str]] = {}
    for path in list(MODEL_DIR.glob("*.py")) + list(API_DIR.glob("*.py")):
        for m in re.finditer(
            r"^class (\w+)\(([\w., \[\]]*)\):\n((?:    .*\n|\n)*)", path.read_text(), re.M
        ):
            name, base, body = m.groups()
            fields[name] = [
                fm.group(1)
                for fm in re.finditer(r"^    (\w+)\s*:\s*([^=\n]+)", body, re.M)
                if fm.group(1) != "model_config"
            ]
            bases[name] = [b.strip() for b in base.split(",")]
    return fields, bases


def _declared(name: str, fields, bases, seen=()) -> list[str]:
    if name in seen or name not in fields:
        return []
    out = list(fields[name])
    for base in bases.get(name, []):
        out += _declared(base, fields, bases, seen + (name,))
    return out


def _annotations(name: str) -> dict[str, str]:
    """field -> annotation text, for the boolean test. Read from source, first match wins."""
    out: dict[str, str] = {}
    for path in list(MODEL_DIR.glob("*.py")) + list(API_DIR.glob("*.py")):
        for m in re.finditer(
            r"^class (\w+)\(([\w., \[\]]*)\):\n((?:    .*\n|\n)*)", path.read_text(), re.M
        ):
            for fm in re.finditer(r"^    (\w+)\s*:\s*([^=\n]+)", m.group(3), re.M):
                out.setdefault(fm.group(1), fm.group(2).strip())
    return out


def _routes():
    """(key, declared fields, fields the handler reads) for every body-taking route."""
    fields, bases = _schemas()
    for path in sorted(API_DIR.glob("*.py")):
        source = path.read_text()
        heads = list(ROUTE_HEAD.finditer(source))
        for i, head in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(source)
            chunk = source[head.start(): end]
            verb, route = head.group(1), head.group(2)
            bm = BODY_PARAM.search(chunk)
            if not bm:
                continue
            var, model = bm.groups()
            declared = set(_declared(model, fields, bases))
            if not declared:
                continue
            # `model_dump()` forwards the whole body at once; nothing can be dropped.
            if re.search(rf"\b{var}\.(model_dump|dict)\(", chunk):
                continue
            read = set(re.findall(rf"\b{var}\.(\w+)", chunk))
            yield f"{path.stem}:{verb.upper()} {route}", declared, read


class TestTheMeasurementIsReal:
    def test_routes_are_found(self):
        routes = list(_routes())
        assert len(routes) > 25, (
            f"only {len(routes)} body-taking routes found; the route regex collapsed and "
            f"every assertion below would be about nothing"
        )

    def test_a_known_complete_route_reads_everything_it_declares(self):
        """Positive control. `POST /yard/checkpoints` was the first instance of this class and
        is now wired end to end, so it must read every field it declares. If this fails the
        extractor is under-counting what a handler reads, and the register would grow with
        routes that are fine."""
        for key, declared, read in _routes():
            if key == "yard:POST /checkpoints":
                assert not (declared - read), f"control route drops {sorted(declared - read)}"
                return
        pytest.fail("the control route was not found at all")

    def test_the_extractor_sees_a_dropped_field(self):
        """Negative control, so the sweep is not passing by reading nothing. The register is
        non-empty by construction; if it were empty this test would be the one to delete."""
        assert any(declared - read for _key, declared, read in _routes())


class TestNoBooleanLosesTheFieldThatBoundsIt:
    """ABSOLUTE, not ratcheted. Rule 143."""

    def test_no_route_passes_a_flag_and_drops_its_qualifier(self):
        annotations = _annotations("")
        offenders = []
        for key, declared, read in _routes():
            for flag in sorted(f for f in declared & read if "bool" in annotations.get(f, "")):
                head = flag.split("_")[0]
                for field in sorted(declared - read):
                    if QUALIFIER.search(field) and field.startswith(head):
                        offenders.append(f"{key}: passes {flag}, drops {field}")
        assert not offenders, (
            f"{offenders} — a boolean is stored and the field that says what it is worth is "
            f"discarded. `POST /carriers` did exactly this and every carrier it created "
            f"reported its certification invalid, because the compliance check reads "
            f"`certified AND expires_at AND expires_at > now`. Pass the qualifier, or take "
            f"the flag off the Create schema."
        )


class TestTheRegisterOnlyShrinks:
    def test_no_new_route_drops_a_declared_field(self):
        new = sorted(
            f"{key}: {sorted(declared - read)}"
            for key, declared, read in _routes()
            if (declared - read) and key not in UNREAD
        )
        assert not new, (
            f"{new} declare body fields the handler never reads. Either pass them to the "
            f"service, or take them off the Create schema — an API that accepts a value it "
            f"will never honour is its own small lie. If neither is right yet, add the route "
            f"to UNREAD with the reason."
        )

    def test_no_recorded_route_drops_more_than_it_did(self):
        """A recorded route may shrink its list, never grow it."""
        grew = []
        for key, declared, read in _routes():
            if key not in UNREAD:
                continue
            extra = sorted((declared - read) - set(UNREAD[key]))
            if extra:
                grew.append(f"{key}: now also drops {extra}")
        assert not grew, f"{grew}. The register may shrink, never grow."

    def test_no_recorded_route_is_already_clean(self):
        """A stale entry overstates the debt and invites the work to be done twice."""
        live = {key: declared - read for key, declared, read in _routes()}
        stale = sorted(
            key for key, fields in UNREAD.items()
            if key not in live or not (set(fields) & live[key])
        )
        assert not stale, (
            f"{stale} are recorded as dropping fields and no longer do, or no longer exist. "
            f"Remove them so the register means something."
        )

    @pytest.mark.parametrize("key", sorted(UNREAD))
    def test_each_recorded_route_still_exists(self, key: str):
        assert key in {k for k, _d, _r in _routes()}, (
            f"{key} is in the register and is not a body-taking route any more"
        )


def test_the_register_is_serialisable_for_a_report():
    """The register is data, not prose, so a status report can be generated from it rather
    than transcribed — the transcription is what goes stale."""
    assert json.dumps(UNREAD)
    assert sum(len(v) for v in UNREAD.values()) > 0
