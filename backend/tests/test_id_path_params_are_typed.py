"""A path parameter holding a UUID must be declared as one.

Declared as a bare `str`, an id like "0" passes FastAPI untouched, reaches a uuid
column, and asyncpg raises:

    invalid input for query argument $1: '0' (invalid UUID '0')

which surfaces as a **500**. The request was malformed, so the honest answer is 422.
A 500 tells the caller the server broke and a retry might work, when it never will,
and it files a non-incident into error tracking.

28 path params across nine routers had drifted this way, against 145 already declared
UUID — the convention existed and these had fallen out of it. Found by the API contract
suite, which generates "0" for any unconstrained string parameter.

NOT EVERY `*_id` IS A UUID, which is why this guard works from an explicit list rather
than the name. `geotab.device_id` is an external GeoTab identifier and
`data_residency.record_id` is polymorphic — the row it points at lives in a table chosen at
runtime. (`health.collector_id` was a third; its endpoint was removed in FS-352 because it
restarted nothing, and `test_the_allowlist_has_no_dead_entries` caught the stale entry the
moment it went.) Converting any of those would break
them. The allowlist below records that judgement so the next person does not have to
re-derive it, and so a NEW bare-string id fails this test instead of joining them
silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"

#: Path parameters that are legitimately strings, with the reason. Anything not listed
#: here must be typed UUID. Add an entry only with a reason that survives being read
#: aloud — "it was already like that" is not one.
LEGITIMATE_STRING_IDS = {
    ("geotab.py", "device_id"): "GeoTab's own device identifier, not one of ours",
    ("data_residency.py", "record_id"): (
        "polymorphic — identifies a row in a table chosen at runtime, so it cannot be "
        "typed against one column"
    ),
    ("bulk_operations.py", "job_id"): "job handle from the bulk-import service, not a table id",
    ("rag.py", "doc_id"): "document id in the vector store, which is not Postgres",
    ("user_context.py", "goal_id"): "goal ids are stored in a JSON column, not a table",
    ("fleet_logistics.py", "vehicle_id"): (
        "reaches a service layer typed str; converting the route without the service "
        "would only move the coercion"
    ),
    ("correlation_evidence.py", "feedback_id"): (
        "a caller-supplied vocabulary-feedback key held in the evaluation service's own "
        "dict (correlation_evaluation.py `_feedback_by_id`), not a row id — there is no "
        "column to type it against"
    ),
    ("health_index.py", "asset_id"): (
        "passed into health_index_calculator.get_asset_health(asset_id: str); the "
        "service contract is the thing to change first"
    ),
}
# An entry for `compliance.py::framework_id` was written here from memory and removed:
# no such parameter exists. test_the_allowlist_has_no_dead_entries caught it, which is
# the case that test was written for — a plausible-sounding exemption is exactly what
# an allowlist accumulates if nothing checks that its subjects are real.


def _string_id_path_params() -> list[tuple[str, int, str, str]]:
    """Every `*_id: str` that is a PATH parameter, as (file, line, name, route)."""
    found = []
    for path in sorted(API_DIR.glob("*.py")):
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"^(\s+)(\w+_id): str([,)=].*)?$", line)
            if not m:
                continue
            name = m.group(2)
            route = None
            for j in range(i, max(0, i - 40), -1):
                d = re.search(r'@\w*router\.(get|post|put|patch|delete)\(\s*"([^"]*)"', lines[j])
                if d:
                    route = d.group(2)
                    break
            if route and "{" + name + "}" in route:
                found.append((path.name, i + 1, name, route))
    return found


def test_the_sweep_can_see_the_routers():
    """A guard that parses nothing passes for the wrong reason."""
    assert API_DIR.is_dir(), f"{API_DIR} is gone; this guard is inspecting nothing"
    routers = list(API_DIR.glob("*.py"))
    assert len(routers) > 40, f"only {len(routers)} routers found; check the path"


def test_no_new_uuid_path_param_is_typed_as_a_string():
    offenders = [
        (f, ln, n, r) for f, ln, n, r in _string_id_path_params()
        if (f, n) not in LEGITIMATE_STRING_IDS
    ]
    assert not offenders, (
        "these path parameters are declared `str`. If they hold a UUID, an id like "
        '"0" reaches Postgres and returns 500 where it should be 422:\n  '
        + "\n  ".join(f"{f}:{ln}  {n}  in {r}" for f, ln, n, r in offenders)
        + "\n\nDeclare it `UUID`, or — if it genuinely is not one — add it to "
        "LEGITIMATE_STRING_IDS with the reason."
    )


def test_the_allowlist_has_no_dead_entries():
    """An allowlist entry for a parameter that no longer exists is stale.

    Without this, the list grows into a record of what used to be true, and a real
    offender can hide behind an entry whose subject was renamed years ago.
    """
    live = {(f, n) for f, _, n, _ in _string_id_path_params()}
    dead = sorted(k for k in LEGITIMATE_STRING_IDS if k not in live)
    assert not dead, (
        f"these allowlist entries no longer match any string path parameter: {dead}. "
        "Remove them — either the parameter is gone or it is already typed."
    )


@pytest.mark.parametrize("key,reason", sorted(LEGITIMATE_STRING_IDS.items()))
def test_every_allowlist_entry_states_a_reason(key, reason):
    assert len(reason) > 20, f"{key} is allowlisted with no usable reason: {reason!r}"
