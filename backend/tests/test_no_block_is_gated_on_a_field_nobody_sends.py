"""A conditional block must not hide data on a field that never arrives (FS-438).

`YardManagement.tsx` wrapped the trailer's whole driver section in
`{trailer.driverName && ( … )}`. **`driverName` was never sent**, so the block never
rendered — and it took `driverPhone` with it, a field the yard resolver exists specifically
to deliver, under a docstring calling it *"the number an operator calls when a trailer has
been sitting on the yard"*.

That phone fix was real, correct, tested, and invisible for as long as the gate stood. **A
guard on a field nobody sends is a permanent `false`, and everything inside it disappears** —
worse than a blank line, because a blank line can be seen, and worse than a missing field,
because it silently cancels work that was done properly.

THE RULE IS NARROWER THAN "DO NOT GATE ON AN UNSENT FIELD", and the difference is the whole
point. Two other gates in this codebase do exactly that, correctly:

  * `{zone.vehiclesInside && …}` in `GeofencingPanel.tsx` — added deliberately, under a
    comment explaining that the panel previously rendered an unconditional
    `{n} vehicles inside` and every zone reported **0**, "a count, which reads as a
    measurement, not as a blank".
  * `{vehicle.tripInfo && …}` in `GeoTabIntegration.tsx` — the block shows only
    `tripInfo.destination`.

In both, the gate hides a field that is itself absent. That is right: showing nothing beats
showing a fabricated zero. The defect is the OTHER shape — a gate on an absent field
standing in front of a field that **does** arrive.

So this asserts: *if the gating field has no producer, nothing inside the block may have
one.* Decidable without resolving the object's type, which is what makes it trustworthy —
three sweeps in this directory have now been wrong because they guessed at types.

MEASURED TODAY: three gates on a field with no wire producer, all three legitimate. The
population this guards is empty and was not empty last week.
"""

from __future__ import annotations

import re

import pytest

from tests.test_frontend_fields_exist_on_the_wire import FRONTEND
from tests.test_frontend_types_match_their_own_payload import PAIRS, _unfed

#: `{obj.field && (` and `{obj?.field && (`.
_GATE = re.compile(r"\{\s*(\w+)\??\.(\w+)\s*&&")

#: React Query and react-hook-form state lives on the HOOK RESULT, not on a payload:
#: `isError`, `isPending`, `isFetching`, `__form`. Twenty-two of the twenty-five gates the
#: first run of this sweep reported were these, and none is a wire field.
_CLIENT_STATE = re.compile(r"^(is|has)[A-Z]|^__|^(data|error|status|refetch|mutate)$")

#: `e.target.value` and friends are the handler's own event object, not payload — the first
#: version of this sweep counted them and reported `['target', 'value']` as hidden data.
_EVENT_READ = re.compile(r"\b(e|ev|event|evt)\??\.\w+")


def _block_after(text: str, start: int) -> str:
    """The JSX the gate actually controls, by BALANCING BRACES rather than reading a window.

    The first version read a fixed 700 characters past the `&&` and reported all three of
    this codebase's legitimate gates as defects: it ran off the end of a four-line block and
    picked up the `name` of the NEXT element, plus `target`/`value` from an event handler
    below it. Three false findings from a constant.

    A fixed window cannot work here. A gated block is one line in one place and forty in
    another, and reading too far does not merely add noise — it attributes fields to a block
    that does not contain them, which is precisely the claim this file makes.
    """
    depth, i, opened = 0, start, False
    while i < len(text):
        char = text[i]
        if char in "{(":
            depth += 1
            opened = True
        elif char in "})":
            depth -= 1
            if opened and depth <= 0:
                return text[start:i]
        i += 1
    return text[start:]


