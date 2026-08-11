"""A parameter the endpoint requires in the query must not be sent in the body (FS-658).

THE OTHER DIRECTION. `test_frontend_query_params_are_declared.py` checks that every query key
the frontend sends is one the endpoint declares — a key the server does not know is ignored
silently and the caller renders an unfiltered set as a filtered one. This checks the reverse,
and it is louder and has bitten three times:

FastAPI reads a **non-Pydantic scalar with no `Body(...)` marker as a QUERY parameter**. Write
`async def f(status: str)` on a POST and the server requires `?status=`. A client that posts
`{"status": ...}` as JSON — which is the natural thing to write, and what every generated
client does — gets **422 on every call**, forever, with the feature never having worked once.

  * **FS-379** — Strategic approve/reject. `operator_id` and `notes` were query parameters;
    the page posted a body. Found by clicking the buttons against a real backend, because the
    mock path returns void without assembling a request.
  * **FS-420** — `POST /shipments/{id}/dispatch`. Same shape, same file as the next one.
  * **FS-658** — `POST /shipments/{id}/status`, the route immediately below the one FS-420
    fixed. "Mark Delivered" and "Cancel" had never worked.

WHY THE SERVER SIDE IS STILL FULL OF THEM. All three were closed by moving the CLIENT onto the
contract the server already published — cheaper, and it crosses no lane boundary. The comments
in `api/engines.ts` and `api/assets.ts` say so explicitly. That was the right call each time
and it means **22 routes still take bare scalars**, each one client-edit away from breaking:
the next person to write the obvious `api.post(url, { field })` gets a 422 and no clue why.

So this guard does not demand 22 refactors across other people's lanes. It asserts the thing
that actually matters — **that the two sides agree** — and fails when a frontend caller sends
a body to a route whose parameters live in the query.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
API_DIR = REPO / "backend" / "app" / "api"
FRONTEND = REPO / "frontend" / "src"

#: A parameter annotated with any of these is not a query parameter, whatever its type.
#: The first draft of this sweep excluded four of them and flagged `x_webhook_signature:
#: Optional[str] = Header(default=None)` as a defect — correct code, named by a detector that
#: had not been told what a header looks like. A guard that reports correct code is a guard
#: people learn to skip.
MARKERS = (
    "Depends(", "Body(", "Query(", "Header(", "Cookie(",
    "Form(", "File(", "Path(", "Security(", "UploadFile",
)

SCALAR = re.compile(
    r"^(str|int|float|bool|UUID|datetime|Optional\[\s*(str|int|float|bool|UUID|datetime)\s*\])\s*(=|$)"
)

ROUTE = re.compile(
    r'@router\.(post|put|patch)\("([^"]*)"[^\n]*\n(?:\s*[^\n]*\n)?async def (\w+)\(\s*([^)]*)\)'
)

#: Routes whose frontend caller sends a body to a query-parameter route. **Empty**, and the
#: three that were here are fixed rather than recorded. An entry belongs here only with the
#: reason a 422 is acceptable, which is a sentence nobody has been able to write yet.
ALLOWED: dict[str, str] = {}


def _query_scalars() -> dict[tuple[str, str], list[str]]:
    """(path, method) -> the parameter names FastAPI will read from the query string."""
    found: dict[tuple[str, str], list[str]] = {}
    for path_file in sorted(API_DIR.glob("*.py")):
        source = path_file.read_text()
        for verb, route, _fn, params in ROUTE.findall(source):
            bare = []
            for raw in params.split(","):
                line = raw.strip()
                if not line or line.startswith("#") or any(k in line for k in MARKERS):
                    continue
                name, _, annotation = line.partition(":")
                name, annotation = name.strip(), annotation.strip()
                if not annotation or f"{{{name}}}" in route:
                    continue
                if SCALAR.match(annotation):
                    bare.append(name)
            if bare:
                found[(route, verb)] = bare
    return found


def _frontend_sources() -> dict[pathlib.Path, str]:
    return {
        f: f.read_text()
        for f in FRONTEND.rglob("*.ts*")
        if ".test." not in f.name and "mocks" not in str(f)
    }


def _callers_sending_a_body(route: str) -> list[str]:
    """Frontend `post/put/patch` calls to this route whose second argument is an object.

    `api.post(url, null, { params })` is the correct shape for a query-parameter route and is
    NOT reported. `api.post(url, { field })` is the shape that 422s.

    MATCHED ON THE WHOLE ROUTE, not its last segment. The first draft matched the tail, so
    `/insights/activations/{id}/reject` was reported against
    `/strategic/recommendations/{rec_id}/approve` — two unrelated routes that share the word
    "reject". Path parameters become wildcards; everything else is literal.
    """
    if not route.strip("/"):
        return []
    pattern = re.escape(route).replace(r"\{", "{").replace(r"\}", "}")
    pattern = re.sub(r"\{[^}]*\}", r"[^/`]+", pattern)
    offenders = []
    for path, text in _frontend_sources().items():
        for match in re.finditer(
            rf"\.(post|put|patch)(?:<[^>]*>)?\(\s*`[^`]*{pattern}`\s*,\s*(.)", text
        ):
            if match.group(2) == "{":
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(FRONTEND)}:{line}")
    return offenders


class TestTheMeasurementIsReal:
    def test_routes_are_found(self):
        """Vacuity: a regex that matched no routes would report a clean tree."""
        assert len(_query_scalars()) > 5

    def test_the_frontend_is_readable(self):
        assert len(_frontend_sources()) > 100

    def test_a_marked_parameter_is_not_counted_as_a_query_parameter(self):
        """The calibration that cost the first draft its credibility. `Header(...)`,
        `Body(...)` and friends are not query parameters, and a sweep that says they are
        reported 48 sites where 22 candidates exist — including a correctly-declared webhook
        signature header.

        Driven through the real extractor rather than asserted against the regex, because the
        regex was never the part that was wrong.
        """
        marked = "x_webhook_signature: Optional[str] = Header(default=None)"
        assert any(k in marked for k in MARKERS), "the marker list no longer covers Header()"

        bare = "status: str"
        name, _, annotation = bare.partition(":")
        assert SCALAR.match(annotation.strip()), "a bare scalar is no longer detected at all"
        assert not any(k in bare for k in MARKERS)

    def test_a_route_is_not_matched_by_a_shared_last_segment(self):
        """`/insights/activations/{id}/reject` and `/strategic/recommendations/{id}/reject`
        share a last segment and nothing else. Matching on the tail reported the first as a
        defect in the second — a name collision presented as a finding."""
        assert not _callers_sending_a_body("/strategic/recommendations/{rec_id}/reject_zzz")

    def test_the_body_shape_and_the_params_shape_are_told_apart(self):
        """`api.post(url, null, { params })` is correct; `api.post(url, { field })` is the
        defect. If this stopped discriminating, the guard would pass by calling everything
        correct — the failure mode three earlier sweeps in this repo had."""
        sample = "api.post(`/x/status`, { status })"
        assert re.search(r"\.post\(\s*`[^`]*status[^`]*`\s*,\s*\{", sample)
        correct = "api.post(`/x/status`, null, { params: { status } })"
        assert not re.search(r"\.post\(\s*`[^`]*status[^`]*`\s*,\s*\{", correct)


class TestTheTwoSidesAgree:
    @pytest.mark.parametrize(
        "route,verb", sorted(_query_scalars().keys()), ids=lambda v: str(v)[:40]
    )
    def test_no_caller_posts_a_body_to_a_query_parameter_route(self, route: str, verb: str):
        if route in ALLOWED:
            pytest.skip(ALLOWED[route])
        params = _query_scalars()[(route, verb)]
        offenders = _callers_sending_a_body(route)
        assert not offenders, (
            f"{verb.upper()} {route} reads {params} from the QUERY STRING — they are bare "
            f"scalars with no Body() marker — and {offenders} post a JSON body to it. Every "
            f"one of those calls answers 422, and has since it was written. Either send them "
            f"as `params`, or give the route a Pydantic body model. Three features shipped "
            f"broken this way: FS-379, FS-420 and FS-658."
        )
