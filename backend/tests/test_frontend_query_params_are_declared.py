"""A query parameter the frontend sends must be one the endpoint declares.

WHY THIS IS THE DANGEROUS HALF. `test_frontend_calls_real_endpoints.py` checks that the
path exists. This checks what is sent to it, and the failure mode is quieter: **FastAPI
ignores unknown query parameters silently**. A misspelled or invented filter does not
error — the endpoint returns the UNFILTERED set and the caller renders it as a filtered
result. Nobody sees a stack trace; they see the wrong rows.

The frontend suite cannot catch this either, for the reason in the sibling file:
`VITE_USE_MOCK='true'` is forced in `src/test/setup.ts`, so every test takes the mock
branch and the real request is never assembled.

WHAT IT FOUND. 37 calls that send resolvable query keys; two wrong, in different ways:

`yard.getDockDoors` sent `workcell_id`, which `GET /api/v1/yard/dock/doors` does not
declare — and `dock_doors` has no workcell column, so it could never have been honoured.
Only the mock branch, filtering fixture data on a field the real model lacks, made the
feature look implemented.

`nlpCorrelation.chat` sent `conversation_history` as a query parameter with a `null`
body. The handler declares it `Optional[List[Dict[str, str]]]`, and FastAPI reads complex
types from the BODY — so the server received `None` every time, while the endpoint's
docstring promised it "maintains conversation context for multi-turn queries." It had no
context to maintain. This guard flags the query/body confusion; the fix moved it to the
body.

The same sweep surfaced a third thing it does not itself assert: **four yard endpoints
took `organization_id` as a REQUIRED client-supplied query parameter** and used it
directly in the WHERE clause — the IDOR shape `app/core/tenant.py` exists to prevent,
with RLS the only thing standing between it and a cross-tenant read. It was also plain
broken: no frontend call sent it, so every one got a 422. They now derive the org from
the token, which is covered by `test_yard_tenant_scoping_realdb.py`.

SCOPE. Parameter keys are resolved from a literal `?a=b`, a `params: { ... }` object
literal (including one inside a ternary), or — added after the blind spot below — a
`params` VARIABLE traced back to its local `const` object, its later `params.x =`
assignments, or the type of the function parameter it came from. Anything still
unresolvable is counted and reported, not guessed at.

THE BLIND SPOT, AND WHAT IT HID. The first version matched only an object literal or a
bare variable, so `{ params }` shorthand and `params: cond ? {…} : undefined` were
neither checked NOR counted — they vanished from the sweep, and its printed coverage
number said nothing was missing. Two live defects were sitting in that gap:

  * `workcellsApi.list` sent `organization_id` to `GET /api/v1/workcells/`, which
    declares only `skip` and `limit` — a filter that never filtered.
  * `authApi.getUsers` sent `skip` and `limit` to `GET /api/v1/auth/users`, which
    declared no query parameters at all, so every caller received the whole
    organization while believing it had asked for a page. Fixed by giving the handler
    real pagination; see `test_auth_users_pagination_realdb.py`.

CASING. `transformRegistry.ts` rewrites request params camelCase -> snake_case for
REGISTERED URL prefixes only. A key under such a prefix is therefore compared in both
forms, because `historian.query` sending `assetId` to an endpoint declaring `asset_id`
is correct — the interceptor converts it — and reporting it would have been a fabricated
defect. Prefixes are read from the frontend source rather than hardcoded, so a
registration removed there tightens this check automatically.
"""

from __future__ import annotations

import pathlib
import re
from typing import Dict, List, Set, Tuple

import pytest

from app.main import app

