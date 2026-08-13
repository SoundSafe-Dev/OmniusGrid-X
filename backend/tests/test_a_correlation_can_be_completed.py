"""A schema written down and never wired, and a record that could never be completed (FS-676).

`PUT /registries/correlations/{id}` declared three bare scalars — `correlation_strength`,
`confidence_score`, `is_active` — and FastAPI reads a non-Pydantic scalar with no `Body()`
marker as a **query parameter**. So the endpoint wanted `?correlation_strength=80`, and the
obvious `api.put(url, {...})` would have returned 200 having changed nothing.

`DataCorrelationUpdate` already existed in `schemas.py`, referenced by no code at all: the
intended design was written down and never connected. `update_registry`, `update_registry_item`
and `create_correlation` in the same file all take their model, so this was the one route that
missed it rather than a deliberate contract — and nothing calls it, so aligning it breaks
nothing.

**And the schema was three fields of eleven.** `source_id` and `target_id` are nullable columns
and optional on create, so a correlation could be filed between *a task* and *an asset* with
neither identified — and then never completed. That is the shape FS-665 left on shipments,
found here by the same Create-vs-Update comparison, which is why the pair now lives in
`test_what_can_be_created_can_be_corrected.py` rather than only being fixed here.

A DETECTOR CORRECTION WORTH KEEPING. The sweep for write schemas nothing references first
reported **three**: `AlarmCreate`, `DataCorrelationUpdate`, `TruckAssetCorrelationCreate`. It
searched every file except `schemas.py` — to avoid matching each class's own definition — and
so could not see that `AlarmResponse(AlarmCreate)` **inherits** from one of them. Excluding a
file to suppress self-matches also suppressed the legitimate intra-file use. One of the three
was real.
"""

from __future__ import annotations

import ast
import pathlib
import re

from pydantic import BaseModel

from app.models import schemas

SCHEMAS = pathlib.Path(__file__).resolve().parents[1] / "app" / "models" / "schemas.py"
APP = SCHEMAS.parents[2]
TESTS = pathlib.Path(__file__).resolve().parent

CORRELATION_PATH = "/api/v1/registries/correlations/{correlation_id}"

#: Write schemas that exist and nothing references, with the reason each is still here.
#: Names and reasons rather than a count, so the entry has to be argued with rather than
#: decremented.
UNWIRED = {
    "TruckAssetCorrelationCreate": (
        "`TruckAssetCorrelation` is a table with five relationships and no reader and no "
        "writer anywhere in `app/` — not a dead schema so much as a dead entity, which is a "
        "different conversation from this one and belongs to whoever designed it. Deleting a "
        "table is not a mechanical fix; recorded rather than acted on."
    ),
}


def _write_schema_names() -> set[str]:
    tree = ast.parse(SCHEMAS.read_text())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and node.name.endswith(("Create", "Update", "Request"))
        and isinstance(getattr(schemas, node.name, None), type)
        and issubclass(getattr(schemas, node.name), BaseModel)
    }


def _referenced_inside_schemas() -> set[str]:
    """Names used within `schemas.py` itself — crucially including base classes.

    This function is the correction. Without it `AlarmCreate` reads as dead, because the
    only thing that uses it is `class AlarmResponse(AlarmCreate)` in the same file.
    """
    tree = ast.parse(SCHEMAS.read_text())
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            used.update(ast.unparse(base) for base in node.bases)
        elif isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    return used


def _unreferenced() -> list[str]:
    elsewhere = "\n".join(
        p.read_text() for p in APP.rglob("*.py") if p != SCHEMAS
    ) + "\n".join(p.read_text() for p in TESTS.glob("*.py"))
    internal = _referenced_inside_schemas()
    return sorted(
        name
        for name in _write_schema_names()
        if name not in internal and not re.search(rf"\b{name}\b", elsewhere)
    )