def _gates() -> list[tuple[str, str, str, set[str]]]:
    """(file, object, gating field, fields read inside the block)."""
    found = []
    for path in sorted(FRONTEND.rglob("*.tsx")):
        if "test" in path.name:
            continue
        text = path.read_text()
        for match in _GATE.finditer(text):
            obj, field = match.group(1), match.group(2)
            if _CLIENT_STATE.match(field):
                continue
            block = _EVENT_READ.sub("", _block_after(text, match.end()))
            # SAME OBJECT ONLY. `{vehicle.tripInfo && …}` reads `vehicle.tripInfo.
            # destination` inside — a SUB-field of the thing that is absent, not a sibling
            # being hidden — and a window-based reader counted it as hidden data. Scoping to
            # `obj.<name>` reads that name exactly, which is the FS-437 shape:
            # `{trailer.driverName && …}` standing in front of `trailer.driverPhone`.
            #
            # It also removes the generic-name collisions. `value` and `name` are in the
            # 8,229-name wire vocabulary because SOME endpoint sends them, so any block
            # mentioning `.value` looked like it was hiding server data.
            inside = {
                name
                for name in re.findall(rf"\b{re.escape(obj)}\??\.(\w+)\b", block)
                if name != field and not _CLIENT_STATE.match(name)
            }
            found.append((str(path.relative_to(FRONTEND)), obj, field, inside))
    return found


GATES = _gates()


class TestTheSweepIsNotVacuous:
    def test_it_finds_gates(self):
        assert len(GATES) >= 40, (
            f"only {len(GATES)} conditional gates found; the JSX pattern has drifted and "
            f"the assertion below would pass over nothing"
        )

    def test_it_ignores_query_state(self):
        assert _CLIENT_STATE.match("isError")
        assert _CLIENT_STATE.match("isPending")
        assert not _CLIENT_STATE.match("driverName")

    def test_it_reads_the_fields_inside_a_block(self):
        gates = {
            (obj, field): inside for _, obj, field, inside in GATES
        }
        assert any(inside for inside in gates.values()), (
            "no gate reported any field read inside it; the block reader is broken and a "
            "dead block hiding live data could not be detected"
        )


def _interfaces_declaring(field: str) -> set[str]:
    """Paired TS interfaces that declare this field name."""
    return {name for name, (declared, _) in PAIRS.items() if field in declared}


def test_no_gate_on_an_unsent_field_hides_a_sent_one():
    """The FS-437 shape, asserted PER TYPE.

    The first version of this assertion used the global wire vocabulary and **would not
    have caught FS-437**, which is the defect it was written for. `driverName` is sent by
    `fleet_health.py`, so it stays in the 8,229-name vocabulary no matter what the yard
    does, and the yard's gate looked fed. That is the same collision the per-type sweep was
    built for one commit earlier, reappearing in the guard written to complement it.

    SOUNDNESS WITHOUT RESOLVING THE OBJECT'S TYPE. A gate is judged only when the gating
    field and a field read inside the block are BOTH declared on one paired interface. Two
    names co-occurring on a single interface is strong evidence the object has that type,
    and requiring the pair is what makes it evidence rather than a guess — three sweeps in
    this directory have been wrong from guessing types, and this one declines to.

    `{zone.vehiclesInside && …}` is untouched by this: `GeofenceZoneExtended` has no
    same-named response model, so it is not paired and never judged. That is the right
    outcome for the right reason, not a coincidence — the deliberate gates in this codebase
    sit on types assembled by adapters, which are exactly the ones pairing cannot reach.
    """
    offenders = []
    for path, obj, field, inside in GATES:
        # ALL matching interfaces, named together. The pair (`driverName`, `driverPhone`) is
        # declared on BOTH `YardTrailer` and `DockAppointment`, and reporting the first match
        # would send a reader to whichever the dict happened to yield — a small wrongness
        # that costs a real investigation. This sweep deliberately does not resolve the
        # object's type, so it must not claim one.
        matches = []
        for interface in sorted(_interfaces_declaring(field)):
            declared, sent = PAIRS[interface]
            unfed = _unfed(declared, sent)
            if field not in unfed:
                continue  # the gating field DOES arrive on this type
            hidden = sorted(
                name for name in inside if name in declared and name not in unfed
            )
            if hidden:
                matches.append((interface, hidden))
        if matches:
            names = ", ".join(f"`{i}`" for i, _ in matches)
            hidden = sorted({h for _, hs in matches for h in hs})
            offenders.append(
                f"{path}: {{{obj}.{field} && …}} — on {names}, `{field}` has no producer, "
                f"so this block never renders, and it stands in front of {hidden}, which "
                f"the server does send"
            )
    assert not offenders, (
        "these blocks are gated on a field their own payload never carries, and they stand "
        "in front of fields that DO arrive — so the data is fetched, serialised and thrown "
        "away without ever reaching a screen:\n  " + "\n  ".join(sorted(set(offenders)))
    )