FRONTEND_API = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "api"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
CALL_START = re.compile(r"api\.(get|post|put|patch|delete)\s*(?:<[^;{]*?>)?\s*\(", re.S)
URL_IN_ARGS = re.compile(r"[`'\"]([^`'\"]+)[`'\"]")
PARAMS_OBJECT = re.compile(r"params\s*:\s*\{([^{}]*)\}", re.S)
PARAMS_VARIABLE = re.compile(r"params\s*:\s*[A-Za-z_$][\w$]*\s*[,}]")
#: `params: cond ? { a: 1 } : undefined` — an object literal inside a conditional.
#:
#: THIS WAS A BLIND SPOT, and it hid a real finding. The two patterns above match an
#: object literal or a bare variable; a ternary is neither, so such a call was not
#: checked AND not counted as skipped — it simply vanished from the sweep.
#: `workcellsApi.list` sent `organization_id` that way to an endpoint declaring only
#: `skip` and `limit`, and this guard reported nothing. Any object literal appearing
#: anywhere in the params expression is now read.
PARAMS_ANY_OBJECT = re.compile(r"params\s*:\s*[^,}]*?\{([^{}]*)\}", re.S)
#: Object KEYS only — `key:` or a shorthand `key` closed by a comma or the brace.
#: Matching identifiers loosely also catches the VALUES, which turned `{ intake_id:
#: intakeId }` into two parameters and reported a defect that was not there.
OBJECT_KEY = re.compile(r"(?:^|,)\s*([A-Za-z_$][\w$]*)\s*(?::|(?=\s*(?:,|$)))")
LITERAL_QUERY_KEY = re.compile(r"[?&]([A-Za-z_][\w]*)=")
PATH_PARAM = re.compile(r"/\$\{[^}]+\}")
GLUED_SUFFIX = re.compile(r"(?<!/)\$\{[^}]+\}")


def _balanced(source: str, open_paren: int) -> str:
    depth = 0
    for i in range(open_paren, len(source)):
        if source[i] in "([{":
            depth += 1
        elif source[i] in ")]}":
            depth -= 1
            if depth == 0:
                return source[open_paren : i + 1]
    return ""


def normalise(raw: str) -> str:
    path = raw.split("?")[0]
    return (GLUED_SUFFIX.sub("", PATH_PARAM.sub("/{param}", path)).rstrip("/")) or "/"


def _declared_query_params() -> Dict[Tuple[str, str], Set[str]]:
    table: Dict[Tuple[str, str], Set[str]] = {}
    for path, operations in app.openapi()["paths"].items():
        key = re.sub(r"\{[^}]+\}", "{param}", path.rstrip("/")) or "/"
        for method, operation in operations.items():
            if method.lower() not in HTTP_METHODS:
                continue
            table[(key, method.lower())] = {
                p["name"] for p in operation.get("parameters", []) if p.get("in") == "query"
            }
    return table


#: Keys of a TypeScript type literal or interface body — `key:` / `key?:`.
TYPE_KEY = re.compile(r"(?:^|[,;{])\s*([A-Za-z_$][\w$]*)\s*\??\s*:")
#: The shorthand `{ params }`, whose variable name is just `params`.
PARAMS_SHORTHAND = re.compile(r"\{\s*params\s*[,}]")
#: `params: someVariable` — the variable's own name.
PARAMS_NAMED = re.compile(r"params\s*:\s*([A-Za-z_$][\w$]*)\s*[,}]")
CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
#: Query keys the backend is not expected to declare, with the reason. Keep this
#: SHORT — every entry is a check that no longer runs.
DELIBERATELY_UNDECLARED = {
    "_t": "cache-busting timestamp; ignored server-side by design, which is the point",
}


def _registered_prefixes() -> List[str]:
    """URL prefixes whose request params the axios seam converts to snake_case.

    Read from the frontend rather than hardcoded: `registerTransform` calls are the
    single source of truth, and a prefix removed there must tighten this check rather
    than leave a stale exemption behind.
    """
    prefixes: List[str] = []
    for file in FRONTEND_API.glob("*.ts"):
        if ".test." in file.name:
            continue
        prefixes += re.findall(r"registerTransform\(\s*'([^']+)'", file.read_text())
    return prefixes


def _out_aliases() -> Dict[str, str]:
    """TS field name -> wire field name, for divergences beyond casing."""
    source = (FRONTEND_API / "transform.ts")
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
    """Every name this key could legitimately arrive under.

    Outside a registered prefix that is the key itself. Inside one the interceptor
    applies `outAliases` then camelToSnake, so both forms are accepted — anything
    narrower reports the conversion itself as a defect.
    """
    path = url.split("?")[0]
    if not any(path == p or path.startswith(p + "/") for p in REGISTERED):
        return {key}
    return {key, _snake(key), _snake(OUT_ALIASES.get(key, key))}


def _balanced_from(source: str, open_bracket: int) -> str:
    return _balanced(source, open_bracket)


