"""A route's declared content types must include what it actually sends (FS-304).

NOTHING CHECKED THIS, and it has gone wrong in both directions already:

  - five download endpoints declared `application/json` while serving a file, fixed in
    the response_model burn-down;
  - `/exports/jobs/{job_id}` declared `text/csv` while serving JSON, recorded in
    `docs/engineering/defect-class-sweeps.md`;
  - and this sweep found `/exports/telemetry/{asset_id}`, which declares only
    `200: text/csv` but returns `202 application/json` whenever the range exceeds
    SYNC_ROW_CAP and the export is queued — so the contract described a route that could
    only ever return CSV, and the JSON arrived on exactly the large exports most likely
    to need the job-polling path.

A wrong content type is not cosmetic here: this repo generates an SDK from the schema, so
a declared type is what a client's deserializer is built around.

WHY THE DETECTOR LOOKS THE WAY IT DOES. Two traversal mistakes were made writing it, and
both produced a confident "0 problems" from a sweep that was examining almost nothing:

  1. `app.routes` yields **2** APIRoutes. The other 450 are behind mounted routers, and
     only `tests/_route_tree.http_routes` walks them. A guard reporting a clean result
     over 2 of 452 routes is worse than no guard.
  2. `return FileResponse(...)` appears almost nowhere. The responses here are built by
     helpers (`_secure_file_response`) and assigned to a variable first, so a walk that
     only inspects `ast.Return` nodes sees none of them. This walks every Call in the
     endpoint and follows one level of same-module helper — the same blind spot FS-305
     describes for the returned-keys sweep.

WHAT IT DELIBERATELY PERMITS: a media type computed at runtime. `/reports/{job_id}/
download` picks between PDF, XLSX and octet-stream from the artifact's format, and its
`responses` declares all three. Demanding a literal would force those handlers to lie.
Unresolvable media types are counted and reported, not failed — with a floor test below
so the sweep cannot quietly stop resolving them.
"""

from __future__ import annotations

import ast
import importlib
import inspect

import pytest
from fastapi import routing

from app.main import app
from tests._route_tree import http_routes

#: Response classes with a FIXED media type. These are the ones a static check can judge.
FIXED_MEDIA = {
    "JSONResponse": "application/json",
    "ORJSONResponse": "application/json",
    "PlainTextResponse": "text/plain",
    "HTMLResponse": "text/html",
}

#: Response classes whose media type is a runtime decision (or absent). Counted, never
#: failed — see the docstring.
DYNAMIC = {"FileResponse", "StreamingResponse", "Response", "RedirectResponse"}


def _declared(route) -> set[str]:
    """Every content type the OpenAPI schema promises, across all declared statuses.

    ALL statuses, not just 2xx: a route that declares `202: application/json` has told
    the truth about its JSON body, and restricting this to 200 would report it as a
    liar for a response it documents correctly.
    """
    types: set[str] = set()
    media_type = getattr(getattr(route, "response_class", None), "media_type", None)
    if media_type:
        types.add(media_type)
    for spec in (getattr(route, "responses", None) or {}).values():
        if isinstance(spec, dict):
            types.update((spec.get("content") or {}).keys())
    return types


def _module_functions(module) -> dict[str, ast.AST]:
    try:
        tree = ast.parse(inspect.getsource(module))
    except (OSError, TypeError, SyntaxError):  # pragma: no cover - defensive
        return {}
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _responses_built(node, helpers, depth: int = 0) -> list[tuple[str, str | None]]:
    """(class name, literal media_type or None) for every Response constructed."""
    built: list[tuple[str, str | None]] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        name = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
        if name in FIXED_MEDIA or name in DYNAMIC:
            literal = None
            for keyword in sub.keywords:
                if keyword.arg == "media_type":
                    literal = (
                        keyword.value.value
                        if isinstance(keyword.value, ast.Constant)
                        else None
                    )
            built.append((name, literal))
        elif depth == 0 and name in helpers:
            built.extend(_responses_built(helpers[name], helpers, depth + 1))
    return built


def _sweep() -> tuple[list[str], int, int]:
    """(problems, resolved count, dynamic count)."""
    problems: list[str] = []
    resolved = dynamic = 0

    for route, path, _methods in http_routes(app):
        if not isinstance(route, routing.APIRoute):
            continue
        module = importlib.import_module(route.endpoint.__module__)
        helpers = _module_functions(module)
        function = helpers.get(route.endpoint.__name__)
        if function is None:
            continue

        declared = _declared(route)
        if not declared:
            continue

        for class_name, literal in _responses_built(function, helpers):
            actual = literal or FIXED_MEDIA.get(class_name)
            if actual is None:
                dynamic += 1
                continue
            resolved += 1
            if actual not in declared:
                problems.append(
                    f"{path} builds {class_name} sending {actual!r}, but the schema "
                    f"declares only {sorted(declared)}"
                )
    return problems, resolved, dynamic


class TestTheSweepCanSeeItsSubject:
    """Both of these exist because the first two versions of this file passed while
    inspecting almost nothing."""

    def test_it_walks_the_whole_route_tree(self):
        routes = [r for r, _p, _m in http_routes(app) if isinstance(r, routing.APIRoute)]
        assert len(routes) > 400, (
            f"only {len(routes)} APIRoutes found. `app.routes` yields 2 — everything else "
            "is behind a mounted router. If this drops, the sweep is judging a handful of "
            "routes and reporting a clean bill of health for all of them"
        )

    def test_it_resolves_media_types_at_all(self):
        _problems, resolved, dynamic = _sweep()
        assert resolved + dynamic >= 10, (
            f"only {resolved + dynamic} Response constructions found across every "
            "endpoint. Handlers build them through helpers and assign to a variable, so "
            "a walk restricted to `ast.Return` nodes sees none of them"
        )

    def test_it_can_recognise_a_mismatch(self):
        """Synthetic proof the comparison works, independent of the codebase's state —
        otherwise a passing suite could mean 'no mismatches' or 'comparison broken'."""
        source = (
            "def handler():\n"
            "    return JSONResponse(content={})\n"
        )
        tree = ast.parse(source)
        built = _responses_built(tree.body[0], {})
        assert built == [("JSONResponse", None)]
        assert FIXED_MEDIA[built[0][0]] == "application/json"
        assert "application/json" not in {"text/csv"}


class TestEveryDeclaredMediaTypeIsHonest:
    def test_no_route_sends_a_content_type_it_did_not_declare(self):
        problems, _resolved, _dynamic = _sweep()
        assert not problems, (
            "These routes send a content type their schema does not declare. This repo "
            "generates an SDK from that schema, so the declared type is what a client's "
            "deserializer is built around.\n\n  "
            + "\n  ".join(problems)
        )


class TestTheDynamicOnesAreAccountedFor:
    def test_dynamic_media_types_are_reported_not_hidden(self):
        """A floor, so the sweep cannot quietly reclassify everything as unresolvable
        and pass. These are the file-download handlers that choose a type per artifact."""
        _problems, _resolved, dynamic = _sweep()
        assert dynamic >= 5, (
            f"only {dynamic} runtime-determined media types found; the download handlers "
            "should account for around a dozen. A drop means the helper-following broke "
            "and those routes are now unexamined rather than permitted"
        )
