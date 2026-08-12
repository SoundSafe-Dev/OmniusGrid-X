"""A write field TypeScript calls optional that the server requires (FS-672).

`AssetCreate.workcellId` was declared `workcellId?: string`. `POST /assets/` requires it —
`assets.workcell_id` has been NOT NULL since migration 013 — so a caller who believed the `?`
gets a 422. Nothing constructs an `AssetCreate` today, so nothing was failing; the `?` was a
trap set for whoever writes the asset form, which is precisely the reason FS-423 deleted three
other fields from these interfaces rather than leaving them as harmless noise.

THE DIRECTION MATTERS. `test_frontend_fields_exist_on_the_wire.py` sweeps the other way — a TS
field the wire never carries, where the client believes in something the server does not have.
This is the client believing it may omit something the server insists on: the same seam, the
opposite failure, and a guard for one says nothing about the other.

COVERAGE, STATED RATHER THAN IMPLIED. Interfaces are paired with backend models **by identical
name**, which reaches 6 of 133 TS interfaces. That is the honest reach of a name-based pairing
and it is asserted below so it cannot quietly fall to zero — but it is not "the frontend is
checked". Fourteen required fields are compared, thirteen of which agree, and those thirteen
are what stops this file from being a restatement of the one defect that motivated it.
"""

from __future__ import annotations

import pathlib
import re

from pydantic import BaseModel

from app.models import schemas

TYPES = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "types"

#: Only `*Create` / `*Update` shapes. A response interface marking a field optional is a
#: different claim — it is the client tolerating a field the server may omit, which is
#: defensive rather than wrong.
WRITE_SUFFIXES = ("Create", "Update", "Request")


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(word.title() for word in rest)


def _interfaces() -> dict[str, tuple[str, dict[str, bool]]]:
    """name -> (file, {field: is_optional}). Comment lines are skipped: a `//` line mentioning
    a removed field would otherwise be read as a declaration of it (rule 37)."""
    found: dict[str, tuple[str, dict[str, bool]]] = {}
    for path in sorted(TYPES.glob("*.ts")):
        for match in re.finditer(
            r"export interface (\w+)\s*\{(.*?)\n\}", path.read_text(), re.S
        ):
            fields: dict[str, bool] = {}
            for line in match.group(2).splitlines():
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                field = re.match(r"\s*(\w+)(\??):", line)
                if field:
                    fields[field.group(1)] = field.group(2) == "?"
            found[match.group(1)] = (path.name, fields)
    return found


def _pairs():
    """(ts_name, file, ts_fields, model) for every interface named like a backend model."""
    for name, (filename, fields) in sorted(_interfaces().items()):
        model = getattr(schemas, name, None)
        if isinstance(model, type) and issubclass(model, BaseModel):
            yield name, filename, fields, model


def _compared():
    for name, filename, fields, model in _pairs():
        for py_field, info in model.model_fields.items():
            if not info.is_required():
                continue
            ts_field = _camel(py_field)
            if ts_field in fields:
                yield name, filename, ts_field, fields[ts_field]


class TestTheComparisonIsReal:
    def test_interfaces_are_parsed(self):
        assert len(_interfaces()) > 100, (
            f"only {len(_interfaces())} TS interfaces parsed; the regex has stopped "
            f"matching and every assertion below is vacuously true"
        )

    def test_some_interfaces_pair_with_a_model(self):
        paired = [p[0] for p in _pairs()]
        assert len(paired) >= 5, (
            f"only {len(paired)} interfaces pair with a backend model by name ({paired}); "
            f"a rename has broken the pairing and this file now checks nothing"
        )

    def test_required_fields_are_actually_compared(self):
        """Vacuity, one level down: the pairing could survive while every required field
        is absent from the TS side, and the sweep would still report clean."""
        compared = list(_compared())
        assert len(compared) >= 10, (
            f"only {len(compared)} required fields found on both sides; the snake-to-camel "
            f"conversion or the field regex has stopped lining up"
        )

    def test_the_agreeing_majority_is_the_negative_control(self):
        """Thirteen of fourteen agree. If that number collapses, this file is calling
        correct code wrong rather than finding anything."""
        agreeing = [c for c in _compared() if not c[3]]
        assert len(agreeing) >= 10, (
            f"only {len(agreeing)} required fields are correctly non-optional in TS; "
            f"the guard is now reporting more defects than the tree plausibly has"
        )


def test_no_write_field_is_optional_in_typescript_and_required_on_the_server():
    wrong = sorted(
        f"{filename}:{name}.{ts_field} is `{ts_field}?` and the server requires it"
        for name, filename, ts_field, optional in _compared()
        if optional and name.endswith(WRITE_SUFFIXES)
    )
    assert not wrong, (
        f"{wrong}\n\n"
        f"TypeScript will accept a call that omits the field and the server answers 422. "
        f"Nothing may be constructing the type today — that makes it a trap for the next "
        f"person rather than a live failure, which is the same reason FS-423 deleted "
        f"fields these interfaces named but the endpoint could not apply."
    )


class TestTheInstance:
    def test_a_workcell_is_required_to_create_an_asset(self):
        fields = _interfaces()["AssetCreate"][1]
        assert fields.get("workcellId") is False, (
            "AssetCreate.workcellId is optional in TypeScript; assets.workcell_id has been "
            "NOT NULL since migration 013 and the create schema declares it required"
        )

    def test_the_backend_still_requires_it(self):
        """The other half of the pair. If the server ever makes it optional this test is
        what says the TS `?` may come back, rather than someone re-deriving it."""
        assert schemas.AssetCreate.model_fields["workcell_id"].is_required()

    def test_the_update_type_offers_both_moveable_fields(self):
        """FS-672's frontend half: `workcellId` was removed from `AssetUpdate` because the
        endpoint refused it, and the endpoint no longer does."""
        fields = _interfaces()["AssetUpdate"][1]
        assert "workcellId" in fields and "assetTypeId" in fields
