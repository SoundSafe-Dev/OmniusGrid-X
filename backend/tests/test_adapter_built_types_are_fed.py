"""A field an adapter never sets is a field that never arrives (FS-442).

`test_frontend_types_match_their_own_payload` pairs a TS interface with a same-named
backend response model. That covers the types the server sends directly and reaches **none**
of the adapter-built ones — `GeofenceZoneExtended`, `GeofenceAlertExtended`,
`MaintenanceSchedule` and the rest, which are assembled in `src/api/*.ts` from a response
whose shape diverges from the component's.

Those adapters are where two of this week's defects lived: every geofence alert reading
`'Violation'` because an unrecognised type fell back to a constant, and every zone reporting
`0 vehicles inside` because an absent list was defaulted to `[]`. So the uncovered half is
not the quiet half.

THE PAIRING IS THE ADAPTER'S OWN RETURN ANNOTATION — no type guessing. An adapter written
`const adaptZone = (z: any): GeofenceZoneExtended => ({ … })` states which interface it
builds, and the keys of that object literal are exactly the fields it can populate. A
declared field the literal never sets is `undefined` for every consumer, whatever the server
sent.

WHAT IS DELIBERATELY OUT OF REACH. `const adaptTrailer = (t: any): YardTrailer => ({ ...t })`
spreads the response through, so every field is "whatever arrived" and this sweep can
conclude nothing. Spread adapters are skipped rather than guessed at — the point of pairing
on the annotation was to stop inferring, and inferring through a spread would be the same
mistake in a new place.
"""

from __future__ import annotations

import re

import pytest

from tests.test_frontend_fields_exist_on_the_wire import COMMENT, FIELD, FRONTEND

#: `const adaptX = (arg: any): TypeName => ({` or `=> {`. The annotation is the pairing.
#:
#: ONLY `adapt*`. `mockAnswer`, `mockAssessment` and `mockResponse` have the same shape and
#: are NOT adapters: a mock's job is to produce a plausible example, and one that omits an
#: optional field is doing nothing wrong. An adapter's job is to produce the interface from
#: a response, so a field it never sets is a field no consumer can ever read. Judging mocks
#: here would bury the real finding under every optional field a fixture skipped.
_ADAPTER = re.compile(
    r"const\s+(adapt\w*)\s*=\s*\([^)]*\)\s*:\s*([A-Z]\w+)\s*=>\s*(\(?\{)", re.M
)

#: `export interface Name {` and `export interface Name extends Parent {`. The shared
#: `INTERFACE` regex in the sibling module requires `{` immediately after the name, so it
#: silently skips every extended interface — `GeofenceZoneExtended extends GeofenceZone` is
#: exactly the type this file exists to reach.
_INTERFACE = re.compile(
    r"export interface (\w+)(?:\s+extends\s+([\w,\s]+?))?\s*\{([^}]*)\}", re.S
)

#: A key set in the returned object literal — BOTH forms. `fieldName: value` and the
#: SHORTHAND `fieldName,`, which is how `adaptZone` sets `center` after computing it into a
#: local. The first version of this regex read only the colon form and reported `center` as
#: never set: a confident false finding about the one adapter this file was written for.
_LITERAL_KEY = re.compile(r"^\s{2,}(\w+)\s*(?::|,\s*$)", re.M)

#: `...x` anywhere in the body means the adapter forwards fields it never names.
_SPREAD = re.compile(r"\.\.\.\w")


def _balanced(text: str, start: int) -> str:
    """The adapter body, by brace balancing — a fixed window mis-attributes keys."""
    depth, i, opened = 0, start, False
    while i < len(text):
        if text[i] in "{(":
            depth += 1
            opened = True
        elif text[i] in "})":
            depth -= 1
            if opened and depth <= 0:
                return text[start:i]
        i += 1
    return text[start:]


