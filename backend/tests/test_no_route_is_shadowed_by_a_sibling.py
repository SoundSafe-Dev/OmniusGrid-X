"""A literal path may not be swallowed by a parameterised sibling declared before it (FS-739).

FastAPI matches routes in DECLARATION ORDER. So this pair, in this order, is a dead endpoint:

    @router.get("/{registry_id}")     # line 77
    ...
    @router.get("/correlations")      # line 323 — never reached

`GET /api/v1/registries/correlations` arrived at the by-id handler with
`registry_id="correlations"`, failed UUID parsing and answered **422**, for as long as the
route had existed. It could not be noticed from either side: `POST /correlations` works,
because no `POST /{registry_id}` exists to shadow it, so correlations were creatable and
never listable — an API write-only for one feature, with neither half broken on its own.

HOW IT SURFACED, because the route there is the point. The contract gate reported
`UnsupportedMethodResponse` on 22 operations — "unsupported method PUT returned 422,
expected 405" — which reads like a schemathesis nicety about status codes. Twenty-one of
the 22 are exactly that: a literal path beside a parameterised sibling, where a method the
literal does not declare falls through to the sibling and 422s instead of 405ing. Harmless,
and not worth contorting the router for. The twenty-second was a dead endpoint. A check
worth dismissing 21 times out of 22 still had one real defect in it.

WHAT THIS ASSERTS, and what it deliberately does not. Only the dangerous case: same method,
same segment count, literal declared AFTER the parameter that would capture it. That is the
one where a request cannot reach its handler. The 21 different-method pairs are recorded in
`SHADOWED_BY_METHOD_ONLY` below with the reason, because they are real facts about the
router that a reader will otherwise rediscover here.
"""

from __future__ import annotations

import pathlib

import pytest

from tests._route_tree import DOC_PATHS, IMPLICIT_METHODS, flatten


def _ordered_operations() -> list[tuple[str, str, int]]:
    """(path, method, declaration index) in the order FastAPI will match them."""
    from app.main import app

    out: list[tuple[str, str, int]] = []
    for route, prefix in flatten(app.routes):
        path = prefix + getattr(route, "path", "")
        if path in DOC_PATHS:
            continue
        for method in sorted(getattr(route, "methods", None) or []):
            if method in IMPLICIT_METHODS:
                continue
            out.append((path, method, len(out)))
    return out


def _shadowed() -> list[tuple[str, str, str]]:
    """Literal routes a parameterised sibling declared earlier will capture."""
    ops = _ordered_operations()
    first: dict[tuple[str, str], int] = {}
    for path, method, index in ops:
        first.setdefault((path, method), index)

    found = []
    for literal, method, literal_index in ops:
        segments = literal.split("/")
        for other, other_method, other_index in ops:
            if other == literal or other_method != method:
                continue
            other_segments = other.split("/")
            if len(other_segments) != len(segments):
                continue
            # Exactly one differing segment, and it is a parameter on the other side.
            differing = [
                i for i, (a, b) in enumerate(zip(segments, other_segments)) if a != b
            ]
            if len(differing) != 1:
                continue
            i = differing[0]
            if not other_segments[i].startswith("{") or segments[i].startswith("{"):
                continue
            if other_index < literal_index:
                found.append((literal, method, other))
    return found


#: The 21 different-method pairs, kept as a fact rather than an exemption list.
#:
#: A literal path and a parameterised sibling coexist safely as long as the literal is
#: declared first — a request to the literal reaches its own handler. What still happens is
#: that a method the LITERAL does not declare falls through to the sibling: `PUT
#: /yard/trailers/checkin` matches `PUT /yard/trailers/{trailer_id}` and answers 422 for an
#: unparseable UUID, where the contract promises 405.
#:
#: NOT FIXED, deliberately. Making those 405 would mean either declaring stub handlers for
#: every method on every literal path, or constraining every path parameter with a routing
#: converter — a change to 546 operations' matching behaviour, and to the generated SDK, to
#: convert one honest error code into another. The behaviour is correct; the status code is
#: imprecise. Recorded in `docs/engineering/api-contract-gate.md` as a known residue with
#: this reasoning, which is what a ratchet is for.
SHADOWED_BY_METHOD_ONLY = 21


class TestTheMeasurementIsReal:
    def test_the_route_tree_is_walked(self):
        """`app.routes` holds lazy `_IncludedRouter` containers — a walk that does not
        recurse sees a handful of routes and passes over nothing."""
        ops = _ordered_operations()
        assert len(ops) > 500, (
            f"only {len(ops)} operations flattened; the app serves ~546. The walk is not "
            f"recursing and every assertion here would be vacuous."
        )

    def test_the_detector_finds_a_known_pair(self):
        """A literal beside a parameterised sibling must be VISIBLE to the pair-finder,
        or the shadow check below is asserting over an empty set."""
        ops = _ordered_operations()
        paths = {p for p, _m, _i in ops}
        assert "/api/v1/registries/correlations" in paths
        assert "/api/v1/registries/{registry_id}" in paths

    def test_the_detector_would_catch_a_reversal(self):
        """Mutation, in-process: reverse the declaration order of the pair this file was
        written for and the shadow check must fire. Without this the check could be
        matching nothing at all and still pass."""
        ops = [
            ("/api/v1/registries/{registry_id}", "GET", 0),
            ("/api/v1/registries/correlations", "GET", 1),
        ]
        found = []
        for literal, method, literal_index in ops:
            for other, other_method, other_index in ops:
                if other == literal or other_method != method:
                    continue
                a, b = literal.split("/"), other.split("/")
                if len(a) != len(b):
                    continue
                differing = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
                if len(differing) != 1:
                    continue
                i = differing[0]
                if b[i].startswith("{") and not a[i].startswith("{") and other_index < literal_index:
                    found.append(literal)
        assert found == ["/api/v1/registries/correlations"], (
            f"the shadow rule did not fire on a deliberately reversed pair: {found}"
        )


class TestNoEndpointIsUnreachable:
    def test_no_literal_path_is_captured_by_an_earlier_parameter(self):
        shadowed = _shadowed()
        assert not shadowed, (
            "these routes cannot be reached — FastAPI matches in declaration order, and a "
            "parameterised sibling declared earlier captures the literal segment:\n  "
            + "\n  ".join(
                f"{method} {literal}  <-- captured by {other}"
                for literal, method, other in shadowed
            )
            + "\n\nMove the literal path ABOVE the parameterised one in its router. A "
            "UUID-typed parameter makes this a 422; a `str`-typed one routes the request "
            "to the wrong handler with no error at all."
        )
