"""A TS interface must match the payload that FEEDS IT, not the wire in general (FS-435).

`test_frontend_fields_exist_on_the_wire` builds one vocabulary of **8,229 field names**
drawn from every response model, every raw dict key and every alias in the codebase, and
asks whether a declared TS field appears anywhere in it. That is the right question for
"is this name a fiction", and the wrong question for "does this field arrive".

MEASURED ON `YardMove` BEFORE ANY FIX. `YardMoveResponse` sends twelve fields. The TS
interface declared eleven, and **six were not among the twelve**:

    performedBy           not sent | credited by the global vocabulary
    startTime             not sent | credited by the global vocabulary
    endTime               not sent | credited by the global vocabulary
    trailerLicensePlate   not sent | credited by the global vocabulary
    status                not sent | credited by the global vocabulary
    notes                 not sent | credited by the global vocabulary
    equipmentUsed         not sent | NOT credited — the only one the older sweep saw

Six of the seven were invisible because some *other* endpoint sends a `status`, a `notes`,
a `startTime`. The older sweep reported ONE phantom on this type where there were seven,
so its total of 34 is a floor rather than a count.

`performedBy`, `startTime` and `endTime` were the sharp ones and are now FIXED: the backend
sends `jockey_driver_id`, `started_at` and `completed_at`, and the only thing between them
and the TS names was an alias nobody wrote. A yard move rendered its mover and both of its
times as undefined. Three lines in `YARD_ALIASES`; the same commit added the missing half
of the DockAppointment `actual_start`/`actual_end` pair and the third Driver expiry alias.

So the four names above that remain — `trailerLicensePlate`, `status`, `notes`,
`equipmentUsed` — are the ones with no source at all, and deciding between "the server
should send it" and "delete the field" is a product question. They stay in the count rather
than being excused, because inventing an answer to make a number go down is how the phantom
fields arrived in the first place.

WHY THIS IS A SEPARATE FILE rather than a repair of the other one. The two ask different
questions and both are worth asking. A name that appears nowhere on the wire is a fiction
whatever type it sits on; a name that appears on the wrong payload is a mismatch that only
a per-type check can see. Merging them would lose the first.

SCOPE — and it is deliberately narrow. Only TS interfaces whose name matches a backend
response model (`YardMove` → `YardMoveResponse`) are checked, because that is where the
correspondence is unambiguous. A type assembled from three endpoints has no single payload
to be checked against, and guessing which one would produce exactly the confident-but-wrong
findings this file exists to replace.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models import schemas
from tests.test_frontend_fields_exist_on_the_wire import (
    COMMENT,
    FIELD,
    FRONTEND,
    INTERFACE,
    _wire_vocabulary,
)

#: Alias maps in the casing seam rename fields beyond casing. A TS name that is the TARGET
#: of an alias is fed by the alias SOURCE, so both have to be resolvable.
_ALIAS_ENTRY = re.compile(r"^\s*(\w+):\s*'([^']+)',", re.M)


def _alias_targets_to_sources() -> dict[str, set[str]]:
    text = (FRONTEND / "api" / "transform.ts").read_text()
    out: dict[str, set[str]] = {}
    for source, target in _ALIAS_ENTRY.findall(text):
        out.setdefault(target, set()).add(source)
    return out


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(part.title() for part in rest)


def _response_model_fields(model) -> set[str]:
    """Every name this model can put on the wire, camelCased as the seam delivers them.

    `model_computed_fields` as well as `model_fields`. A Pydantic v2 `@computed_field` is
    serialised and appears in the OpenAPI schema but is NOT in `model_fields`, so reading
    only the latter reported `DriverWaitTime.detentionAssessed` as never sent — a field
    added deliberately three commits earlier precisely so it would reach the client. A
    guard that calls a working field broken teaches people to skip its findings.
    """
    names: set[str] = set()
    for field_name, field in model.model_fields.items():
        names.add(_camel(field_name))
        for attr in ("serialization_alias", "alias"):
            value = getattr(field, attr, None)
            if isinstance(value, str):
                names.add(_camel(value))
    for computed_name in getattr(model, "model_computed_fields", {}):
        names.add(_camel(computed_name))
    return names


def _ts_interfaces() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in (FRONTEND / "types").glob("*.ts"):
        text = COMMENT.sub(" ", path.read_text())
        for match in INTERFACE.finditer(text):
            found[match.group(1)] = {f.group(1) for f in FIELD.finditer(match.group(2))}
    return found


#: Keys a handler writes onto the row AFTER validating the model — `row["carrierName"] = …`
#: and `"driverPhone": …` in a dict literal. The first version of this sweep read only the
#: response model and reported 63 unfed fields; `DockAppointment.carrierName`,
#: `trailerLicensePlate` and `driverPhone` are all set by the handler two lines after
#: `model_dump`, so part of that finding was the detector's blind spot rather than the
#: codebase's. Same shape as FS-305, and the third time this family of sweeps has hit it.
_ROW_ASSIGN = re.compile(r"""\brow\[["']([A-Za-z_]\w*)["']\]\s*=""")
_DICT_KEY = re.compile(r"""["']([a-z][A-Za-z0-9_]*)["']\s*:""")

API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"


def _keys_added_by_producing_modules(model_name: str) -> set[str]:
    """Every key written by an api module that uses this response model.

    Coarse on purpose: it credits any key the producing module emits anywhere. That can
    only make this sweep MORE forgiving, which is the right direction — a false finding
    costs someone a real investigation, and this file exists because the previous sweep's
    findings could not be trusted per-type.
    """
    keys: set[str] = set()
    for path in API_DIR.glob("*.py"):
        text = path.read_text()
        if model_name not in text:
            continue
        keys |= {_camel(name) for name in _ROW_ASSIGN.findall(text)}
        keys |= {_camel(name) for name in _DICT_KEY.findall(text)}
    return keys


def _paired() -> dict[str, tuple[set[str], set[str]]]:
    """interface -> (declared TS fields, fields the payload that feeds it can carry)."""
    interfaces = _ts_interfaces()
    pairs: dict[str, tuple[set[str], set[str]]] = {}
    for name, fields in interfaces.items():
        model_name = f"{name}Response"
        model = getattr(schemas, model_name, None)
        if model is None or not hasattr(model, "model_fields"):
            continue
        sent = _response_model_fields(model) | _keys_added_by_producing_modules(model_name)
        pairs[name] = (fields, sent)
    return pairs


PAIRS = _paired()
ALIAS_SOURCES = _alias_targets_to_sources()


def _unfed(declared: set[str], sent: set[str]) -> set[str]:
    """Declared fields with no source on this payload, directly or through an alias."""
    missing = set()
    for field in declared - sent:
        if any(source in sent for source in ALIAS_SOURCES.get(field, ())):
            continue
        missing.add(field)
    return missing


class TestTheSweepIsNotVacuous:
    def test_it_pairs_some_types(self):
        assert len(PAIRS) >= 8, (
            f"only {len(PAIRS)} TS interfaces paired with a same-named response model; the "
            f"interface parser or the naming convention has drifted and every assertion "
            f"below would pass over nothing"
        )

    def test_it_resolves_an_alias(self):
        """`performedBy` is fed by `jockey_driver_id` through YARD_ALIASES. Without alias
        resolution this file would report every aliased field as missing — dozens of
        confident false findings, which is the failure it was written to avoid."""
        assert "performedBy" in ALIAS_SOURCES
        assert "jockeyDriverId" in ALIAS_SOURCES["performedBy"]

    def test_it_camelcases_the_way_the_seam_does(self):
        assert _camel("jockey_driver_id") == "jockeyDriverId"
        assert _camel("id") == "id"

    def test_a_field_on_the_payload_is_not_reported(self):
        assert not _unfed({"trailerId"}, {"trailerId"})

    def test_a_field_absent_from_the_payload_is_reported(self):
        assert _unfed({"invented"}, {"trailerId"}) == {"invented"}


#: Fields declared on a paired interface that this payload does not carry, WITH THE REASON.
#: Not a suppression list: each entry names why the field is legitimately absent, and the
#: ratchet below is what stops it being used as one.
#:
#: `trailerLicensePlate`, `status` and `notes` on YardMove are NOT here. They are real
#: mismatches, left visible in the count rather than excused, because deciding between
#: "the server should send it" and "delete the field" is a product question and inventing
#: an answer to make a number go down is how the phantom fields arrived in the first place.
KNOWN_UNFED: dict[str, str] = {}

#: LOWER THIS, never raise it — and with ZERO slack, which the sibling ratchet learned the
#: hard way: it was set one too high, and a deliberately-planted phantom slipped through
#: because the single spare slot absorbed exactly the regression it existed to catch.
#:
#: 38 is a floor, not a total. Only 14 TS interfaces pair with a same-named response model;
#: the rest are assembled from several endpoints and are out of this sweep's reach.
#: ZERO as of 2026-08-05 (FS-439). It opened at 38, and every one is now resolved rather
#: than excused: six renames where the data arrived under another name, and the rest deleted
#: because no column, join or computation could ever have filled them.
#:
#: A ratchet at zero is the only kind that cannot rot. There is no headroom to absorb a
#: regression and no number to argue about — the next declared field either has a producer
#: or this fails.
MAX_UNFED_FIELDS = 0


def _all_unfed() -> dict[str, set[str]]:
    return {
        name: missing
        for name, (declared, sent) in PAIRS.items()
        if (missing := _unfed(declared, sent) - {KNOWN_UNFED.get(name, "")})
    }


def test_the_count_of_unfed_fields_does_not_grow():
    unfed = _all_unfed()
    total = sum(len(v) for v in unfed.values())
    assert total <= MAX_UNFED_FIELDS, (
        f"{total} declared fields have no source on the payload that feeds their type; "
        f"the ratchet allows {MAX_UNFED_FIELDS}. Each renders as undefined, and "
        f"TypeScript vouches for it.\n\n"
        + "\n".join(
            f"  {name}: {', '.join(sorted(fields))}" for name, fields in sorted(unfed.items())
        )
    )


def test_the_global_vocabulary_is_wider_than_any_single_payload():
    """The premise of this whole file, asserted so it cannot quietly stop being true.

    It used to assert that at least one CURRENT offender was hidden by the global
    vocabulary — sound while offenders existed, and self-defeating the moment the count
    reached zero: its own failure message said "delete it rather than keeping a guard that
    guards nothing", which would have been exactly the wrong conclusion. The count is zero
    BECAUSE this file works.

    The structural fact is what matters and it does not depend on offenders existing: the
    global vocabulary is drawn from every model, dict key and alias in the codebase, so it
    is strictly wider than any one payload. A field can therefore be in it and absent from
    the payload that feeds its type — which is the whole reason a per-type check is needed,
    whether or not anything is currently wrong.
    """
    vocabulary = _wire_vocabulary()
    wider_than = [
        name for name, (_, sent) in PAIRS.items() if len(vocabulary - sent) > len(sent)
    ]
    assert len(wider_than) >= 5, (
        f"the global vocabulary is no longer meaningfully wider than the individual "
        f"payloads ({len(wider_than)} of {len(PAIRS)} paired types); if that is genuinely "
        f"true the sibling sweep now answers this file's question and this one is "
        f"redundant"
    )
