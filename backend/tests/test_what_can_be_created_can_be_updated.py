"""An entity you can create and never update (FS-677).

`test_what_can_be_created_can_be_corrected.py` compares a `*Create` schema to its `*Update`
sibling and finds *fields* that are frozen. It cannot see the worse case, because a schema
pair can agree perfectly while **no route serves the update at all** — which is what five
entities looked like:

  * a **dock appointment** that could be started and completed but never RESCHEDULED, on a
    surface whose most common event is a truck moving to a different slot;
  * a **load plan** that could not be amended, so a pallet that would not fit meant a second
    plan on the same shipment contradicting the first;
  * a **freight charge** that could not be corrected — FS-665 found this same service
    inventing a $1,333.33 linehaul from a 500-mile default, and once written that figure was
    permanent;
  * a **route** whose distance prices every shipment on it (FS-665 again), fixed at creation;
  * a **dock door** that could not be reconfigured, so converting a bay from inbound to
    cross-dock meant deleting it and losing every appointment referencing it.

Four of the five had an `*Update` schema already written and wired to nothing — the FS-676
shape, five more times.

HOW THIS IS MEASURED, AND THE DETECTOR THAT WAS THROWN AWAY FIRST. The obvious version walks
route paths: every collection `POST` should have a sibling `PUT`. It reported **95 of 123
POSTs as missing an update**, because most POSTs are actions — login, flush, enforce,
acknowledge — and because `POST /api/v1/assets/` and `PUT /api/v1/assets/{id}` differ by a
trailing slash. A detector that names ninety-five defects in a tree with five is not a rough
first pass; it is noise that would have buried the answer.

The version below pairs by SCHEMA instead, from the OpenAPI document: find the operation whose
request body is `XCreate`, find the one whose body is `XUpdate`, and require that if the first
exists the second does. It has no heuristic in it — an action endpoint has no `*Create` model,
so it never enters the comparison — and it answers exactly the question the class asks.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.models import schemas


def _spec():
    from app.main import app

    return app.openapi()


def _operations_taking(model_name: str) -> list[str]:
    """`METHOD /path` for every operation whose JSON request body is this model."""
    found = []
    for path, operations in _spec()["paths"].items():
        for method, operation in operations.items():
            body = (operation.get("requestBody") or {}).get("content", {})
            ref = ((body.get("application/json") or {}).get("schema") or {}).get("$ref", "")
            if ref.rsplit("/", 1)[-1] == model_name:
                found.append(f"{method.upper()} {path}")
    return found


def _pairs() -> list[tuple[str, str, str]]:
    """(entity, CreateName, UpdateName) for every schema pair that exists."""
    out = []
    for name in sorted(dir(schemas)):
        if not name.endswith("Create"):
            continue
        model = getattr(schemas, name)
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            continue
        update = name[: -len("Create")] + "Update"
        if hasattr(schemas, update):
            out.append((name[: -len("Create")], name, update))
    return out


class TestTheMeasurementIsReal:
    def test_pairs_are_found(self):
        assert len(_pairs()) >= 15, (
            f"only {len(_pairs())} Create/Update schema pairs found; the naming convention "
            f"has changed and this guard is now checking almost nothing"
        )

    def test_a_known_create_route_is_located(self):
        """Vacuity. If `$ref` resolution breaks, every entity looks uncreatable and the
        assertion below passes for the wrong reason."""
        assert _operations_taking("ShipmentCreate"), (
            "the OpenAPI request-body walk found no route taking ShipmentCreate, so it "
            "would find none for anything and this file would report a clean tree"
        )

    def test_a_known_update_route_is_located(self):
        assert _operations_taking("ShipmentUpdate")

    def test_an_action_endpoint_is_not_dragged_in(self):
        """The reason this pairs by schema and not by path. `POST /auth/login` has no
        `LoginCreate` model, so it never enters the comparison — where the path-based
        version reported it, and ninety-four others, as an entity missing its update."""
        assert not any(entity == "Login" for entity, _c, _u in _pairs())


@pytest.mark.parametrize(
    "entity,create,update", _pairs(), ids=[p[0] for p in _pairs()]
)
def test_an_entity_that_can_be_created_can_be_updated(entity, create, update):
    create_routes = _operations_taking(create)
    if not create_routes:
        pytest.skip(f"{create} is not served by any route; nothing to pair")
    assert _operations_taking(update), (
        f"{entity} can be created via {create_routes} and there is no route taking "
        f"{update}, which exists. A row that can be written once and never corrected is a "
        f"worse contract than one that cannot be written at all — and an Update schema "
        f"sitting unserved reads to the next person as a promise the API keeps."
    )


class TestTheIdentifiersStayImmutable:
    """The other direction, for the fields deliberately left off the new update schemas."""

    @pytest.mark.parametrize(
        "update,field",
        [
            ("DockDoorUpdate", "door_number"),
            ("LoadPlanUpdate", "shipment_id"),
            ("FreightChargeUpdate", "shipment_id"),
        ],
    )
    def test_the_identifying_field_is_absent(self, update, field):
        assert field not in getattr(schemas, update).model_fields, (
            f"{field} became editable on {update}. For the doors that is renaming the bay "
            f"you are addressing; for the other two it turns a correction into a transfer — "
            f"a charge moved to another shipment is a different charge."
        )
