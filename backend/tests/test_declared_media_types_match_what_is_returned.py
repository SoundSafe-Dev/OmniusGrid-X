"""A declared media type must be what the handler actually sends (FS-304).

FastAPI documents `application/json` for every route unless told otherwise, so a handler
returning a CSV is documented as JSON **by default and silently**. That matters here
because an SDK is generated from this schema across 375 paths (FS-252): a generated client
reading the schema will try to JSON-parse a spreadsheet, and the failure surfaces in the
caller's code with no hint that the contract was wrong.

BOTH DIRECTIONS HAVE HAPPENED IN THIS REPOSITORY — five downloads promising JSON, and an
export declaring `text/csv` while serving JSON — and both were fixed by hand, one at a
time, with nothing left behind to keep them fixed. Measured today: all seven file-returning
operations declare their type, and no route declares a file type it does not send. This
file is what makes that survive the next download endpoint.

THE DETECTOR IS THE HARD PART, and two versions of it were wrong before this one:

  * Reading only `inspect.getsource(route.endpoint)` for `FileResponse`/`StreamingResponse`
    found **4** of the 7. `compliance_reports.py` and `exports.py` build their responses
    through `_secure_file_response`/`_secure_streaming_response` helpers, so the handler
    body never names a response class. That is the FS-305 blind spot exactly, and it made
    the sweep report a clean schema over three endpoints it could not see.
  * Adding `Response(` to the pattern with a `\\b` after the paren matched nothing — a word
    boundary cannot follow `(` there — so five handlers that return
    `Response(content=..., media_type=XLSX_MEDIA_TYPE)` were reported as declaring a file
    type while returning JSON. Five false findings from one misplaced metacharacter.

Hence the vacuity class below, and hence AST rather than regex for the media types: the
constants are module-level names like `XLSX_MEDIA_TYPE`, and a text search returns the
name rather than the value.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from pathlib import Path

import pytest
from fastapi import routing

from app.main import app
from tests._route_tree import http_routes

API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"

#: Anything that puts bytes on the wire with a media type of its own — response classes,
#: the two local helpers that wrap them, and a bare `Response(...)`. The helpers are named
#: explicitly rather than followed: they take `media_type` as a parameter, so the call site
#: carries the value and that is what this needs to read.
_EMITTERS = {
    "FileResponse",
    "StreamingResponse",
    "PlainTextResponse",
    "HTMLResponse",
    "Response",
    "_secure_file_response",
    "_secure_streaming_response",
}

#: Constants like `XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-…"`. A media type is
#: nearly always too long to repeat, so the value lives in a module constant and the call
#: site names it — which is why this reads the module rather than the call.
_CONST = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*[\"']([a-z]+/[^\"']+)[\"']", re.M)


def _module_constants(module_name: str) -> dict[str, str]:
    path = API_DIR / f"{module_name}.py"
    if not path.exists():  # pragma: no cover - defensive
        return {}
    return dict(_CONST.findall(path.read_text()))


def _emitted_media_types(source: str, constants: dict[str, str]) -> tuple[bool, set[str]]:
    """(does it emit a body itself, the media types it can emit).

    A handler can emit without naming a type — `FileResponse(path)` infers from the
    filename, and `_secure_file_response(path, job.media_type, …)` passes a runtime value.
    Both are "emits, type unknown", which is a different verdict from "emits text/csv" and
    must not be collapsed into it.
    """
    emits, types = False, set()
    try:
        # `textwrap.dedent`, NOT `inspect.cleandoc`. cleandoc strips the first line's
        # indent and then the COMMON indent of lines 2+, so a two-line function
        # (`def f():` / `    return …`) has its body dedented to column 0 and the parse
        # raises IndentationError, which `except SyntaxError` below swallows into
        # "emits nothing".
        #
        # It did NOT break the real sweep. A decorated handler's source starts
        # `@router.get(...)` / `async def …` — both at column 0 — so the common indent of
        # lines 2+ is 0 and cleandoc left it alone. What broke was the synthetic input in
        # the vacuity tests, and only there. Worth stating precisely: the first version of
        # this comment claimed every handler came back empty, which would have been a much
        # worse bug and was not true. `test_there_are_enough_emitters` was passing
        # throughout, which is the evidence.
        #
        # dedent is still correct — it uses the common indent of ALL lines, so it handles
        # both shapes, and a helper defined inside a class would hit exactly the two-line
        # case.
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:  # pragma: no cover - defensive
        return False, set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in _EMITTERS:
            continue
        emits = True
        for kw in node.keywords:
            if kw.arg != "media_type":
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                types.add(kw.value.value)
            elif isinstance(kw.value, ast.Name) and kw.value.id in constants:
                types.add(constants[kw.value.id])
        # Positional media_type, as the two helpers take it.
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "/" in arg.value:
                types.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in constants:
                types.add(constants[arg.id])
    return emits, types


def _operations():
    """(method, path, emits, emitted_types, declared_types) for every documented op."""
    spec = app.openapi()
    out = []
    for route, path, methods in http_routes(app):
        if not isinstance(route, routing.APIRoute):
            continue
        try:
            source = inspect.getsource(route.endpoint)
        except (OSError, TypeError):  # pragma: no cover - defensive
            continue
        module = route.endpoint.__module__.rsplit(".", 1)[-1]
        emits, emitted = _emitted_media_types(source, _module_constants(module))
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            operation = (spec.get("paths", {}).get(path) or {}).get(method.lower())
            if not operation:
                continue
            declared = {
                key
                for code, response in (operation.get("responses") or {}).items()
                if str(code).startswith("2")
                for key in (response.get("content") or {})
            }
            out.append((method, path, emits, emitted, declared))
    return out


OPERATIONS = _operations()
EMITTERS = [op for op in OPERATIONS if op[2]]


class TestTheSweepIsNotVacuous:
    """Two earlier detectors passed while blind. These are the checks that caught them."""

    def test_it_sees_every_known_download(self):
        paths = {path for _, path, emits, _, _ in OPERATIONS if emits}
        expected = {
            "/api/v1/exports/telemetry/{asset_id}",
            "/api/v1/exports/jobs/{job_id}/download",
            "/api/v1/exports/deliveries/{job_id}/download",
            "/api/v1/compliance/reports/{job_id}/download",
            "/api/v1/compliance/reports/{job_id}/signed-download",
            "/api/v1/fleet/releases/{release_id}/bundle",
            "/api/v1/models/{model_id}/download",
        }
        missing = expected - paths
        assert not missing, (
            f"the emitter detector cannot see {sorted(missing)}. The first version read "
            f"only the handler body for a response CLASS and missed every endpoint that "
            f"builds its response through a helper — 3 of these 7"
        )

    def test_it_resolves_a_module_constant(self):
        """`media_type=XLSX_MEDIA_TYPE` must yield the value, not the name."""
        emits, types = _emitted_media_types(
            "def f():\n    return Response(content=b'', media_type=XLSX_MEDIA_TYPE)\n",
            {"XLSX_MEDIA_TYPE": "application/vnd.ms-excel"},
        )
        assert emits and types == {"application/vnd.ms-excel"}

    def test_a_bare_response_call_counts_as_emitting(self):
        """The regex version used `Response\\(` followed by `\\b` and matched nothing, so
        five handlers returning `Response(content=…, media_type=…)` were reported as
        declaring a file type while returning JSON."""
        emits, _ = _emitted_media_types("def f():\n    return Response(content=b'')\n", {})
        assert emits

    def test_an_ordinary_json_handler_does_not_count(self):
        emits, types = _emitted_media_types("def f():\n    return {'a': 1}\n", {})
        assert not emits and not types

    def test_there_are_enough_emitters_to_be_worth_checking(self):
        assert len(EMITTERS) >= 7, (
            f"only {len(EMITTERS)} body-emitting operations found; the detector is broken "
            f"and every assertion below would pass over nothing"
        )


def test_every_emitted_media_type_is_declared():
    """What the handler sends must appear in the schema.

    Undeclared means the schema says `application/json` and the client gets a spreadsheet.
    """
    undeclared = [
        f"{method} {path} sends {sorted(emitted - declared)} but the schema declares "
        f"{sorted(declared)}"
        for method, path, emits, emitted, declared in EMITTERS
        if emitted and (emitted - declared)
    ]
    assert not undeclared, (
        "these operations send a media type the schema does not document, so a generated "
        "client will try to parse the body as JSON:\n  " + "\n  ".join(sorted(undeclared))
    )


def test_no_operation_declares_a_media_type_it_cannot_send():
    """The other direction, which has also happened here.

    Only checked for handlers whose types are statically known: one that passes a runtime
    `media_type` (`job.media_type`) can legitimately send any of several declared types,
    and demanding otherwise would force those endpoints to under-declare.
    """
    overdeclared = []
    for method, path, emits, emitted, declared in OPERATIONS:
        extra = declared - {"application/json"}
        if not extra:
            continue
        if emits and not emitted:
            continue  # runtime media type; the declaration is the only record of the set
        if not emits:
            overdeclared.append(
                f"{method} {path} declares {sorted(extra)} but returns no body of its own"
            )
        elif extra - emitted:
            overdeclared.append(
                f"{method} {path} declares {sorted(extra - emitted)} which it never sends"
            )
    assert not overdeclared, (
        "these operations document a media type they do not produce — a client written "
        "against the schema will request or expect a format that never arrives:\n  "
        + "\n  ".join(sorted(overdeclared))
    )


def test_a_download_is_never_documented_as_json_only():
    """The headline case, asserted on its own so the failure message names it.

    This is what FastAPI does by default, so it is the state every new download endpoint
    starts in.
    """
    json_only = [
        f"{method} {path}"
        for method, path, emits, emitted, declared in EMITTERS
        if declared == {"application/json"}
    ]
    assert not json_only, (
        "these send a file or stream and are documented as application/json only — the "
        "FastAPI default, which is silent:\n  " + "\n  ".join(sorted(json_only))
    )