class TestTheRouteTakesABody:
    def test_the_correlation_update_declares_a_json_body(self):
        from app.main import app

        operation = app.openapi()["paths"][CORRELATION_PATH]["put"]
        content = (operation.get("requestBody") or {}).get("content", {})
        assert "application/json" in content, (
            "the correlation update takes its fields as query parameters again. A client "
            "sending the obvious JSON body gets 200 and no change — the quietest possible "
            "failure, and the one this route shipped with."
        )

    def test_it_no_longer_declares_those_fields_as_query_parameters(self):
        """The other half. A body could be added while the scalars stayed, and then the
        route would accept both and honour whichever FastAPI resolved first."""
        from app.main import app

        operation = app.openapi()["paths"][CORRELATION_PATH]["put"]
        query = {
            p["name"] for p in operation.get("parameters", []) if p.get("in") == "query"
        }
        assert not query & {"correlation_strength", "confidence_score", "is_active"}, (
            f"these are still query parameters: {sorted(query)}"
        )

    def test_the_sibling_routes_it_was_aligned_with_still_take_bodies(self):
        """The argument for changing this route was that its three neighbours take their
        model and it was the outlier. If that stops being true the reasoning is stale."""
        from app.main import app

        spec = app.openapi()
        for path, method in (
            ("/api/v1/registries/{registry_id}", "put"),
            ("/api/v1/registries/items/{item_id}", "put"),
            ("/api/v1/registries/correlations", "post"),
        ):
            content = (spec["paths"][path][method].get("requestBody") or {}).get("content", {})
            assert "application/json" in content, f"{method.upper()} {path} no longer takes a body"


class TestACorrelationCanBeCompleted:
    def test_the_endpoints_are_editable(self):
        """`source_id`/`target_id` are optional on create and were absent from the update, so
        a correlation naming two *types* and no *ids* was permanently incomplete."""
        for field in ("source_id", "target_id", "source_type", "target_type"):
            assert field in schemas.DataCorrelationUpdate.model_fields

    def test_the_context_field_is_editable(self):
        assert "correlation_meta_data" in schemas.DataCorrelationUpdate.model_fields

    def test_an_endpointless_correlation_is_still_creatable(self):
        """The premise. If the create schema ever requires the ids, the defect above stops
        existing and this file's reasoning should be re-read rather than trusted."""
        created = schemas.DataCorrelationCreate(
            correlation_type="task_to_asset", source_type="task", target_type="asset"
        )
        assert created.source_id is None and created.target_id is None

    def test_an_update_that_sends_one_field_carries_only_that_field(self):
        import uuid

        payload = schemas.DataCorrelationUpdate(source_id=uuid.uuid4())
        assert set(payload.model_dump(exclude_unset=True)) == {"source_id"}


class TestNoWriteSchemaIsWiredToNothing:
    def test_the_sweep_sees_the_schemas(self):
        assert len(_write_schema_names()) > 30, "the class walk has stopped finding schemas"

    def test_a_base_class_is_not_reported_as_unused(self):
        """The correction, asserted. `AlarmResponse(AlarmCreate)` is the only use of
        `AlarmCreate` and it lives in the file the first sweep excluded wholesale."""
        assert "AlarmCreate" in _referenced_inside_schemas()
        assert "AlarmCreate" not in _unreferenced()

    def test_a_wired_schema_is_not_reported(self):
        """Negative control. `DataCorrelationUpdate` was on the unused list until this
        change wired it, so it is the one name that proves the sweep tracks reality."""
        assert "DataCorrelationUpdate" not in _unreferenced()

    def test_only_the_recorded_entries_are_unwired(self):
        unexpected = [name for name in _unreferenced() if name not in UNWIRED]
        assert not unexpected, (
            f"{unexpected}\n\n"
            f"A write schema nothing references is either an endpoint somebody meant to "
            f"build or code that should go, and a reader cannot tell which — "
            f"`DataCorrelationUpdate` sat here while the route it belonged to took query "
            f"parameters instead. Wire it, delete it, or add it to UNWIRED with the reason."
        )

    def test_the_recorded_entries_still_exist(self):
        """A register naming a schema that has since been deleted is an exemption nobody
        can audit, and it would silently permit the next one."""
        for name in UNWIRED:
            assert hasattr(schemas, name), f"{name} is recorded as unwired and no longer exists"
