"""No module may hand-roll the tenant-bound session. There were two that did.

`app.core.tenant.tenant_session` was extracted because the test harness had four hand-copied
overrides of `get_tenant_db`, each under a comment reading *"Mirrors the production
get_tenant_db"* — and each mirroring the RLS-after-commit defect as faithfully as the
behaviour, which is why the suite could not see it.
`test_tenant_guc_survives_commit_realdb.py::TestNoTestDoubleReimplementsIt` closed that for the
TEST doubles.

**Production had two more, and that guard could not see them.** `ExportProcessor._tenant_session`
and `BulkProcessor._tenant_session` were `@asynccontextmanager`s yielding a session bound with an
inline `set_config`, under the same *"Mirrors app.core.tenant.get_tenant_db"* docstring. They now
delegate. This file is the guard that keeps the third one from being written.

WHY THEY WERE NOT SIMPLY EQUIVALENT. Both used a SESSION-scoped GUC —
`set_config(..., false)` — because the binding had to survive intermediate commits, and reset it
to `''` in a `finally` so it could not leak onto a pooled connection. That reasoning is sound and
the reset was there, but it holds only while the reset actually runs. `tenant_session` gets the
same survive-the-commit property from an `after_begin` listener with a TRANSACTION-scoped GUC:
nothing outlives the transaction, so there is nothing to reset and no path where a leak depends
on cleanup running.

WHAT THIS FILE DOES NOT FORBID. Roughly thirty call sites bind the GUC inline before a block of
background work, without wrapping it in a reusable helper. Those are not reimplementations of
this helper and are not flagged here — `TestNoBoundSessionOutlivesItsTransaction` covers the one
way they go wrong instead.
"""

from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

GUC = "set_config('app.current_org_id'"

#: The one module allowed to define the helper.
OWNER = "app/core/tenant.py"

#: What counts as "still talking to the database" after a commit.
#:
#: A bare ``.get(`` was in this list for one run and produced a false positive immediately:
#: `report_download_audit._insert_audit` logs `details.get("reason")` in its exception handler,
#: which is a dict lookup in an error path and not a query at all. The receiver has to be named
#: for the primary-key form to mean anything — hence `session.get(` / `db.get(` rather than
#: `.get(`. A detector that reports a logger line is a detector nobody will keep.
_DB_STATEMENT_TOKENS = (".execute(", ".add(", ".scalar(", "session.get(", "db.get(")


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(APP.parent))


def _async_context_managers_binding_the_guc() -> dict[str, list[str]]:
    """`{file: [function names]}` for every `@asynccontextmanager` that binds the tenant GUC."""
    found: dict[str, list[str]] = {}
    for path in sorted(APP.rglob("*.py")):
        source = path.read_text()
        if GUC not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover - the app must parse
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = {
                d.attr if isinstance(d, ast.Attribute) else getattr(d, "id", "")
                for d in node.decorator_list
            }
            if "asynccontextmanager" not in decorators:
                continue
            body = ast.get_source_segment(source, node) or ""
            # A DELEGATING wrapper quotes the GUC only in its docstring, explaining what it
            # used to do. Judge the code, not the prose — the same trap this repository has
            # hit three times (rule 37).
            code = ast.unparse(
                ast.Module(
                    body=[n for n in node.body if not _is_docstring(n)], type_ignores=[]
                )
            )
            # `ast.unparse` re-quotes string literals, so match on the GUC NAME rather than
            # on the `set_config('...` spelling, which survives neither round-trip reliably.
            if body and "app.current_org_id" in code:
                found.setdefault(_relative(path), []).append(node.name)
    return found


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(
        node.value.value, str
    )


class TestTheScanIsNotVacuous:
    def test_it_sees_the_helper_it_is_protecting(self):
        """`tenant_session` itself is an `@asynccontextmanager` that binds the GUC. If the scan
        cannot find that one, it can find nothing, and every assertion below is decoration."""
        found = _async_context_managers_binding_the_guc()
        assert OWNER in found, (
            f"the scan did not find the canonical helper in {OWNER}; it is inspecting nothing. "
            f"Found: {found}"
        )
        assert "tenant_session" in found[OWNER]

    def test_it_would_flag_a_new_copy(self):
        """A positive control, because the assertion this file exists for is a NEGATIVE one and
        a negative assertion over a broken scan passes for the wrong reason (rule 21). This is
        the shape the two production copies had, parsed in isolation."""
        source = (
            "from contextlib import asynccontextmanager\n"
            "@asynccontextmanager\n"
            "async def _tenant_session(self, organization_id):\n"
            '    """Mirrors app.core.tenant.get_tenant_db."""\n'
            "    async with AsyncSessionLocal() as session:\n"
            "        await session.execute(\n"
            "            text(\"SELECT set_config('app.current_org_id', :org, false)\"),\n"
            "            {'org': str(organization_id)},\n"
            "        )\n"
            "        yield session\n"
        )
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))
        code = ast.unparse(
            ast.Module(body=[n for n in fn.body if not _is_docstring(n)], type_ignores=[])
        )
        assert "app.current_org_id" in code, (
            "the scan strips docstrings and then looks for the GUC in the remaining code; on "
            "this deliberately-bad sample it must still find it"
        )

    def test_a_delegating_wrapper_is_not_flagged(self):
        """The other half of the control. The two fixed helpers keep a docstring that quotes
        `set_config` to explain what they used to do — prose about a defect gathers around the
        defect (rule 37), and a scan that judged the docstring would report the fix as the bug."""
        source = (
            "from contextlib import asynccontextmanager\n"
            "@asynccontextmanager\n"
            "async def _tenant_session(self, organization_id):\n"
            '    """It used to call set_config(\'app.current_org_id\', :org, false) itself."""\n'
            "    async with tenant_session(organization_id) as session:\n"
            "        yield session\n"
        )
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))
        code = ast.unparse(
            ast.Module(body=[n for n in fn.body if not _is_docstring(n)], type_ignores=[])
        )
        assert "app.current_org_id" not in code