def _ts_interfaces() -> dict[str, set[str]]:
    """Declared fields per interface, with `extends` resolved.

    Reads `src/types/` AND `src/api/` — `RagAnswer` and `RULAssessment` are declared beside
    the client that returns them, and an interface is no less real for living next to its
    caller.

    Inheritance matters here specifically: an adapter returning `GeofenceZoneExtended` has
    to populate everything `GeofenceZone` declares too, and reading only the child's own
    body would call a half-built object complete.
    """
    own: dict[str, set[str]] = {}
    parents: dict[str, list[str]] = {}
    for folder in ("types", "api"):
        for path in (FRONTEND / folder).glob("*.ts"):
            if path.name.endswith(".test.ts"):
                continue
            text = COMMENT.sub(" ", path.read_text())
            for match in _INTERFACE.finditer(text):
                name, extends, body = match.group(1), match.group(2), match.group(3)
                own[name] = {f.group(1) for f in FIELD.finditer(body)}
                if extends:
                    parents[name] = [p.strip() for p in extends.split(",") if p.strip()]

    def resolve(name: str, seen: frozenset = frozenset()) -> set[str]:
        if name in seen or name not in own:
            return set()
        fields = set(own[name])
        for parent in parents.get(name, []):
            fields |= resolve(parent, seen | {name})
        return fields

    return {name: resolve(name) for name in own}


def _adapters() -> list[tuple[str, str, str, set[str], bool]]:
    """(file, adapter name, interface, keys it sets, whether it spreads)."""
    out = []
    for path in sorted((FRONTEND / "api").glob("*.ts")):
        if path.name.endswith(".test.ts"):
            continue
        text = COMMENT.sub(" ", path.read_text())
        for match in _ADAPTER.finditer(text):
            body = _balanced(text, match.end() - 1)
            out.append((
                path.name,
                match.group(1),
                match.group(2),
                set(_LITERAL_KEY.findall(body)),
                bool(_SPREAD.search(body)),
            ))
    return out


ADAPTERS = _adapters()
INTERFACES = _ts_interfaces()

#: Adapters whose interface this sweep can judge: annotated, non-spreading, and pointing at
#: an interface we parsed.
JUDGED = [
    (file, name, iface, keys)
    for file, name, iface, keys, spreads in ADAPTERS
    if not spreads and iface in INTERFACES
]


class TestTheSweepIsNotVacuous:
    def test_it_finds_adapters(self):
        assert len(ADAPTERS) >= 4, (
            f"only {len(ADAPTERS)} annotated adapters found; the pattern has drifted and "
            f"every assertion below would pass over nothing"
        )

    def test_it_judges_some_of_them(self):
        assert len(JUDGED) >= 2, (
            f"only {len(JUDGED)} adapters are judgeable ({len(ADAPTERS)} found). If they "
            f"have all become spread-style this file no longer guards anything"
        )

    def test_it_skips_a_spread_adapter(self):
        """`({ ...t })` forwards fields it never names, so no conclusion is available."""
        spreading = [name for _, name, _, _, spreads in ADAPTERS if spreads]
        assert spreading, (
            "no spread adapter found; the skip path is untested and a future one would be "
            "judged on the keys it happens to name"
        )

    def test_it_reads_the_keys_of_a_literal(self):
        geofence = [k for f, _, i, k in JUDGED if i == "GeofenceAlertExtended"]
        assert geofence and "vehicleNumber" in geofence[0], (
            "the object-literal key reader is broken; it cannot see fields the adapter sets"
        )


#: Fields an adapter deliberately leaves unset, with the reason. Not a suppression list —
#: each entry says why the field is legitimately absent from THIS adapter.
KNOWN_UNSET: dict[str, str] = {}

#: LOWER, never raise.
MAX_UNSET_FIELDS = 0


def _unset() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for file, name, iface, keys in JUDGED:
        missing = {
            field for field in INTERFACES[iface] - keys
            if f"{iface}.{field}" not in KNOWN_UNSET
        }
        if missing:
            found[f"{file}:{name} -> {iface}"] = missing
    return found


def test_no_adapter_leaves_a_declared_field_unset():
    unset = _unset()
    total = sum(len(v) for v in unset.values())
    assert total <= MAX_UNSET_FIELDS, (
        f"{total} fields are declared on an interface that its own adapter never sets, so "
        f"they are `undefined` for every consumer no matter what the server sends. Set "
        f"them, or delete them from the interface:\n"
        + "\n".join(f"  {k}: {', '.join(sorted(v))}" for k, v in sorted(unset.items()))
    )
