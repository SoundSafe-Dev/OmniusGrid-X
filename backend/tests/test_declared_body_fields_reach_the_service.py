"""A body field the schema declares and the handler never reads (FS-663).

THE CLASS. `POST /yard/checkpoints` declared `inspector_id` and `metadata`, returned them, had
columns for both, and passed neither to the service — accepted, discarded, echoed back as the
default. Three more turned up the same day, and the last one was not merely lossy:

    get_carrier_compliance:  is_valid = certified AND expires_at AND expires_at > now

`POST /carriers` passed `ctpat_certified` and dropped `ctpat_expires_at`, so every carrier
created through the API reported its certification **invalid**. A wrong answer computed from
the dropped field, with a 200 on the way in.

TWO TIERS, because the severities are not comparable.

**Absolute** — no route may pass a boolean and drop the field that bounds it (rule 143). A
certification with no expiry, a seal with no status, an inspection with no inspector: each is
a positive claim that cannot be checked, and each is the more reassuring of the two possible
readings. This set is empty and may not gain a member.

**Ratcheted** — the general case, where a declared field never reaches the service. Nine routes
carry one, most in other lanes, and several are lifecycle fields wrongly declared on a Create
schema rather than data loss. Recording them separates a decision from an oversight without
demanding work from lanes that did not ask for it; the register only shrinks.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
API_DIR = REPO / "backend" / "app" / "api"
MODEL_DIR = REPO / "backend" / "app" / "models"

#: The file is SPLIT on the decorator rather than matched across it. A single regex spanning
#: decorator-to-next-decorator needs a bounded body window, and a handler longer than that
#: window fails to match — taking the FOLLOWING decorator with it, because `finditer` resumes
#: past the failed attempt. That silently hid nine of yard's twelve routes, including the one
#: this guard uses as its control, and the sweep still looked plausible.
ROUTE_HEAD = re.compile(
    r'^@router\.(post|put|patch)\("([^"]*)"', re.M
)
BODY_PARAM = re.compile(r"\b(\w+)\s*:\s*(\w+(?:Create|Update|Request|Input|In))\b")

#: Field-name shapes that QUALIFY a boolean: when does it lapse, who did it, what state is it
#: in. Deliberately narrow — a wide pattern would drag in every id on every schema and the
#: absolute tier below would become a second ratchet.
QUALIFIER = re.compile(r"(_expires_at|_at$|_by$|_status$|_id$|_reason$|_note)")

#: Routes with a declared field the handler never reads, and why each is tolerated.
#: **Only ever shrinks.** Measured 2026-08-12.
#: `metadata` ONCE APPEARED ON NINE OF THIRTEEN ENTRIES — one defect wearing nine hats rather
#: than nine findings. Every one of those tables has a `meta_data` column the handler never
#: passed, so metadata attached to a shipment, a yard move or a dock appointment vanished with
#: a 200. Closed on the six routes in this lane by FS-669; the one that remains
#: (`logistics_correlation:POST /load-quality`) is Harsh's, and is left for him rather than
#: edited across a lane boundary.
UNREAD: dict[str, list[str]] = {
    #: Harsh's lane.
    "analysis_sessions:POST /{session_id}/correlate": ["auto_integrate"],
    #: `kanban:POST /rules": ["organization_id"]` WAS HERE AND IS CLOSED (FS-677).
    #: It was the thirteenth instance of FS-523 — a required field the handler discards,
    #: so the natural client got a 422 on every rule it tried to create — and it sat here
    #: deferred as another lane's until that lane was explicitly opened. Deleted rather
    #: than reworded: this register only ever shrinks.
    #: DELIBERATE, same shape as the check-in above. Harsh's lane.
    "kanban:POST /tasks": ["status"],
    #: Harsh's lane. Includes `metadata`, the pattern closed on my side by FS-669.
    "logistics_correlation:POST /load-quality": ["claim_amount", "claim_filed", "manufacturing_correlation_score", "metadata", "resolved_at", "root_cause_asset", "root_cause_operation", "trailer_id"],
    #: Harsh's lane.
    "nlp_correlation:POST /intake/cross-correlate": ["auto_integrate"],
    #: SCHEMA-SIDE. `create_route` always runs the optimizer and sets all four from its
    #: result, so honouring a caller's value would let somebody override a computed route
    #: distance — and that distance is billed per mile. `is_active` is the exception:
    #: nothing computes it, and it is genuine creation input.
    "transportation:POST /routes": ["estimated_duration_hours", "fuel_cost_estimate", "is_active", "toll_cost_estimate", "total_distance_miles"],
    #: SCHEMA-SIDE. Every figure is COMPUTED by `close_driver_wait_time` at checkout.
    #: Honouring a caller's `detention_charge` would let an operator bill their own number.
    "yard:POST /driver-wait-times": ["check_out_at", "demurrage_charge", "demurrage_minutes", "detention_charge", "detention_minutes", "docked_at", "is_billed", "total_wait_minutes", "unloaded_at"],
    #: DELIBERATE. The service sets 'checked_in'; honouring a caller's status would let
    #: somebody check a trailer straight to 'checked_out' without it entering the yard.
    "yard:POST /trailers/checkin": ["status"],
}

#: Why the register has members, recorded once rather than nine times. The two kinds are worth
#: telling apart because the fix differs:
#:
#:   * LIFECYCLE STATE on a Create schema — `approved_at`, `billed_at`, `is_executed`,
#:     `actual_start`. The handler is right to ignore them; the SCHEMA is wrong, and an API
#:     that accepts values it will never honour is its own small lie. Fixing means removing
#:     them from the Create model, which is a contract change with clients to check.
#:   * GENUINE CREATION INPUT being lost — `temperature_min`/`max` on a shipment,
#:     `duration_seconds` on a yard move. That is data loss and the fix is wiring.
#:
#: Four of the nine are in Harsh's lane (kanban, logistics_correlation). The rest are recorded
#: rather than fixed in one pass because each needs its own decision about which kind it is.
REGISTER_REASON = "see the module docstring and the note above"


def _schemas() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    fields: dict[str, list[str]] = {}
    bases: dict[str, list[str]] = {}
    for path in list(MODEL_DIR.glob("*.py")) + list(API_DIR.glob("*.py")):
        for m in re.finditer(
            r"^class (\w+)\(([\w., \[\]]*)\):\n((?:    .*\n|\n)*)", path.read_text(), re.M
        ):
            name, base, body = m.groups()
            fields[name] = [
                fm.group(1)
                for fm in re.finditer(r"^    (\w+)\s*:\s*([^=\n]+)", body, re.M)
                if fm.group(1) != "model_config"
            ]
            bases[name] = [b.strip() for b in base.split(",")]
    return fields, bases


def _declared(name: str, fields, bases, seen=()) -> list[str]:
    if name in seen or name not in fields:
        return []
    out = list(fields[name])
    for base in bases.get(name, []):
        out += _declared(base, fields, bases, seen + (name,))
    return out


def _annotations(name: str) -> dict[str, str]:
    """field -> annotation text, for the boolean test. Read from source, first match wins."""
    out: dict[str, str] = {}
    for path in list(MODEL_DIR.glob("*.py")) + list(API_DIR.glob("*.py")):
        for m in re.finditer(
            r"^class (\w+)\(([\w., \[\]]*)\):\n((?:    .*\n|\n)*)", path.read_text(), re.M
        ):
            for fm in re.finditer(r"^    (\w+)\s*:\s*([^=\n]+)", m.group(3), re.M):
                out.setdefault(fm.group(1), fm.group(2).strip())
    return out


def _root_name(node: ast.AST) -> str | None:
    """The variable an expression is rooted at: `request`, for `request.model_copy(update=…)`."""
    while True:
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, (ast.Await, ast.Starred)):
            node = node.value
        else:
            break
    return node.id if isinstance(node, ast.Name) else None


def _attr_reads(node: ast.AST, var: str) -> set[str]:
    return {
        n.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == var
    }


#: stem -> {callable name as it is spelled in that module: (def node, the stem that defines it)}.
#: The second half of the pair is load-bearing: once a call is followed into another router's
#: helper, the names visible from THERE are that module's, not the caller's.
_VISIBLE: dict[str, dict[str, tuple[ast.AST, str]]] = {}


def _visible(stem: str) -> dict[str, tuple[ast.AST, str]]:
    """Functions a router module can call by bare name: its own, plus those it imports from a
    sibling router. Cached, and re-entrant against a mutual import."""
    if stem in _VISIBLE:
        return _VISIBLE[stem]
    _VISIBLE[stem] = {}
    try:
        tree = ast.parse((API_DIR / f"{stem}.py").read_text())
    except (OSError, SyntaxError):  # pragma: no cover - unparseable modules fail elsewhere
        return _VISIBLE[stem]
    out = {
        n.name: (n, stem)
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.api."):
            other = _visible(node.module.split(".")[-1])
            for alias in node.names:
                if alias.name in other:
                    out.setdefault(alias.asname or alias.name, other[alias.name])
    _VISIBLE[stem] = out
    return out


def _forwarded_reads(node, var, stem, depth=0, seen=frozenset()) -> set[str]:
    """Reads of the body that happen inside a helper the handler forwards it to.

    Without this the extractor measures the handler body alone, and a route that hands the whole
    request to a shared executor — the natural shape once three routes want the same work, one
    synchronous, one queued, one preview — reads NOTHING by that measure. Five correlation
    routes landed in exactly that shape and the register would have absorbed all five, including
    `POST /answer`'s `question`, which is the entire point of the route. A register entry that
    says "deliberate" about a field the service does honour is worse than no entry: it teaches
    the next reader that the drop was reviewed.

    Follows a forward two hops, across a `from app.api.… import` as well as within a module,
    because that is exactly the shape here: the handler calls `_run_question`, which lives in
    the correlation router and calls `_execute_evidence_request` beside it. Cycle-guarded on
    (callee, parameter). An imported SERVICE is still a boundary this guard does not cross —
    only routers are read — which is why `model_dump()` remains its own exemption above.
    """
    if depth > 2:
        return set()
    funcs = _visible(stem)
    out: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        resolved = funcs.get(call.func.id)
        if resolved is None:
            continue
        fn, fn_stem = resolved
        positional = [p.arg for p in fn.args.posonlyargs + fn.args.args]
        targets = {
            positional[i]
            for i, arg in enumerate(call.args)
            if i < len(positional) and _root_name(arg) == var
        }
        targets |= {kw.arg for kw in call.keywords if kw.arg and _root_name(kw.value) == var}
        for target in targets:
            if (call.func.id, target) in seen:
                continue
            out |= _attr_reads(fn, target)
            out |= _forwarded_reads(
                fn, target, fn_stem, depth + 1, seen | {(call.func.id, target)}
            )
    return out


def _dumped_locals(tree, var: str) -> list[str]:
    """Locals bound to `var.model_dump(...)` / `var.dict(...)`."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in {"model_dump", "dict"}
            and _root_name(func.value) == var
        ):
            out += [t.id for t in node.targets if isinstance(t, ast.Name)]
    return out