def _enclosing_function(source: str, pos: int) -> Tuple[str, str]:
    """(signature, body) of the innermost function block containing `pos`.

    Scoped rather than file-wide on purpose: three functions in `analysisSessions.ts`
    each build a local `params`, and merging their keys would invent parameters that no
    single call sends.
    """
    depth, open_index = 0, -1
    for i in range(pos, -1, -1):
        if source[i] == "}":
            depth += 1
        elif source[i] == "{":
            if depth == 0:
                open_index = i
                break
            depth -= 1
    if open_index < 0:
        return "", ""
    body = _balanced_from(source, open_index)
    signature = ""
    close = source.rfind(")", max(0, open_index - 400), open_index)
    if close > 0:
        depth = 0
        for i in range(close, -1, -1):
            if source[i] in ")]}":
                depth += 1
            elif source[i] in "([{":
                depth -= 1
                if depth == 0:
                    signature = source[i : close + 1]
                    break
    return signature, body


def _resolve_variable(source: str, pos: int, name: str) -> Set[str]:
    """Keys of a params variable, from whichever of four shapes declares it."""
    signature, body = _enclosing_function(source, pos)
    keys: Set[str] = set()
    escaped = re.escape(name)

    # 1. a function parameter with an inline type literal: `(opts: { hours?: number })`
    inline = re.search(rf"\b{escaped}\s*\??\s*:\s*\{{", signature)
    if inline:
        keys |= set(TYPE_KEY.findall(_balanced_from(signature, inline.end() - 1)))

    # 2. a function parameter typed by a named interface: `(params: RULListParams)`
    named = re.search(rf"\b{escaped}\s*\??\s*:\s*([A-Z][\w]*)", signature)
    if named:
        declaration = re.search(rf"(?:interface|type)\s+{named.group(1)}\b[^{{]*\{{", source)
        if declaration:
            keys |= set(TYPE_KEY.findall(_balanced_from(source, declaration.end() - 1)))

    # 3. a local object: `const params: any = { limit, offset }`
    local = re.search(rf"(?:const|let|var)\s+{escaped}\s*(?::[^=]+?)?=\s*\{{", body)
    if local:
        keys |= set(OBJECT_KEY.findall(_balanced_from(body, local.end() - 1)[1:-1]))

    # 4. keys added afterwards: `if (status) params.status = status`
    keys |= set(re.findall(rf"\b{escaped}\.([A-Za-z_$][\w$]*)\s*=(?!=)", body))
    return keys


def _split_top_level(args: str) -> List[str]:
    """Split a call's argument list on top-level commas."""
    parts, depth, current = [], 0, []
    for char in args[1:-1]:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _config_argument(method: str, args: str) -> str:
    """The axios argument that can carry `params`, by position.

    `get`/`delete` take (url, config); `post`/`put`/`patch` take (url, BODY, config).
    Scanning the whole call would read a body field named `params` as a query
    parameter — `platformCorrelation.attach` posts `{ source_type, params }` as its
    body, and treating that as a query string would have invented a defect.
    """
    parts = _split_top_level(args)
    index = 2 if method in {"post", "put", "patch"} else 1
    return parts[index] if len(parts) > index else ""


def _calls_sending_params() -> Tuple[List[tuple], int]:
    """((module, line, method, url, keys), count of unresolvable `params: var`)."""
    found, unresolvable = [], 0
    for file in sorted(FRONTEND_API.glob("*.ts")):
        if ".test." in file.name:
            continue
        source = file.read_text()
        for match in CALL_START.finditer(source):
            args = _balanced(source, match.end() - 1)
            url_match = URL_IN_ARGS.search(args)
            if not url_match or not url_match.group(1).startswith("/"):
                continue
            raw = url_match.group(1)
            keys = set(LITERAL_QUERY_KEY.findall(raw))
            args = _config_argument(match.group(1), args)
            obj = PARAMS_OBJECT.search(args) or PARAMS_ANY_OBJECT.search(args)
            if obj:
                keys |= set(OBJECT_KEY.findall(obj.group(1)))
            elif "params" in args:
                # A variable. Trace it to its declaration; only count it as
                # unresolvable when that genuinely fails, so the reported coverage
                # reflects what was checked rather than what was attempted.
                named = PARAMS_NAMED.search(args)
                variable = named.group(1) if named else (
                    "params" if PARAMS_SHORTHAND.search(args) else None
                )
                resolved = _resolve_variable(source, match.start(), variable) if variable else set()
                if not resolved:
                    unresolvable += 1
                    continue
                keys |= resolved
            if keys:
                line = source[: match.start()].count("\n") + 1
                found.append((file.name, line, match.group(1), raw, sorted(keys)))
    return found, unresolvable


