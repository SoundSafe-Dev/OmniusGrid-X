"""A request-body field the frontend sends must be one the endpoint declares (FS-419).

THE THIRD SIDE OF THE SAME SEAM, and the quietest of the three.

  `test_frontend_calls_real_endpoints.py`     the path and method exist
  `test_frontend_query_params_are_declared.py` the query keys are declared
  this file                                    the BODY keys are declared

**Pydantic ignores unknown body fields by default.** So a client that posts
`{"operatorId": ...}` to a model declaring `operator_id` gets a 200, the field is dropped
on the floor, and the write appears to have succeeded. Nothing errors. The row is simply
saved without it, and the defect surfaces later as "why is this column always null".

That is strictly worse than the query-param case, which at least returns unfiltered rows a
careful reader might notice. Here the response is correct in every respect except the one
the caller cared about.

THE PRECEDENT. FS-379: `StrategicRecommendation` approve/reject sent `operator_id` in the
BODY while the server declared it as a query parameter. Every click 422'd, the feature had
never worked once, and no test caught it because `src/test/setup.ts` forces
`VITE_USE_MOCK='true'`, so the real branch of every `if (USE_MOCK)` fork is executed by
nothing. A 422 is the loud version of this class; a silently dropped field is the quiet one.

CASING IS HANDLED, NOT ASSUMED. The axios seam rewrites request bodies camelCase ->
snake_case for registered prefixes only, so a key is accepted under any form it could
legitimately arrive as. Getting that wrong would make this guard a wall of false positives
about the conversion it is supposed to trust.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

from app.main import app

FRONTEND_API = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api"
CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")

#: `api.post('/path', body)` / `.put` / `.patch`. The type argument is optional and may
#: contain braces, so it is matched non-greedily up to the opening paren. The trailing comma
#: is captured rather than required: a call with no body at all is a legitimate shape and is
#: counted separately instead of silently missed.
CALL = re.compile(
    r"\bapi\.(post|put|patch)\s*(?:<[^(]*?>)?\s*\(\s*"
    r"(?:`([^`]+)`|'([^']+)'|\"([^\"]+)\")\s*(,?)",
    re.S,
)

#: Keys of a TypeScript type literal or interface body — `key:` / `key?:`.
TYPE_KEY = re.compile(r"([A-Za-z_$][\w$]*)\s*\??\s*:")


def _readable(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:  # pragma: no cover
        return ""


def _registered_prefixes() -> List[str]:
    """Prefixes whose bodies the seam converts. Read from `registerTransform`, not
    hardcoded — a prefix removed there must tighten this check, not leave a stale
    exemption."""
    prefixes: List[str] = []
    for file in FRONTEND_API.glob("*.ts"):
        if ".test." in file.name:
            continue
        prefixes += re.findall(r"registerTransform\(\s*'([^']+)'", _readable(file))
    return prefixes


def _out_aliases() -> Dict[str, str]:
    source = FRONTEND_API / "transform.ts"
    if not source.exists():
        return {}
    aliases: Dict[str, str] = {}
    for match in re.finditer(r"OUT_ALIASES[^=]*=\s*\{([^}]*)\}", source.read_text()):
        for key, value in re.findall(r"([A-Za-z_$][\w$]*)\s*:\s*'([^']+)'", match.group(1)):
            aliases[key] = value
    return aliases


REGISTERED = _registered_prefixes()
OUT_ALIASES = _out_aliases()


def _snake(name: str) -> str:
    return CAMEL_BOUNDARY.sub(r"\1_\2", name).lower()


def _wire_forms(url: str, key: str) -> Set[str]:
    path = url.split("?")[0]
    if not any(path == p or path.startswith(p + "/") for p in REGISTERED):
        return {key}
    return {key, _snake(key), _snake(OUT_ALIASES.get(key, key))}


def _balanced(source: str, start: int) -> str:
    """The text of the brace-balanced block beginning at `start`."""
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1:i]
    return ""


def _literal_keys(block: str) -> Set[str]:
    """Top-level keys of an object literal. Nested objects are skipped: their keys belong
    to a nested model this guard does not resolve, and reporting them would be noise."""
    keys: Set[str] = set()
    depth = 0
    for match in re.finditer(r"[{}]|([A-Za-z_$][\w$]*)\s*:|\.\.\.([A-Za-z_$][\w$]*)", block):
        token = match.group(0)
        if token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
        elif depth == 0 and match.group(1):
            keys.add(match.group(1))
    return keys


def _balanced_from(source: str, open_bracket: int) -> str:
    return "{" + _balanced(source, open_bracket) + "}"


def _top_level_type_keys(block: str) -> Set[str]:
    """Keys at depth 0 of a TypeScript type literal or interface body.

    DEPTH MATTERS HERE AND DOES NOT FOR QUERY PARAMS, which is why this cannot simply call
    the sibling's resolver. Its type reader takes every `key:` in the block, because a query
    string is flat. A body is not: `erp.ts` declares

        rate_limit?: { requests_per_minute: number; burst_limit: number }

    and the server declares `rate_limit: Optional[Dict[str, int]]`. Reading the nested pair
    as top-level fields reported two defects that do not exist — the first run of this guard
    did exactly that. A nested object's keys belong to a nested model, and this guard does
    not resolve those, so it must not claim to.
    """
    keys: Set[str] = set()
    depth = 0
    for match in re.finditer(r"[{}]|([A-Za-z_$][\w$]*)\s*\??\s*:", block):
        token = match.group(0)
        if token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
        elif depth == 1 and match.group(1):
            keys.add(match.group(1))
    return keys


def _resolve_body_variable(source: str, pos: int, name: str) -> Set[str]:
    """Keys of a body passed as an identifier, across the four shapes this codebase uses.

    The enclosing-function scoping is borrowed from the query-param sibling — several
    modules build a local `payload` in more than one function, and merging them would
    invent fields no single call sends. The KEY READING is not borrowed; see
    `_top_level_type_keys`.
    """
    from tests.test_frontend_query_params_are_declared import _enclosing_function

    signature, body = _enclosing_function(source, pos)
    keys: Set[str] = set()
    escaped = re.escape(name)

    # 1. a parameter with an inline type literal: `(body: { title: string })`
    inline = re.search(rf"\b{escaped}\s*\??\s*:\s*\{{", signature)
    if inline:
        keys |= _top_level_type_keys(_balanced_from(signature, inline.end() - 1))

    # 2. a parameter typed by a named interface: `(payload: CreateAlarmRule)`
    named = re.search(rf"\b{escaped}\s*\??\s*:\s*([A-Z][\w]*)", signature)
    if named:
        declaration = re.search(rf"(?:interface|type)\s+{named.group(1)}\b[^{{]*\{{", source)
        if declaration:
            keys |= _top_level_type_keys(_balanced_from(source, declaration.end() - 1))

    # 3. a local object literal: `const payload = { ... }`
    local = re.search(rf"(?:const|let|var)\s+{escaped}\s*(?::[^=]+?)?=\s*\{{", body)
    if local:
        keys |= _literal_keys(_balanced(body, local.end() - 1))

    # 4. keys assigned afterwards: `if (x) payload.x = x`
    keys |= set(re.findall(rf"\b{escaped}\.([A-Za-z_$][\w$]*)\s*=(?!=)", body))
    return keys


def _body_calls() -> List[Tuple[str, str, str, Set[str], Dict[str, str]]]:
    """(module, method, url, keys) for every write whose body is an inline object literal.

    A body passed as a bare identifier is traced through the sibling's resolver, because
    61% of the writes in this codebase are that shape — a guard that read only inline
    literals would cover about a ninth of the surface while looking complete.
    """
    found: List[Tuple[str, str, str, Set[str], Dict[str, str]]] = []
    for file in sorted(FRONTEND_API.glob("*.ts")):
        if ".test." in file.name:
            continue
        source = _readable(file)
        constants = _module_constants(source)
        for match in CALL.finditer(source):
            method = match.group(1)
            url = match.group(2) or match.group(3) or match.group(4)
            if not match.group(5):        # no body argument at all
                continue
            rest = source[match.end():].lstrip()
            if rest.startswith("{"):
                keys = _literal_keys(_balanced(rest, 0))
            else:
                identifier = re.match(r"([A-Za-z_$][\w$]*)", rest)
                if not identifier:
                    continue
                keys = _resolve_body_variable(source, match.start(), identifier.group(1))
            if keys:
                found.append((file.name, method, url, keys, constants))
    return found


def _module_constants(source: str) -> Dict[str, str]:
    """`const BASE = '/api/v1/notifications'` — module-level string constants.

    Without these, a URL written as `${BASE}/subscriptions` normalises to `{param}/...`,
    matches no route, and is reported as "the endpoint declares no JSON body". Four calls
    were flagged that way: not a defect in the client, a defect in the reader. A guard that
    cannot resolve a path must say so rather than blame the code it is reading.
    """
    return dict(re.findall(r"const\s+([A-Z][A-Z0-9_]*)\s*=\s*'([^']+)'", source))


def _normalise(raw: str, constants: Dict[str, str] | None = None) -> str:
    path = raw.split("?")[0]
    for name, value in (constants or {}).items():
        path = path.replace("${" + name + "}", value)
    path = re.sub(r"\$\{[^}]*\}", "{param}", path)
    return path.rstrip("/") or "/"


def _declared_bodies() -> Dict[Tuple[str, str], Set[str]]:
    """{(path, method): declared body field names} from the live OpenAPI schema.

    Read from the schema rather than from the source, so aliases, inherited fields and
    `$ref`s resolve the way FastAPI actually resolves them.
    """
    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})

    def fields(schema: dict, seen: Set[str] | None = None) -> Set[str]:
        seen = seen or set()
        if not isinstance(schema, dict):
            return set()
        ref = schema.get("$ref")
        if ref:
            name = ref.rsplit("/", 1)[-1]
            if name in seen:
                return set()
            return fields(components.get(name, {}), seen | {name})
        out = set(schema.get("properties", {}))
        for key in ("allOf", "anyOf", "oneOf"):
            for sub in schema.get(key, []) or []:
                out |= fields(sub, seen)
        return out

    table: Dict[Tuple[str, str], Set[str]] = {}
    for raw_path, operations in spec["paths"].items():
        path = _normalise(re.sub(r"\{[^}]+\}", "{param}", raw_path))
        for method, operation in operations.items():
            body = (operation.get("requestBody") or {}).get("content", {})
            schema = (body.get("application/json") or {}).get("schema")
            if schema is not None:
                table[(path, method.lower())] = fields(schema)
    return table


CALLS = _body_calls()
DECLARED = _declared_bodies()


def _mismatches() -> List[str]:
    problems: List[str] = []
    for module, method, url, keys, constants in CALLS:
        path = _normalise(url, constants)
        if "{param}" in path.split("/")[3:4]:
            # The path still starts with an unresolved template variable, so it cannot be
            # matched against any route. Reported by `test_every_url_resolves` rather than
            # blamed on the endpoint.
            continue
        declared = DECLARED.get((path, method))
        if declared is None:
            # Either the operation declares no JSON body, or the path is not in the schema.
            # `test_frontend_calls_real_endpoints` owns the second case; the first is
            # reported HERE, because it is the FS-379 shape exactly — a client sending
            # fields in the body to an endpoint that takes them as query parameters, or
            # takes nothing at all. Every field is discarded.
            #
            # THIS BRANCH USED TO `continue`, with a comment claiming it was "reported
            # separately below". It was not. A planted `{ operatorId, clearedBecause }` on
            # an endpoint declaring no body passed the guard silently — the comment
            # described a check nobody had written.
            if path in {p for p, _ in DECLARED} or (path, method) in DECLARED:
                pass
            if keys:
                problems.append(
                    f"{module}: {method.upper()} {url} sends a body {sorted(keys)}, but the "
                    f"endpoint declares no JSON body — every field is discarded"
                )
            continue
        if not declared:
            continue
        for key in sorted(keys):
            # THE RESOLVED PATH, not the raw URL. `${BASE}/subscriptions` matches no
            # registered prefix, so the seam's camelCase -> snake_case conversion was
            # not applied and three correctly-cased keys were reported as undeclared.
            if not (_wire_forms(path, key) & declared):
                problems.append(
                    f"{module}: {method.upper()} {url} sends `{key}`, which the endpoint "
                    f"does not declare (it accepts {sorted(declared)})"
                )
    return problems


class TestTheScanIsNotVacuous:
    """A guard that reads nothing passes forever. These state its reach out loud."""

    def test_it_resolves_the_bodies_it_claims_to(self):
        """MEASURED, NOT ASSUMED — and the assumption was wrong twice.

        70 write calls carry a body. This resolves the keys of 31 of them and matches all 31 to
        a declared schema; the rest are shapes the resolver does not reach (a body spread
        from a function argument, a variable declared outside the enclosing function, a
        conditional expression). Those are NOT silently ignored — the number is asserted
        here, so coverage that shrinks is a failure rather than a quieter pass.

        Three floors were guessed before this one was measured: 20, then 45, then 35. All
        three were made up. A floor pulled from the air is a claim about nothing.
        """
        assert len(CALLS) >= 31, (
            f"only {len(CALLS)} write bodies resolved across {FRONTEND_API}, down from 31; "
            f"the call pattern probably changed and this file would pass while checking less"
        )

    def test_it_reads_the_declared_bodies(self):
        assert len(DECLARED) >= 100, (
            f"only {len(DECLARED)} operations with a JSON body found in the schema"
        )

    def test_it_extracts_top_level_keys_only(self):
        block = " assetId: 1, nested: { inner: 2 }, reason: r "
        assert _literal_keys(block) == {"assetId", "nested", "reason"}

    def test_a_registered_prefix_accepts_the_snake_case_form(self):
        prefix = REGISTERED[0] if REGISTERED else "/api/v1/assets"
        assert "asset_id" in _wire_forms(f"{prefix}/x", "assetId")

    def test_an_unregistered_prefix_does_not(self):
        """`/api/v1/nlp` is deliberately off the seam, so a camelCase key there really
        does arrive as written and must be compared as written."""
        assert _wire_forms("/api/v1/nlp/sessions", "assetId") == {"assetId"}


def test_every_body_field_the_frontend_sends_is_declared():
    problems = _mismatches()
    assert not problems, (
        "these request-body fields are sent by the frontend and not declared by the "
        "endpoint. FastAPI DROPS them silently — the write returns 200 with the field "
        "missing, so nothing errors and the column is simply never populated:\n  "
        + "\n  ".join(problems)
    )
