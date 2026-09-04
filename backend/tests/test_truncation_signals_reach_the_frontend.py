"""A truncation flag the server sends must survive the client that reads it (FS-485).

THE DEFECT CLASS. `mark_truncated` selects `limit + 1` rows and sets `X-Result-Truncated`
so a bare JSON array of exactly `limit` rows can be told apart from the complete set. Every
endpoint that does it has already been judged worth the extra row — somebody decided the
difference mattered enough to change the query.

Then the frontend client returns `response.data` and the flag is gone. Nothing fails, no
type complains, and the page renders a page of the list as the whole list. That is a claim
about the world derived from a capped query, and it is the class this repository has now
met at four boundaries: the RUL list ordered by asset name, the session transcript ordered
oldest-first, the historian CSV that left the building, and the notification delivery log.

WHAT IT FOUND. One: `notificationsApi.deliveryLog`. The log is ordered NEWEST FIRST, so a
cap removes the oldest attempts — and the question that page answers is "was that alert
delivered?". A row absent from a list presented as complete says the alert was never sent,
which is a statement about the notification system rather than about the query.

WHAT IT DELIBERATELY DOES NOT FLAG. `CommandPanel`'s history is capped at five and reads
`response.data`. It was checked rather than skipped: the list is newest-first, the heading
reads "Recent commands", and the command an operator just sent is by construction in the
first five. The label already carries the caveat, so the flag would add nothing a reader
does not have. Recorded here so the next person can tell "checked and left" from "never
looked at" — Class 25's lesson, which cost a wrong "clean" once already.

WHY THIS LIVES IN THE BACKEND SUITE. It needs both trees. The backend is the only side that
knows which endpoints signal; the frontend is the only side that knows which of them are
called. Neither suite alone can ask the question.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
API_DIR = REPO / "backend" / "app" / "api"
FRONTEND_API = REPO / "frontend" / "src" / "api"

#: Frontend call sites that read a signalling endpoint without `toListResult`, each with the
#: reason it is acceptable. An entry here is a decision on the record, not a silence.
ACCEPTED_WITHOUT_THE_FLAG = {
    "/api/v1/commands/asset": (
        "CommandPanel caps at five, orders newest-first and titles the section 'Recent "
        "commands' — the heading already says it is a page, and the command just sent is "
        "in it by construction."
    ),
}


def _router_prefixes() -> dict[str, str]:
    """module name -> the prefix its routes are mounted under.

    Without this the comparison below falls back to matching the last path segment, and
    `/erp/integrations/{id}/events` collides with `/fleet/security/events` — two unrelated
    endpoints, one of which does not truncate at all. That false positive is exactly the
    kind that makes a report stop being read.

    TWO PLACES DECLARE IT. Most routers take their prefix from `main.py`'s `include_router`;
    three — registries, analysis_sessions and erp_integrations — carry it on their own
    `APIRouter(prefix=…)` and are included bare. Reading only `main.py` dropped all three
    silently, which the vacuity test below now refuses to allow.
    """
    prefixes: dict[str, str] = {}
    for path in sorted(API_DIR.glob("*.py")):
        own = re.search(r'router = APIRouter\(\s*prefix="([^"]*)"', path.read_text())
        if own:
            prefixes[path.stem] = own.group(1)
    source = (REPO / "backend" / "app" / "main.py").read_text()
    for m in re.finditer(r'app\.include_router\(\s*(\w+)\.router,\s*prefix="([^"]*)"', source):
        prefixes[m.group(1)] = m.group(2)
    # A FOURTH way to declare it: included with NO `prefix=` kwarg at all, because every
    # route on the router already spells its full path (`edge_fleet.py`'s
    # `@router.get("/api/v1/edge/fleet", ...)`). That is prefix="", not "unresolved" —
    # conflating the two would make a router with no prefix indistinguishable from one
    # this reader has never heard of, which is exactly the silent-drop the three-router
    # fix above exists to prevent.
    for m in re.finditer(r'app\.include_router\(\s*(\w+)\.router\s*,', source):
        prefixes.setdefault(m.group(1), "")
    return prefixes


PREFIXES = _router_prefixes()
UNRESOLVED: list[str] = []


def _signalling_routes() -> list[tuple[str, str]]:
    """(file, path) for every GET whose own handler calls ``mark_truncated``.

    Sliced on EVERY router decorator, not just ``@router.get``. An earlier version split on
    ``.get`` alone, so a ``@router.post`` between two GETs put a later handler's call inside
    an earlier handler's slice and attributed truncation to a route that does not truncate —
    a detector wrong before the code was.
    """
    found: list[tuple[str, str]] = []
    decorator = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"')
    for path in sorted(API_DIR.glob("*.py")):
        source = path.read_text()
        if "mark_truncated" not in source:
            continue
        marks = [(m.start(), m.group(1), m.group(2)) for m in decorator.finditer(source)]
        for index, (start, verb, route) in enumerate(marks):
            end = marks[index + 1][0] if index + 1 < len(marks) else len(source)
            body = source[start:end]
            # A module-level helper defined between two routes would otherwise be counted
            # against whichever route precedes it.
            body = re.split(r"\n(?:def|async def) _", body)[0]
            if verb == "get" and "mark_truncated(" in body:
                prefix = PREFIXES.get(path.stem)
                if prefix is None:
                    # An unresolved prefix would make the route a bare fragment, and a bare
                    # fragment matches far too much. Counted rather than guessed — the
                    # vacuity test below fails if this starts happening often.
                    UNRESOLVED.append(path.stem)
                    continue
                found.append((path.name, prefix + route))
    return found


def _frontend_get_calls() -> list[tuple[str, str, bool]]:
    """(file, url, reads_the_flag) for every ``api.get`` in the frontend api clients.

    The URL is captured WHOLE, interpolations included, and module-level string constants
    are substituted in. An earlier version stopped the capture at the first ``${``, which
    turned ``` `${BASE}/log` ``` into the empty string — and an empty string matched every
    route whose prefix failed to resolve, so the sweep reported eleven offenders of which
    none was real. A reader who meets that list once stops reading the next one.
    """
    calls: list[tuple[str, str, bool]] = []
    call = re.compile(r"api\.get<[^>]*>\(\s*[`'\"]([^`'\"]*)[`'\"]")
    for path in sorted(FRONTEND_API.glob("*.ts")):
        if ".test." in path.name:
            continue
        source = path.read_text()
        constants = dict(re.findall(r"const (\w+) = '(/[^']*)'", source))
        for match in call.finditer(source):
            url = match.group(1)
            for name, value in constants.items():
                url = url.replace("${" + name + "}", value)
            # BEFORE and AFTER the call. The original window looked only backwards,
            # which recognises `return toListResult(await api.get(...))` and not the
            # equally-correct `const response = await api.get(...); ...
            # toListResult(response)` — a shape engines.ts needed because it reads a
            # second header (X-Engine-Not-Running) off the same response. Flagging that
            # as body-alone was the detector wrong, not the client.
            window = source[max(0, match.start() - 200) : match.end() + 200]
            calls.append((path.name, url, "toListResult" in window))
    return calls


SIGNALLING = _signalling_routes()


class TestTheSweepIsNotVacuous:
    """A broken reader returns nothing, and nothing passes every comparison below."""

    def test_it_finds_the_endpoints_that_signal(self):
        assert len(SIGNALLING) >= 10, (
            f"only {len(SIGNALLING)} signalling routes found; the decorator walk is broken "
            f"and every check below would pass over an empty list"
        )

    def test_it_finds_a_route_known_to_signal(self):
        # `/log` in notifications.py is the one this sweep was written for, spelled as the
        # full path. If the walk stops resolving it — or stops resolving the prefix — the
        # sweep has quietly stopped covering its own subject.
        assert ("notifications.py", "/api/v1/notifications/log") in SIGNALLING

    def test_it_resolves_the_router_prefixes(self):
        # Without a prefix every route is compared as a relative fragment, and the check
        # degenerates into last-segment matching, which collides across routers.
        assert len(PREFIXES) > 40, f"only {len(PREFIXES)} router prefixes parsed from main.py"
        assert PREFIXES.get("notifications") == "/api/v1/notifications"

    def test_it_does_not_attribute_a_helper_to_a_route(self):
        # `erp_integrations.py` defines a module-level `_mark_truncated` between a DELETE
        # and the next GET. An earlier version of this walk reported the DELETE as a
        # truncating route because of it.
        assert not [r for f, r in SIGNALLING if f == "erp_integrations.py" and "mappings" in r]

    def test_every_signalling_router_resolves_its_prefix(self):
        # A module whose prefix does not resolve drops out of the comparison silently, which
        # is the sweep under-reporting rather than failing — the shape Rule 109 is about.
        _signalling_routes()
        assert not UNRESOLVED, (
            f"these routers signal truncation and their mount prefix could not be read out "
            f"of main.py, so their routes are not compared at all: {sorted(set(UNRESOLVED))}"
        )

    def test_it_reads_the_frontend_clients(self):
        calls = _frontend_get_calls()
        assert len(calls) > 40, f"only {len(calls)} frontend GET calls parsed; the reader is broken"
        assert any(reads for _, _, reads in calls), "no call reads toListResult; the check is inverted"


class TestEverySignalledCapSurvivesTheClient:
    def test_no_client_discards_a_flag_the_server_sent(self):
        # Compared as FULL paths, prefix included. A `{param}` segment matches anything,
        # since the frontend interpolates a value where the route declares a placeholder.
        # A template literal (`${BASE}`) truncates the captured URL, so this is loose in
        # that one direction — a false negative costs less than a false positive nobody
        # trusts, and the vacuity tests above hold the floor.
        offenders = []
        for _, route in SIGNALLING:
            pattern = re.compile(
                "^" + re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(route).replace(r"\{", "{").replace(r"\}", "}")) + "/?$"
            )
            for file, url, reads in _frontend_get_calls():
                # An interpolation the constant table could not resolve leaves a `${` in the
                # URL; comparing it would be guesswork either way.
                if reads or "${" in url or not pattern.match(url.split("?")[0]):
                    continue
                if any(url.startswith(prefix) for prefix in ACCEPTED_WITHOUT_THE_FLAG):
                    continue
                offenders.append(f"{file} calls {url}, which sets X-Result-Truncated, and returns the body alone")
        assert not offenders, (
            "these clients drop a truncation flag the server went out of its way to send, so "
            "the page shows a capped list as the complete one: " + "; ".join(offenders)
        )

    @pytest.mark.parametrize("prefix,reason", sorted(ACCEPTED_WITHOUT_THE_FLAG.items()))
    def test_each_exemption_still_names_a_real_endpoint(self, prefix: str, reason: str):
        # An exemption for a call that no longer exists is a stale permission, and stale
        # permissions are how an allowlist stops describing the code it guards.
        tail = prefix.rstrip("/").split("/")[-1]
        sources = list(FRONTEND_API.glob("*.ts")) + list(
            (REPO / "frontend" / "src").rglob("*.tsx")
        )
        assert any(
            prefix in path.read_text()
            for path in sources
            if ".test." not in path.name
        ), f"{prefix} is exempted here and is called nowhere in the frontend — reason on file: {reason}"
