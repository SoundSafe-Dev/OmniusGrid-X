"""A frontend call typed as an array must not receive a paginated envelope.

THE THIRD LEG of the frontend/backend contract. Its siblings check that the path exists
(`test_frontend_calls_real_endpoints.py`) and that the query parameters are declared
(`test_frontend_query_params_are_declared.py`). Neither says anything about what comes
back.

THE FAILURE THIS CATCHES. `api.get<Carrier[]>(...)` followed by `response.data.map(...)`
against an endpoint returning `{items: [...], meta: {...}}` is a runtime
`.map is not a function` — in production, in front of a user. The reverse is quieter and
worse: a call typed as an envelope against an endpoint returning a bare array reads
`.items` as `undefined` and renders an empty list, which looks like "no data".

TypeScript cannot catch either. The type argument to `api.get<T>` is an *assertion* about
a JSON payload, not a checked fact, so the compiler believes whatever it is told.

WHEN THIS WAS WRITTEN IT FOUND NOTHING — 86 typed calls, zero mismatches — and that is
worth recording rather than deleting. The envelope migration (FS-99) evidently landed on
both sides. This exists so the next one cannot half-land.

SCOPE, deliberately narrow. It compares array-vs-object-vs-envelope, not field names.
Field-level comparison would have to model the prefix-gated snake↔camel transform seam,
and a detector that mismodels it manufactures defects — which has already cost this
codebase real time twice.
"""

from __future__ import annotations

import pathlib
import re
from typing import Dict, Iterable, List, Optional, Tuple

import pytest

from app.main import app

FRONTEND_API = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "api"

#: `api.get<Foo[]>('/path')` — the type argument is what the frontend asserts it gets.
TYPED_CALL = re.compile(
    r"api\.(get|post|put|patch|delete)\s*<([^>]*(?:<[^>]*>)?[^>]*)>\s*\(\s*([`'\"])([^`'\"]+)\3",
    re.S,
)
PATH_PARAM = re.compile(r"/\$\{[^}]+\}")
GLUED_SUFFIX = re.compile(r"(?<!/)\$\{[^}]+\}")

#: A paginated envelope carries `items` AND at least one pagination sibling. Treating
#: any object with an `items` field as an envelope was wrong: `SuggestedQuestionsResponse`
#: has `questions`, `items`, `context_summary` and `intelligence` — a plain object whose
#: payload happens to include a list — and the first run of this sweep reported it as a
#: mismatch that did not exist.
PAGINATION_SIBLINGS = {"total", "meta", "skip", "limit", "has_more", "hasMore", "page"}


def normalise(raw: str) -> str:
    path = raw.split("?")[0]
    return (GLUED_SUFFIX.sub("", PATH_PARAM.sub("/{param}", path)).rstrip("/")) or "/"


def _resolve_shape(schema, components, depth: int = 0) -> str:
    """array | envelope | object | unknown, following $ref."""
    if depth > 5 or not isinstance(schema, dict):
        return "unknown"
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        return _resolve_shape(components.get(name, {}), components, depth + 1)
    if schema.get("type") == "array":
        return "array"
    if schema.get("type") == "object" or "properties" in schema:
        props = set(schema.get("properties", {}))
        if "items" in props and props & PAGINATION_SIBLINGS:
            return "envelope"
        return "object"
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []):
            resolved = _resolve_shape(sub, components, depth + 1)
            if resolved != "unknown":
                return resolved
    return "unknown"


def _response_shapes() -> Dict[Tuple[str, str], str]:
    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    table: Dict[Tuple[str, str], str] = {}
    for path, operations in spec["paths"].items():
        key = re.sub(r"\{[^}]+\}", "{param}", path.rstrip("/")) or "/"
        for method, operation in operations.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            content = (operation.get("responses", {}).get("200", {}) or {}).get("content", {})
            schema = (content.get("application/json") or {}).get("schema")
            table[(key, method)] = (
                _resolve_shape(schema, components) if schema else "unknown"
            )
    return table


#: Finds `interface Name {...}` so a NAMED envelope type can be resolved to its body.
_INTERFACE = r"(?:export\s+)?interface\s+{name}\s*(?:extends[^{{]+)?\{{(?P<body>[^}}]*)\}}"


def _named_interface_body(name: str, sources: Iterable[str]) -> Optional[str]:
    """The body of `interface <name>`, searched across the api directory.

    Types are frequently declared in one client and used in another, so this does not
    restrict itself to the calling file.
    """
    if not re.fullmatch(r"\w+", name):
        return None
    pattern = re.compile(_INTERFACE.format(name=re.escape(name)))
    for source in sources:
        match = pattern.search(source)
        if match:
            return match.group("body")
    return None


