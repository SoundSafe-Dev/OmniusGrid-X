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

SCOPE. Only calls whose parameter keys are statically resolvable — a literal `?a=b` or a
`params: { ... }` object literal. A `params: someVariable` cannot be read this way and is
counted and reported, not guessed at.
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
            obj = PARAMS_OBJECT.search(args)
            if obj:
                keys |= set(OBJECT_KEY.findall(obj.group(1)))
            elif PARAMS_VARIABLE.search(args):
                unresolvable += 1
                continue
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

    def test_it_reads_literal_query_keys(self):
        assert set(LITERAL_QUERY_KEY.findall("/x?entity_type=a&status=b")) == {
            "entity_type",
            "status",
        }


class TestTheSweepIsNotVacuous:
    def test_it_found_calls_that_send_parameters(self):
        assert len(CHECKABLE) >= 25, (
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
        assert UNRESOLVABLE <= 5, (
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
    unknown = sorted(set(keys) - declared)
    assert not unknown, (
        f"frontend/src/api/{module}:{line} sends {unknown} to {method.upper()} {raw}, "
        f"which declares {sorted(declared) or 'no query parameters'}. FastAPI ignores "
        f"unknown query parameters silently — the request succeeds and returns the "
        f"UNFILTERED result, which the caller then renders as though it were filtered. "
        f"If the parameter belongs in the body (a non-scalar type), send it there."
    )