class TestOnlyOneModuleDefinesIt:
    def test_no_other_module_reimplements_the_bound_session(self):
        """THE ASSERTION THIS FILE EXISTS FOR. Two production modules did, for months, under a
        docstring that said so in as many words."""
        found = _async_context_managers_binding_the_guc()
        offenders = {f: names for f, names in found.items() if f != OWNER}
        assert not offenders, (
            f"these modules hand-roll a tenant-bound session instead of using "
            f"app.core.tenant.tenant_session: {offenders}.\n"
            "A copy mirrors the original's defects and then keeps them after the original is "
            "fixed — which is exactly how the GUC-lost-on-commit defect survived in four test "
            "doubles and two services. Delegate:\n"
            "    async with tenant_session(organization_id) as session:\n"
            "        yield session"
        )

    def test_nobody_resets_the_guc_by_hand(self):
        """`set_config('app.current_org_id', '', false)` is the cleanup a SESSION-scoped binding
        needs so it cannot ride a pooled connection into the next request. Its presence means
        someone bound the tenant for longer than a transaction — and the leak it guards against
        then depends on that cleanup running. `tenant_session` binds per transaction, so there
        is nothing to reset."""
        offenders = [
            _relative(p)
            for p in sorted(APP.rglob("*.py"))
            if "set_config('app.current_org_id', '', " in p.read_text()
        ]
        assert not offenders, (
            f"these modules reset the tenant GUC by hand, which means they set it "
            f"session-scoped: {offenders}. Use tenant_session, which binds per transaction."
        )


class TestNoBoundSessionOutlivesItsTransaction:
    """The failure mode the ~thirty inline call sites can have.

    `set_config('app.current_org_id', :org, true)` is TRANSACTION-scoped. Set it once, commit,
    and every statement after that commit runs unbound — reads return nothing and writes are
    rejected, both silently on a table that is merely ENABLEd rather than FORCEd. That is the
    defect `tenant_session`'s `after_begin` listener exists to remove, and `run_erp_sync` is one
    `await db.commit()` away from it today.
    """

    @staticmethod
    def _offenders() -> list[str]:
        hits: list[str] = []
        for path in sorted(APP.rglob("*.py")):
            source = path.read_text()
            if GUC not in source:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                segment = ast.get_source_segment(source, node) or ""
                if GUC not in segment:
                    continue
                lines = [line for line in segment.splitlines()
                         if not line.lstrip().startswith("#")]
                try:
                    i_guc = next(i for i, line in enumerate(lines) if GUC in line)
                except StopIteration:
                    continue
                after = lines[i_guc + 1:]
                i_commit = next(
                    (i for i, line in enumerate(after) if ".commit()" in line), None
                )
                if i_commit is None:
                    continue
                tail = after[i_commit + 1:]
                if any(tok in line for line in tail for tok in _DB_STATEMENT_TOKENS):
                    hits.append(f"{_relative(path)}::{node.name}")
        return hits

    def test_the_detector_fires_on_the_shape(self):
        """Positive control. The assertion below is that a list is empty, and an empty list is
        the same answer a broken detector gives (rule 21)."""
        offenders = []
        source = (
            "async def sync(org):\n"
            "    async with AsyncSessionLocal() as db:\n"
            "        await db.execute(\n"
            "            text(\"SELECT set_config('app.current_org_id', :org, true)\"),\n"
            "            {'org': org},\n"
            "        )\n"
            "        await db.commit()\n"
            "        await db.execute(insert_something())\n"
        )
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))
        lines = (ast.get_source_segment(source, fn) or "").splitlines()
        i_guc = next(i for i, line in enumerate(lines) if GUC in line)
        after = lines[i_guc + 1:]
        i_commit = next(i for i, line in enumerate(after) if ".commit()" in line)
        if any(".execute(" in line for line in after[i_commit + 1:]):
            offenders.append("sample")
        assert offenders == ["sample"], (
            "the detector does not fire on a function that binds the tenant, commits, and then "
            "keeps writing — so its silence on the real tree means nothing"
        )

    def test_the_detector_ignores_a_dict_lookup_in_an_error_path(self):
        """The negative control, and it is here because the detector WAS wrong first. With a
        bare `.get(` in the statement list it flagged `report_download_audit._insert_audit`,
        whose only line after the commit is `logger.error(..., reason=details.get("reason"))` —
        a dict lookup in an exception handler. A detector that reports a logger line trains
        people to ignore it."""
        tail = ['        logger.error("failed", reason=details.get("reason"))']
        assert not any(tok in line for line in tail for tok in _DB_STATEMENT_TOKENS)

    def test_no_production_path_keeps_working_after_the_commit(self):
        offenders = self._offenders()
        assert not offenders, (
            f"these functions bind the tenant GUC transaction-scoped, commit, and then issue "
            f"more statements — everything after the commit runs UNBOUND: {offenders}.\n"
            "Use app.core.tenant.tenant_session, which re-asserts the tenant on every "
            "after_begin."
        )