DECLARED = _declared_query_params()
CALLS, UNRESOLVABLE = _calls_sending_params()
CHECKABLE = [c for c in CALLS if (normalise(c[3]), c[2]) in DECLARED]


class TestTheExtractor:
    """Every assertion below depends on it, and its first version read object VALUES
    as parameter names."""

    def test_it_reads_keys_not_values(self):
        keys = set(OBJECT_KEY.findall(" intake_id: intakeId "))
        assert keys == {"intake_id"}, f"got {keys} — values are being read as keys"

    def test_it_reads_shorthand_keys(self):
        assert set(OBJECT_KEY.findall(" severity ")) == {"severity"}
        assert set(OBJECT_KEY.findall(" limit, offset ")) == {"limit", "offset"}

    def test_it_reads_an_object_literal_inside_a_conditional(self):
        """`params: orgId ? { organization_id: orgId } : undefined`. Neither an object
        literal nor a bare variable, so the original two patterns skipped it entirely —
        which is how workcellsApi.list kept sending a parameter the endpoint had never
        declared."""
        args = "'/api/v1/workcells/', { params: organizationId ? { organization_id: organizationId } : undefined }"
        obj = PARAMS_OBJECT.search(args) or PARAMS_ANY_OBJECT.search(args)
        assert obj is not None, "a conditional params object is still invisible"
        assert "organization_id" in set(OBJECT_KEY.findall(obj.group(1)))

    def test_it_traces_a_local_const_and_its_later_assignments(self):
        """The `{ params }` shape that hid two defects. Both halves matter: the object
        literal and the conditional `params.status = status` below it."""
        source = """
        export async function listSessions(limit: number, status?: string) {
          const params: any = { limit: limit.toString(), offset: 0 };
          if (status) { params.status = status; }
          const r = await api.get('/api/v1/nlp/sessions', { params });
        }
        """
        keys = _resolve_variable(source, source.index("api.get"), "params")
        assert {"limit", "offset", "status"} <= keys, f"got {keys}"

    def test_it_traces_a_typed_function_parameter(self):
        source = """
        getAssessment: async (assetId: string, opts: { hours?: number; notify?: boolean } = {}) => {
          const r = await api.get(`/api/v1/rul/${assetId}`, { params: opts });
        }
        """
        keys = _resolve_variable(source, source.index("api.get"), "opts")
        assert keys == {"hours", "notify"}, f"got {keys}"

    def test_it_traces_a_named_interface(self):
        source = """
        export interface RULListParams { hours?: number; limit?: number; offset?: number; }
        listAssessments: async (params: RULListParams = {}) => {
          const r = await api.get('/api/v1/rul', { params });
        }
        """
        keys = _resolve_variable(source, source.index("api.get"), "params")
        assert keys == {"hours", "limit", "offset"}, f"got {keys}"

    def test_it_does_not_merge_params_from_a_sibling_function(self):
        """`analysisSessions.ts` builds a local `params` in three functions. Reading the
        file globally would attribute every key to every call and invent defects."""
        source = """
        function a() { const params = { alpha: 1 }; api.get('/x', { params }); }
        function b() { const params = { beta: 2 }; api.get('/y', { params }); }
        """
        keys = _resolve_variable(source, source.index("api.get('/y'"), "params")
        assert keys == {"beta"}, f"leaked across functions: {keys}"

    def test_an_unresolvable_variable_still_resolves_to_nothing(self):
        """The counter must stay honest — a variable with no reachable declaration is
        counted, not silently treated as sending no parameters."""
        source = "function f(params) { api.get('/x', { params }); }"
        assert _resolve_variable(source, source.index("api.get"), "params") == set()

    def test_a_post_body_is_not_read_as_a_query_string(self):
        """axios `post(url, BODY, config)`. `platformCorrelation.attach` posts
        `{ source_type, params }` as its body; scanning the whole call would read those
        as query parameters and report a defect against correct code."""
        args = "(`/api/v1/nlp/sessions/${id}/platform-data`, { source_type: t, params })"
        assert _config_argument("post", args).strip() == ""

    def test_a_get_config_is_still_read(self):
        """The other direction — the positional rule must not blind the sweep."""
        args = "('/api/v1/rul', { params: { hours: 1 } })"
        assert "params" in _config_argument("get", args)

    def test_a_post_config_in_third_position_is_read(self):
        args = "('/x', { body: 1 }, { params: { limit: 5 } })"
        assert "limit" in _config_argument("post", args)

    def test_it_reads_literal_query_keys(self):
        assert set(LITERAL_QUERY_KEY.findall("/x?entity_type=a&status=b")) == {
            "entity_type",
            "status",
        }


