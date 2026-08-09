"""No request schema requires a tenant the handler throws away (FS-523).

FOURTEEN CREATE ENDPOINTS COULD NOT BE CALLED. Each declared a **required**
`organization_id` on its request body, while its handler derived the tenant from the token
and never read the body's value. The handlers say so themselves, in a comment repeated
verbatim at each site:

    # FROM THE TOKEN, NEVER THE REQUEST — `data.organization_id` is client-supplied,
    # so a caller could file the row under any organisation they named.

Correct. And the schema next door forced every caller to send that exact client-supplied
value anyway — with no default, so **omitting it is a 422**. The frontend's own types carry no
`organization_id` (`frontend/src/api/transportation.ts` has one occurrence in the whole file,
in a comment), so it omitted it, and every one of these returned 422 to the only client that
calls them:

    POST /transportation/{carriers,drivers,shipments,routes,load-plans,freight-charges}
    POST /yard/{trailers/checkin,dock/appointments,moves,driver-wait-times,checkpoints}
    POST /logistics-correlation/load-quality
    POST /assets                        <- found by this guard, after the other twelve
    POST /yard/dock/doors               <- likewise

That is a shipment you cannot create, a carrier you cannot add and a trailer you cannot check
in — the write half of the product.

**THIS IS THE WRITE-SIDE TWIN OF FS-99**, which found four yard GETs taking a required
`organization_id` query parameter that no frontend call sent, and fixed them one router at a
time. The read side got a guard (`test_frontend_query_params_are_declared.py`). The write side
did not, and the same defect was sitting in fourteen places.

WHY THE EXISTING GUARD DID NOT CATCH IT. `test_no_handler_takes_its_tenant_from_the_body.py`
asserts no handler *reads* the tenant out of the request. Every one of these passes it — none
of them reads it. Nothing asked whether the schema still *demanded* it. **Two artefacts, each
correct about itself, and the defect only visible in the pair** — rule 122, in the request
layer.

WHY THE FIELD WAS REMOVED RATHER THAN MADE OPTIONAL. A field a caller can set that changes
nothing is its own small lie: it invites somebody to set it and believe it did something.
Pydantic ignores extra keys by default, so a client still sending one is unaffected.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
API = BACKEND / "app" / "api"

#: The one legitimate source of a tenant, per `app/core/tenant.py`.
TOKEN_DEPENDENCY = "get_tenant_org_id"

TENANT_FIELDS = {"organization_id", "organizationId", "org_id"}

#: Schemas allowed to require a tenant despite a token-derived handler, with the reason.
#: Empty, and meant to stay that way — an entry here is an endpoint a client cannot call
#: without sending a value the server discards.
ALLOWED: dict[str, str] = {}


def _handlers_deriving_tenant_from_the_token() -> list[tuple[str, str, str]]:
    """(module, function, body-schema) for every route handler that takes the org from the
    token and also declares a request body.

    Reads the SOURCE for the handler signature and the IMPORTED model for the field, because
    a required field can be inherited from a base class two levels up — `ShipmentCreate`
    declares its own, but a sibling could get one from `ShipmentBase` and a source-only check
    would miss it entirely.
    """
    found = []
    for path in sorted(API.rglob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            rendered = ast.unparse(fn)
            if TOKEN_DEPENDENCY not in rendered:
                continue
            for arg in fn.args.args + fn.args.kwonlyargs:
                if arg.annotation is None:
                    continue
                annotation = ast.unparse(arg.annotation)
                if annotation.endswith(("Create", "Update", "Request")):
                    found.append((path.name, fn.name, annotation))
    return found


def _required_tenant_fields(schema_name: str) -> set[str]:
    schemas = importlib.import_module("app.models.schemas")
    model = getattr(schemas, schema_name, None)
    if model is None or not hasattr(model, "model_fields"):
        return set()
    return {
        name
        for name, field in model.model_fields.items()
        if name in TENANT_FIELDS and field.is_required()
    }


class TestTheSweepHasSubjects:
    def test_it_finds_handlers_that_derive_the_tenant(self):
        """If the dependency were renamed, this file would pass over an empty list while the
        defect it exists for went unchecked — the failure mode FS-484 and FS-492 each cost
        once."""
        handlers = _handlers_deriving_tenant_from_the_token()
        assert len(handlers) >= 10, (
            f"only {len(handlers)} handlers found taking a request body and deriving the "
            f"tenant from `{TOKEN_DEPENDENCY}`. Either the dependency was renamed or the "
            f"walk broke; either way this gate is protecting nothing."
        )

    def test_the_schema_module_is_readable(self):
        schemas = importlib.import_module("app.models.schemas")
        assert hasattr(schemas, "ShipmentCreate"), (
            "app.models.schemas no longer exposes ShipmentCreate; the field check below "
            "silently answers 'no required tenant' for every schema"
        )


class TestNoSchemaDemandsWhatTheHandlerDiscards:
    def test_no_create_schema_requires_a_tenant(self):
        offenders = []
        for module, function, schema in _handlers_deriving_tenant_from_the_token():
            if schema in ALLOWED:
                continue
            required = _required_tenant_fields(schema)
            if required:
                offenders.append(f"{module}:{function} -> {schema} requires {sorted(required)}")

        assert not offenders, (
            "these handlers derive the tenant from the token and their request schema still "
            "REQUIRES one, so a caller who omits it gets a 422 and a caller who sends one "
            "has it discarded:\n  "
            + "\n  ".join(offenders)
            + "\n\nRemove the field from the schema. It is not defence in depth — the handler "
            "never reads it, so the only thing it does is make the endpoint uncallable by a "
            "client that correctly declines to supply its own tenant."
        )

    @pytest.mark.parametrize("schema", sorted(ALLOWED))
    def test_each_exemption_is_still_needed(self, schema: str):
        assert _required_tenant_fields(schema), (
            f"{schema} no longer requires a tenant field, so its ALLOWED entry is stale"
        )


class TestTheFourteenStayFixed:
    """Named individually so a regression says which endpoint stopped being callable, rather
    than a count. These are the fourteen that were returning 422 to the frontend."""

    FIXED = [
        "CarrierCreate", "DriverCreate", "ShipmentCreate", "RouteCreate",
        "LoadPlanCreate", "FreightChargeCreate", "YardTrailerCreate",
        "DockAppointmentCreate", "YardMoveCreate", "DriverWaitTimeCreate",
        "YardCheckPointCreate", "LoadQualityLogCreate",
        # Found by THIS GUARD after the twelve above were already fixed. The sweep that
        # produced the twelve keyed on the handler's own parameter being named
        # `organization_id`; these two derive the tenant under a different name, so a
        # source-shaped detector missed them. `AssetCreate` is the core create path of the
        # product — a detector one degree narrower than its class would have shipped with
        # `POST /assets` still answering 422.
        "AssetCreate", "DockDoorCreate",
    ]

    @pytest.mark.parametrize("schema", FIXED)
    def test_it_does_not_require_a_tenant(self, schema: str):
        assert not _required_tenant_fields(schema), (
            f"{schema} requires a tenant field again. The handler behind it derives the org "
            f"from the token and discards the body's value, so this makes the endpoint "
            f"answer 422 to the frontend, which sends no organization_id."
        )

    @pytest.mark.parametrize("schema", FIXED)
    def test_it_still_exists(self, schema: str):
        """A renamed or deleted schema would make the test above pass by answering about
        nothing."""
        schemas = importlib.import_module("app.models.schemas")
        assert hasattr(schemas, schema), (
            f"{schema} is gone from app.models.schemas — this list no longer describes the code"
        )