def _dump_is_applied_wholesale(tree, local: str) -> bool:
    """Is every key of `local` applied, whatever those keys turn out to be?

    Two constructs do that and are the reason the `model_dump()` exemption exists at all:
    a splat — `Asset(**payload)`, `NotificationSubscription(**fields)` — and an iteration
    — `for field, value in updates.items(): setattr(row, field, value)`. Both honour a
    field the handler never names, which is exactly what the exemption claims.

    Reading `updates.get("export_format")` is NOT that, and neither is passing the dict to
    a helper that looks at four keys of it.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg is None:
            if _root_name(node.value) == local:
                return True  # f(**local)
        if isinstance(node, ast.Dict) and any(
            k is None and _root_name(v) == local for k, v in zip(node.keys, node.values)
        ):
            return True  # {**local}
        if isinstance(node, (ast.For, ast.AsyncFor)):
            iterated = node.iter
            if isinstance(iterated, ast.Call) and isinstance(iterated.func, ast.Attribute):
                if iterated.func.attr in {"items", "keys"} and _root_name(iterated.func.value) == local:
                    return True  # for k, v in local.items()
            if _root_name(iterated) == local:
                return True  # for k in local
    return False


def _dump_key_reads(tree, local: str) -> set[str]:
    """The keys of `local` a handler names explicitly, including through a literal loop.

    `local["x"]`, `local.get("x")`, `"x" in local`, and the shape `update_task` uses:
    `for field in ("a", "b", ...): setattr(task, field, supplied[field])`, where the names
    are a literal tuple rather than the dict's own keys. That loop honours exactly the
    fields it lists, so the list is the read set.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _root_name(node.value) == local:
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                out.add(node.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and _root_name(node.func.value) == local
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            out.add(node.args[0].value)
        if isinstance(node, ast.Compare) and any(
            isinstance(op, ast.In) for op in node.ops
        ):
            for comparator in node.comparators:
                if _root_name(comparator) == local and isinstance(
                    node.left, ast.Constant
                ) and isinstance(node.left.value, str):
                    out.add(node.left.value)
        if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(
            node.iter, (ast.Tuple, ast.List, ast.Set)
        ):
            names = {
                e.value for e in node.iter.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
            if names and any(
                isinstance(n, ast.Subscript) and _root_name(n.value) == local
                for n in ast.walk(node)
            ):
                out |= names
    return out


#: Callees that INSPECT a dumped body rather than consume it. Passing
#: `data.model_dump()` to one of these says nothing about whether the fields reach the
#: service, so it must not exempt the route.
#:
#: THIS LIST EXISTS BECAUSE THE FIX FOR RULE 234 REPEATED THE MISTAKE IT FIXED. That rule
#: narrowed the exemption from "the handler mentions model_dump" to "the dump is forwarded
#: rather than bound and inspected" — and kept treating any call argument as a forward.
#: Wiring `verify_refs(db, org, data.model_dump(exclude_unset=True))` into twenty handlers
#: then removed three more routes from this sweep and staled three register entries, the
#: identical symptom one level down. A call argument is a forward only if the callee is
#: forwarding it.
INSPECTORS = {"verify_refs", "verify_task_references", "_reject_explicit_nulls"}


def _dump_is_only_inspected(tree, var: str) -> bool:
    """Is every `var.model_dump()` in this handler an argument to an inspector?"""
    dumps, inspected = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in {"model_dump", "dict"}
            and _root_name(func.value) == var
        ):
            dumps.append(node)
        callee = getattr(func, "id", None) or getattr(func, "attr", None)
        if callee in INSPECTORS:
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if (
                    isinstance(arg, ast.Call)
                    and isinstance(arg.func, ast.Attribute)
                    and arg.func.attr in {"model_dump", "dict"}
                    and _root_name(arg.func.value) == var
                ):
                    inspected.append(arg)
    return bool(dumps) and len(inspected) == len(dumps)


def _routes():
    """(key, declared fields, fields the handler reads) for every body-taking route."""
    fields, bases = _schemas()
    for path in sorted(API_DIR.glob("*.py")):
        source = path.read_text()
        heads = list(ROUTE_HEAD.finditer(source))
        for i, head in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(source)
            chunk = source[head.start(): end]
            verb, route = head.group(1), head.group(2)
            bm = BODY_PARAM.search(chunk)
            if not bm:
                continue
            var, model = bm.groups()
            declared = set(_declared(model, fields, bases))
            if not declared:
                continue
            read = set(re.findall(rf"\b{var}\.(\w+)", chunk))
            tree = None
            try:
                tree = ast.parse(chunk)
                read |= _forwarded_reads(tree, var, path.stem)
            except SyntaxError:
                pass
            # `model_dump()` forwards the whole body at once; nothing can be dropped. Checked
            # against the FOLLOWED reads, not the handler text: `POST /answer` dumps the body
            # inside `_run_question`, one hop away, and testing the chunk alone called that a
            # nine-field drop on the route whose whole purpose is to forward the question.
            #
            # BUT ONLY WHEN IT IS ACTUALLY FORWARDED (FS-736). This began as `if read &
            # {"model_dump", "dict"}: continue`, which exempted a route for MENTIONING the
            # call — and a handler that dumps the body to INSPECT it drops just as much as
            # one that never dumped it at all. Adding a validation pass to
            # `kanban:POST /tasks` (`supplied = task_data.model_dump(exclude_unset=True)`,
            # then five ownership checks) removed that route from this sweep entirely, and
            # its live register entry went stale — the guard was weakened by a change that
            # had nothing to do with it, which is the failure mode a register exists to
            # prevent. Measured at the time: 31 of 101 body-taking routes took the
            # exemption, 17 of them by binding the dump to a local.
            #
            # So the exemption now asks what the dump is USED for. Splatted or iterated,
            # every key is applied and the exemption holds. Bound and read key by key, only
            # the named keys count — and the route is measured like any other.
            if tree is not None:
                locals_ = _dumped_locals(tree, var)
                if locals_:
                    if any(_dump_is_applied_wholesale(tree, name) for name in locals_):
                        continue
                    for name in locals_:
                        read |= _dump_key_reads(tree, name)
                elif read & {"model_dump", "dict"} and not _dump_is_only_inspected(
                    tree, var
                ):
                    continue  # dumped straight into a call, a return or a splat
            elif read & {"model_dump", "dict"}:
                continue
            yield f"{path.stem}:{verb.upper()} {route}", declared, read


class TestTheMeasurementIsReal:
    def test_routes_are_found(self):
        routes = list(_routes())
        assert len(routes) > 25, (
            f"only {len(routes)} body-taking routes found; the route regex collapsed and "
            f"every assertion below would be about nothing"
        )

    def test_a_known_complete_route_reads_everything_it_declares(self):
        """Positive control. `POST /yard/checkpoints` was the first instance of this class and
        is now wired end to end, so it must read every field it declares. If this fails the
        extractor is under-counting what a handler reads, and the register would grow with
        routes that are fine."""
        for key, declared, read in _routes():
            if key == "yard:POST /checkpoints":
                assert not (declared - read), f"control route drops {sorted(declared - read)}"
                return
        pytest.fail("the control route was not found at all")

    def test_the_extractor_sees_a_dropped_field(self):
        """Negative control, so the sweep is not passing by reading nothing. The register is
        non-empty by construction; if it were empty this test would be the one to delete."""
        assert any(declared - read for _key, declared, read in _routes())


class TestNoBooleanLosesTheFieldThatBoundsIt:
    """ABSOLUTE, not ratcheted. Rule 143."""

    def test_no_route_passes_a_flag_and_drops_its_qualifier(self):
        annotations = _annotations("")
        offenders = []
        for key, declared, read in _routes():
            for flag in sorted(f for f in declared & read if "bool" in annotations.get(f, "")):
                head = flag.split("_")[0]
                for field in sorted(declared - read):
                    if QUALIFIER.search(field) and field.startswith(head):
                        offenders.append(f"{key}: passes {flag}, drops {field}")
        assert not offenders, (
            f"{offenders} — a boolean is stored and the field that says what it is worth is "
            f"discarded. `POST /carriers` did exactly this and every carrier it created "
            f"reported its certification invalid, because the compliance check reads "
            f"`certified AND expires_at AND expires_at > now`. Pass the qualifier, or take "
            f"the flag off the Create schema."
        )


class TestTheRegisterOnlyShrinks:
    def test_no_new_route_drops_a_declared_field(self):
        new = sorted(
            f"{key}: {sorted(declared - read)}"
            for key, declared, read in _routes()
            if (declared - read) and key not in UNREAD
        )
        assert not new, (
            f"{new} declare body fields the handler never reads. Either pass them to the "
            f"service, or take them off the Create schema — an API that accepts a value it "
            f"will never honour is its own small lie. If neither is right yet, add the route "
            f"to UNREAD with the reason."
        )

    def test_no_recorded_route_drops_more_than_it_did(self):
        """A recorded route may shrink its list, never grow it."""
        grew = []
        for key, declared, read in _routes():
            if key not in UNREAD:
                continue
            extra = sorted((declared - read) - set(UNREAD[key]))
            if extra:
                grew.append(f"{key}: now also drops {extra}")
        assert not grew, f"{grew}. The register may shrink, never grow."

    def test_no_recorded_route_is_already_clean(self):
        """A stale entry overstates the debt and invites the work to be done twice."""
        live = {key: declared - read for key, declared, read in _routes()}
        stale = sorted(
            key for key, fields in UNREAD.items()
            if key not in live or not (set(fields) & live[key])
        )
        assert not stale, (
            f"{stale} are recorded as dropping fields and no longer do, or no longer exist. "
            f"Remove them so the register means something."
        )

    @pytest.mark.parametrize("key", sorted(UNREAD))
    def test_each_recorded_route_still_exists(self, key: str):
        assert key in {k for k, _d, _r in _routes()}, (
            f"{key} is in the register and is not a body-taking route any more"
        )


def test_the_register_is_serialisable_for_a_report():
    """The register is data, not prose, so a status report can be generated from it rather
    than transcribed — the transcription is what goes stale."""
    assert json.dumps(UNREAD)
    assert sum(len(v) for v in UNREAD.values()) > 0
