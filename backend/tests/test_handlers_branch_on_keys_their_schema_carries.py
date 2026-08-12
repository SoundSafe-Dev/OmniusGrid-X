"""A handler that branches on a key its schema cannot carry (FS-672).

`update_asset` contains a tenant-scoped validation block: if the caller sends `workcell_id`,
look the workcell up **within the caller's organization** and 404 if it belongs to someone
else. Somebody wrote that deliberately — it is the cross-tenant check the create path also
does, and it is the reason moving an asset between workcells would be safe.

`AssetUpdate` has no `workcell_id` field. `"workcell_id" in update_data` is therefore always
False, the block has never run, and **an asset cannot be moved between workcells at all** — a
sensor registered against the wrong line stays there for the life of the row. The dead check is
what makes it a defect rather than a missing feature: the intent is in the file.

`asset_type_id` is the same omission without the tell, and is added alongside with the
existence check the create path performs (asset types are a **global catalog**, explicitly not
tenant-scoped — `GET /assets/types/` says so — so existence is the whole check, and skipping it
turns a bad id into a foreign-key 500 rather than a 400).

THE SWEEP. For every API handler taking a pydantic model, follow the variable it dumps into
and require every key read off that dump to exist on the model. Ten sites, eight reachable —
`user_management.update_user` reading `role` and `is_active` is the negative control, and it
is a real one rather than a constructed one.

DETECTOR CALIBRATION, twice. The first version matched `'key' in update_data` textually against
a fixed list of variable names and found **one key across forty-three handlers** — a detector
with no negative control is not a sweep, it is a restatement of the thing you already found.
The second followed the dump variable properly and flagged two `organization_id` sites that
were `payload["organization_id"] = org_id` — assignments, not reads. A subscript is only a read
when its context is `Load`, and a detector that cannot tell a write from a read reports the
server correcting a value as the server depending on one.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from pydantic import BaseModel

from app.models import schemas

API = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"


def _model_params(fn: ast.AST) -> dict[str, type[BaseModel]]:
    params: dict[str, type[BaseModel]] = {}
    for arg in list(fn.args.args) + list(fn.args.kwonlyargs):
        if arg.annotation is None:
            continue
        model = getattr(schemas, ast.unparse(arg.annotation), None)
        if isinstance(model, type) and issubclass(model, BaseModel):
            params[arg.arg] = model
    return params


def _dump_vars(fn: ast.AST, params: dict) -> dict[str, type[BaseModel]]:
    """`update_data = asset_data.model_dump(...)` -> {'update_data': AssetUpdate}.

    Followed rather than guessed. The name is `update_data` here, `payload` next door and
    `data` elsewhere, and a fixed list of names is how the first draft came back nearly empty.
    """
    dumps: dict[str, type[BaseModel]] = {}
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in ("model_dump", "dict")
            and isinstance(func.value, ast.Name)
            and func.value.id in params
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    dumps[target.id] = params[func.value.id]
    return dumps


def _sites():
    """(file, handler, model, key, reachable) for every key READ off a dumped model."""
    for path in sorted(API.glob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            params = _model_params(fn)
            if not params:
                continue
            dumps = _dump_vars(fn, params)
            for node in ast.walk(fn):
                key = var = None
                if (
                    isinstance(node, ast.Compare)
                    and len(node.ops) == 1
                    and isinstance(node.ops[0], ast.In)
                    and isinstance(node.left, ast.Constant)
                    and isinstance(node.left.value, str)
                    and isinstance(node.comparators[0], ast.Name)
                    and node.comparators[0].id in dumps
                ):
                    key, var = node.left.value, node.comparators[0].id
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in dumps
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    key, var = node.args[0].value, node.func.value.id
                elif (
                    isinstance(node, ast.Subscript)
                    # LOAD ONLY. `payload["organization_id"] = org_id` is the server
                    # overriding a tenant field, which the second draft reported as the
                    # server depending on one.
                    and isinstance(node.ctx, ast.Load)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in dumps
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)
                ):
                    key, var = node.slice.value, node.value.id
                if key is None:
                    continue
                model = dumps[var]
                aliases = {f.alias for f in model.model_fields.values() if f.alias}
                yield (
                    path.name,
                    fn.name,
                    model.__name__,
                    key,
                    key in model.model_fields or key in aliases,
                )


class TestTheDetectorIsCalibrated:
    def test_it_finds_sites_at_all(self):
        """Vacuity. The first draft found one key across forty-three handlers and would
        have reported a clean tree for the same reason a broken grep does."""
        sites = list(_sites())
        assert len(sites) >= 8, (
            f"only {len(sites)} dumped-key reads found; the dataflow walk has stopped "
            f"following the dump variable and the assertion below is about nothing"
        )

    def test_a_reachable_key_is_not_flagged(self):
        """Negative control, and a real one: `update_user` reads `role` and `is_active`
        off its dump and both are declared on `UserAdminUpdate`."""
        reachable = [s for s in _sites() if s[4]]
        assert any(s[1] == "update_user" and s[3] == "role" for s in reachable), (
            "the known-good site is missing or is being reported as unreachable, so this "
            "guard is calling correct code wrong"
        )

    def test_a_server_side_override_is_not_a_read(self):
        """`payload["organization_id"] = org_id` appears in `create_asset` and
        `create_dock_door`. Both are the server binding the tenant, and the second draft
        reported both as handlers depending on a field their schema had dropped."""
        for name in ("create_asset", "create_dock_door"):
            assert not [s for s in _sites() if s[1] == name], (
                f"{name} is being reported, and its only dumped-key line is an assignment. "
                f"The Load-context filter has been dropped."
            )


def test_no_handler_branches_on_a_key_its_schema_cannot_carry():
    unreachable = sorted(
        {f"{f}:{fn} reads `{key}` off {model}, which does not declare it" for f, fn, model, key, ok in _sites() if not ok}
    )
    assert not unreachable, (
        f"{unreachable}\n\n"
        f"The branch can never run. Either the schema is missing a field the handler was "
        f"written to accept — which is a capability the product silently does not have — or "
        f"the branch is residue from a field that was removed and should go. A validation "
        f"block that never executes reads, to anyone auditing the file, exactly like one "
        f"that does."
    )


class TestTheAssetCanBeMoved:
    """The instance. Asserted on the schema as well as through the sweep, because the sweep
    would also go quiet if somebody deleted the validation block instead of fixing it."""

    def test_an_asset_can_be_moved_between_workcells(self):
        assert "workcell_id" in schemas.AssetUpdate.model_fields, (
            "an asset registered against the wrong workcell stays there for the life of "
            "the row, and `update_asset` already contains the tenant-scoped check that "
            "would make moving it safe"
        )

    def test_an_assets_type_can_be_corrected(self):
        assert "asset_type_id" in schemas.AssetUpdate.model_fields

    @pytest.mark.parametrize("field", ["workcell_id", "asset_type_id"])
    def test_the_field_is_optional_so_the_update_stays_partial(self, field):
        assert not schemas.AssetUpdate.model_fields[field].is_required(), (
            f"{field} is required on AssetUpdate, so every partial update must now send "
            f"it — the widening has turned a PUT into a full replace"
        )

    def test_an_unsent_field_is_still_excluded(self):
        assert schemas.AssetUpdate().model_dump(exclude_unset=True) == {}


class TestTheNewFieldIsValidatedLikeTheCreatePath:
    """One of the two new foreign keys needs a handler-side check and one does not, and the
    difference was settled by mutation-testing rather than by symmetry with the create path.

    An `asset_type_id` existence check was written here first, mirroring `create_asset`, on
    the stated grounds that a bad id would otherwise be a 500. Removing it left every test
    passing: `app/core/errors.py` maps a foreign-key violation to a 400 naming the column
    and table, which is a better message than the copy produced. So it was deleted. A guard
    whose own mutation test does not fail is asserting the guard exists, not that it works.
    """

    def test_the_workcell_check_is_still_tenant_scoped(self):
        """The check that motivated all of this, and the only assertion that holds it.

        Deleting `Workcell.organization_id == org_id` leaves the whole real-database suite
        green, because RLS hides the other tenant's workcell from that session anyway. RLS
        holding depends on the database ROLE — a connection with BYPASSRLS turns the same
        request into a genuine cross-tenant write — so the predicate is a real control that
        no behavioural test can currently distinguish. That is exactly when a static
        assertion earns its place.
        """
        source = (API / "assets.py").read_text()
        update = source[source.index("async def update_asset") :]
        update = update[: update.index("@router.delete")]
        assert "Workcell.organization_id == org_id" in update