def ts_shape(type_argument: str, sources: Iterable[str] = ()) -> str:
    """What the frontend's type argument asserts the payload looks like.

    NAMED ENVELOPES ARE RESOLVED, not just `Paginated<T>` and inline literals. The first
    version classified any bare identifier as "object", so `PostingPage` — an interface whose
    body is literally `{items, total, limit, truncated}` — was reported as a mismatch against
    an endpoint correctly returning an envelope. That is a false positive of the worst kind:
    it pushes whoever hits it toward renaming the type to satisfy the regex, or toward
    inlining a literal, neither of which makes the code more correct. The rule applied to the
    resolved body is the same one used for inline literals and for the OpenAPI schema.
    """
    t = type_argument.strip()
    if t.endswith("[]") or t.startswith("Array<"):
        return "array"
    if re.match(r"^(Paginated|List)\w*<", t):
        return "envelope"
    if t.startswith("{"):
        return "envelope" if "items" in t and any(s in t for s in PAGINATION_SIBLINGS) else "object"
    body = _named_interface_body(t, sources)
    if body is not None:
        return (
            "envelope"
            if "items" in body and any(sib in body for sib in PAGINATION_SIBLINGS)
            else "object"
        )
    return "object"


def _typed_calls() -> List[tuple]:
    found = []
    for file in sorted(FRONTEND_API.glob("*.ts")):
        if ".test." in file.name:
            continue
        source = file.read_text()
        for match in TYPED_CALL.finditer(source):
            method, type_arg, raw = match.group(1), match.group(2), match.group(4)
            if not raw.startswith("/"):
                continue
            line = source[: match.start()].count("\n") + 1
            found.append((file.name, line, method, raw, type_arg.strip()))
    return found


#: Every api client's text, so a named type declared in one file and used in another still
#: resolves. Read once at import; these are small files and the parametrisation needs them
#: before collection.
_API_SOURCES = [
    f.read_text() for f in sorted(FRONTEND_API.glob("*.ts")) if ".test." not in f.name
]

SHAPES = _response_shapes()
CALLS = [c for c in _typed_calls() if (normalise(c[3]), c[2]) in SHAPES]
CHECKABLE = [c for c in CALLS if SHAPES[(normalise(c[3]), c[2])] not in ("unknown",)]


class TestTheDetector:
    """It reported a false positive on its first run; these pin the correction."""

    def test_an_object_that_merely_contains_items_is_not_an_envelope(self):
        """`SuggestedQuestionsResponse` has `questions`, `items`, `context_summary`,
        `intelligence`. It is a plain object whose payload includes a list, and the
        frontend types it exactly that way."""
        schema = {"type": "object", "properties": {
            "questions": {}, "items": {}, "context_summary": {}, "intelligence": {}}}
        assert _resolve_shape(schema, {}) == "object"

    def test_items_plus_a_pagination_sibling_is_an_envelope(self):
        schema = {"type": "object", "properties": {"items": {}, "total": {}, "meta": {}}}
        assert _resolve_shape(schema, {}) == "envelope"

    def test_an_array_schema_is_an_array(self):
        assert _resolve_shape({"type": "array", "items": {}}, {}) == "array"

    def test_the_typescript_side_reads_the_same_way(self):
        assert ts_shape("Carrier[]") == "array"
        assert ts_shape("Array<Carrier>") == "array"
        assert ts_shape("PaginatedResponse<Vehicle>") == "envelope"
        assert ts_shape("SuggestedQuestionsResponse") == "object"
        assert ts_shape("{ items: Foo[]; total: number }") == "envelope"

    def test_a_named_envelope_interface_is_resolved(self):
        """The heuristic used to classify every bare identifier as "object", so a named
        envelope was a false positive that pushed the reader toward renaming the type to
        satisfy a regex instead of fixing anything."""
        source = """
        export interface PostingPage {
          items: Posting[];
          total: number;
          limit: number;
          truncated: boolean;
        }
        """
        assert ts_shape("PostingPage", [source]) == "envelope"

    def test_a_named_object_interface_is_still_an_object(self):
        source = "export interface Fanout { eventType: string; items: string[] }"
        # `items` with no pagination sibling is a payload that contains a list, not a page.
        assert ts_shape("Fanout", [source]) == "object"

    def test_an_unresolvable_name_stays_an_object(self):
        assert ts_shape("SomethingDeclaredElsewhere", []) == "object"


class TestTheSweepIsNotVacuous:
    def test_it_found_typed_calls(self):
        assert len(CHECKABLE) >= 50, (
            f"only {len(CHECKABLE)} typed calls resolvable against the spec; the sweep "
            f"is not reaching them"
        )

    def test_it_sees_both_shapes_somewhere(self):
        """If every endpoint resolved to the same shape, agreement would be trivial."""
        seen = {SHAPES[(normalise(c[3]), c[2])] for c in CHECKABLE}
        assert len(seen) >= 2, f"only one response shape observed: {seen}"


@pytest.mark.parametrize(
    "module,line,method,raw,type_arg",
    CHECKABLE,
    ids=[f"{m}:{ln}" for m, ln, _me, _r, _t in CHECKABLE],
)
def test_the_response_shape_matches_the_type(module, line, method, raw, type_arg):
    expected = SHAPES[(normalise(raw), method)]
    actual = ts_shape(type_arg, _API_SOURCES)
    assert actual == expected, (
        f"frontend/src/api/{module}:{line} types {method.upper()} {raw} as `{type_arg}` "
        f"({actual}), but the endpoint returns {expected}. An array typed as an envelope "
        f"reads `.items` as undefined and renders an empty list; an envelope typed as an "
        f"array throws `.map is not a function`. TypeScript cannot catch either — the "
        f"type argument is an assertion about JSON, not a checked fact."
    )