class TestTheCasingSeamIsRespected:
    """`historian.query` sends `assetId` to an endpoint declaring `asset_id`. That is
    correct — the axios interceptor converts it — and flagging it would have been a
    fabricated defect reported against working code."""

    def test_a_registered_prefix_accepts_the_snake_case_form(self):
        assert "/api/v1/historian" in REGISTERED, (
            "the historian prefix is no longer registered; either the seam changed or "
            "this exemption is now hiding a real mismatch"
        )
        assert "asset_id" in _wire_forms("/api/v1/historian/query", "assetId")

    def test_an_unregistered_prefix_does_not(self):
        """The exemption must not leak. `/api/v1/auth` is on the never-register list,
        so a camelCase key there really would arrive as written."""
        assert "/api/v1/auth" not in REGISTERED
        assert _wire_forms("/api/v1/auth/users", "someKey") == {"someKey"}

    def test_the_historian_call_is_actually_in_the_sweep(self):
        """Without this the two assertions above could hold while the call itself was
        never reached."""
        assert any(m == "historian.ts" for m, _l, _me, _r, _k in CHECKABLE), (
            "no historian call is being checked; the casing exemption guards nothing"
        )


class TestTheSweepIsNotVacuous:
    def test_it_found_calls_that_send_parameters(self):
        assert len(CHECKABLE) >= 40, (
            f"only {len(CHECKABLE)} checkable param-sending calls found; the sweep is "
            f"not reaching them and would pass while checking nothing"
        )

    def test_a_known_parameter_is_declared(self):
        """If the spec lookup could not confirm a parameter that definitely exists, a
        green run would mean nothing."""
        assert "severity" in DECLARED[("/api/v1/alarms/active", "get")]

    def test_an_invented_parameter_is_not_declared(self):
        """Proves the check can fail."""
        assert "definitely_not_a_param" not in DECLARED[("/api/v1/alarms/active", "get")]

    def test_unresolvable_calls_are_reported_not_hidden(self, capsys):
        """A `params: someVariable` cannot be read statically. Silently skipping them
        would let coverage erode invisibly, so the number is printed."""
        with capsys.disabled():
            print(
                f"\n  query-param sweep: {len(CHECKABLE)} calls checked, "
                f"{UNRESOLVABLE} skipped (params passed as a variable)"
            )
        assert UNRESOLVABLE <= 2, (
            f"{UNRESOLVABLE} calls pass params as a variable and cannot be checked; "
            f"if this keeps growing the sweep stops meaning much"
        )


@pytest.mark.parametrize(
    "module,line,method,raw,keys",
    CHECKABLE,
    ids=[f"{m}:{ln}" for m, ln, _meth, _raw, _k in CHECKABLE],
)
def test_every_query_parameter_is_declared(module, line, method, raw, keys):
    declared = DECLARED[(normalise(raw), method)]
    unknown = sorted(
        key
        for key in keys
        if key not in DELIBERATELY_UNDECLARED and not (_wire_forms(raw, key) & declared)
    )
    assert not unknown, (
        f"frontend/src/api/{module}:{line} sends {unknown} to {method.upper()} {raw}, "
        f"which declares {sorted(declared) or 'no query parameters'}. FastAPI ignores "
        f"unknown query parameters silently — the request succeeds and returns the "
        f"UNFILTERED result, which the caller then renders as though it were filtered. "
        f"If the parameter belongs in the body (a non-scalar type), send it there."
    )
