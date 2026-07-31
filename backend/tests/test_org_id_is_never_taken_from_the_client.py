"""No endpoint may store an `organization_id` that came from the request body.

18 Create/Update schemas in `app/models/schemas.py` carry an `organization_id` field, so
a client can name any tenant it likes. Every handler but one already ignores it and binds
the row to the authenticated user's organisation. `yard.create_dock_door` did not — it
did `DockDoor(**data.model_dump())`, storing whatever arrived.

Row-level security is enabled and FORCED on those tables and would reject the write, so
this was defence-in-depth rather than an open door. But relying on RLS alone makes the
outcome depend on the database ROLE rather than on the code:

  * a connection with BYPASSRLS — a superuser, or the cluster owner — turns the same
    request into a genuine cross-tenant write;
  * and even where RLS holds, the caller gets a 500 from a policy violation instead of a
    row correctly bound to their own tenant.

Two independent controls, neither trusted alone.

WHY THIS TEST IS FUSSIER THAN IT LOOKS. The obvious version — "does the handler mention
organization_id?" — reported `assets.py` as an offender while it was already correct: it
overrides via `payload["organization_id"] = org_id`, a dict-key assignment the naive
pattern missed. A guard that cries wolf on compliant code gets its assertion loosened
until it catches nothing, so the accepted forms are enumerated explicitly below.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
API_DIR = BACKEND / "app" / "api"
SCHEMAS = BACKEND / "app" / "models" / "schemas.py"

#: Sources a handler may legitimately bind organization_id from — all of them derive it
#: from the authenticated principal, never from the request body.
TENANT_SOURCES = r"(org_id|organization_id_dep|current_user\.organization_id|tenant_org_id)"

#: The forms that count as an override, including the dict-key spelling assets.py uses.
OVERRIDE_PATTERNS = [
    rf'\[["\']organization_id["\']\]\s*=\s*{TENANT_SOURCES}',   # payload["organization_id"] = org_id
    rf'organization_id\s*=\s*{TENANT_SOURCES}\b',                # Model(organization_id=org_id)
    rf'\.organization_id\s*=\s*{TENANT_SOURCES}\b',              # obj.organization_id = org_id
    rf'update\(\s*organization_id\s*=\s*{TENANT_SOURCES}',       # payload.update(organization_id=...)
]


def _schemas_carrying_org_id() -> set[str]:
    src = SCHEMAS.read_text()
    carriers: set[str] = set()
    for m in re.finditer(r"class (\w+)\(([\w, ]*)\):(.*?)(?=\nclass |\Z)", src, re.S):
        name, _bases, body = m.groups()
        if re.search(r"^\s+organization_id\s*:", body, re.M):
            carriers.add(name)
    # A subclass of a carrier inherits the field. Iterate to a fixed point.
    changed = True
    while changed:
        changed = False
        for m in re.finditer(r"class (\w+)\(([\w, ]*)\):", src):
            child, bases = m.group(1), m.group(2)
            if child not in carriers and any(b.strip() in carriers for b in bases.split(",")):
                carriers.add(child)
                changed = True
    return carriers


def _handlers_storing_client_org() -> list[str]:
    carriers = _schemas_carrying_org_id()
    offenders = []
    for path in sorted(API_DIR.glob("*.py")):
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            m = re.search(r"(\w+)\s*:\s*(\w+)\b", line)
            if not m or m.group(2) not in carriers:
                continue
            var, schema = m.group(1), m.group(2)
            body = "\n".join(lines[i : i + 40])
            splats = re.search(rf"\b{re.escape(var)}\.(model_dump|dict)\(\)", body)
            if not splats:
                continue  # builds the row field by field; organization_id is not carried over
            if any(re.search(p, body) for p in OVERRIDE_PATTERNS):
                continue  # binds it to the authenticated tenant
            offenders.append(f"{path.name}: {schema} (parameter `{var}`)")
    return offenders


def test_the_sweep_finds_schemas_and_handlers():
    """A guard that matches nothing passes for the wrong reason."""
    carriers = _schemas_carrying_org_id()
    assert len(carriers) > 10, (
        f"only {len(carriers)} schemas found carrying organization_id; the class-parsing "
        "regex has probably drifted from schemas.py"
    )
    assert API_DIR.is_dir()


def test_no_handler_stores_a_client_supplied_organization_id():
    offenders = _handlers_storing_client_org()
    assert not offenders, (
        "these handlers splat a request schema that carries organization_id into a model "
        "without rebinding it to the authenticated tenant, so a caller can name someone "
        "else's organisation:\n  " + "\n  ".join(offenders)
        + "\n\nDo what assets.py:100 does:\n"
        '    payload = data.model_dump()\n'
        '    payload["organization_id"] = org_id\n'
        "RLS would reject the write, but that makes correctness depend on the database "
        "role rather than the code."
    )
