"""Static guard against plain DB sessions on RLS-protected route handlers.

``get_db`` never installs PostgreSQL's ``app.current_org_id`` setting. A route
that uses it to query an RLS-protected table therefore gets an empty result (or
writes nothing) without an error. Every such handler must instead use
``get_tenant_db`` or open a trusted ``tenant_session`` for machine/background
authentication.

The guard works at handler level so mixed modules can keep plain sessions for
genuinely global or pre-authentication routes. It also follows calls to local
helpers and recognizes protected table names in ``text(...)`` SQL. There is no
allowlist: newly introduced debt fails immediately.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
API_DIR = BACKEND / "app" / "api"
DB_DIR = BACKEND / "app" / "db"
MIGRATIONS = BACKEND.parent / "database" / "migrations"

ROUTE_METHODS = {
    "api_route",
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "trace",
    "websocket",
}


def _strip_sql_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    return re.sub(r"--[^\n]*", " ", source)


def _rls_tables() -> set[str]:
    tables: set[str] = set()
    pattern = re.compile(
        r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
        r"(?:\w+\.)?[\"`]?([A-Za-z_][A-Za-z0-9_]*)[\"`]?\s+"
        r"(?:FORCE\s+)?ENABLE\s+ROW\s+LEVEL\s+SECURITY",
        re.I,
    )
    for migration in MIGRATIONS.glob("*.sql"):
        sql = _strip_sql_comments(migration.read_text())
        tables.update(match.group(1).lower() for match in pattern.finditer(sql))
    return tables


def _model_to_table() -> dict[str, str]:
    """Map every declarative model in app/db, not only models.py."""
    mapping: dict[str, str] = {}
    for model_file in DB_DIR.glob("*.py"):
        tree = ast.parse(model_file.read_text(), filename=str(model_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                if not any(isinstance(target, ast.Name) and target.id == "__tablename__" for target in targets):
                    continue
                value = statement.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    mapping[node.name] = value.value.lower()
    return mapping


def _leaf_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_route_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _leaf_name(target) in ROUTE_METHODS:
            return True
    return False


def _plain_db_dependency_names(tree: ast.Module) -> set[str]:
    names = {"get_db"}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for imported in node.names:
            if imported.name == "get_db":
                names.add(imported.asname or imported.name)
    return names


def _local_model_mapping(
    tree: ast.Module,
    model_to_table: dict[str, str],
) -> dict[str, str]:
    """Include ``from ... import Asset as AssetRow`` aliases in the scan."""
    mapping = dict(model_to_table)
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for imported in node.names:
            table = model_to_table.get(imported.name)
            if table is not None:
                mapping[imported.asname or imported.name] = table
    return mapping


def _depends_on_plain_db(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    dependency_names: set[str],
) -> bool:
    expressions: list[ast.AST] = []
    arguments = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    expressions.extend(argument.annotation for argument in arguments if argument.annotation)
    expressions.extend(function.args.defaults)
    expressions.extend(default for default in function.args.kw_defaults if default is not None)
    for expression in expressions:
        for node in ast.walk(expression):
            if not isinstance(node, ast.Call) or _leaf_name(node.func) != "Depends":
                continue
            if any(_leaf_name(argument) in dependency_names for argument in node.args):
                return True
    return False


class _FunctionFacts(ast.NodeVisitor):
    """Collect protected models/SQL and local calls from one function body."""

    def __init__(self, model_to_table: dict[str, str], rls_tables: set[str]) -> None:
        self.model_to_table = model_to_table
        self.rls_tables = rls_tables
        self.tables: set[str] = set()
        self.calls: set[str] = set()

    def _record_model(self, name: str) -> None:
        table = self.model_to_table.get(name)
        if table in self.rls_tables:
            self.tables.add(table)

    def visit_Name(self, node: ast.Name) -> None:
        self._record_model(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._record_model(node.attr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        callee = _leaf_name(node.func)
        if isinstance(node.func, ast.Name):
            self.calls.add(node.func.id)
        if callee == "text":
            sql = " ".join(
                value.value
                for value in ast.walk(node)
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            ).lower()
            self.tables.update(
                table
                for table in self.rls_tables
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(table)}(?![A-Za-z0-9_])", sql)
            )
        self.generic_visit(node)

    # A nested definition is not executed merely because its parent is called.
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def _function_facts(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    model_to_table: dict[str, str],
    rls_tables: set[str],
) -> tuple[set[str], set[str]]:
    visitor = _FunctionFacts(model_to_table, rls_tables)
    body = function.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body = body[1:]
    for statement in body:
        visitor.visit(statement)
    return visitor.tables, visitor.calls


def _find_offenders_in_source(
    source: str,
    model_to_table: dict[str, str],
    rls_tables: set[str],
    filename: str = "<source>",
) -> list[tuple[str, str, tuple[str, ...]]]:
    tree = ast.parse(source, filename=filename)
    local_models = _local_model_mapping(tree, model_to_table)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    facts = {
        name: _function_facts(function, local_models, rls_tables)
        for name, function in functions.items()
    }

    def protected_tables(name: str, visiting: set[str] | None = None) -> set[str]:
        visiting = set() if visiting is None else visiting
        if name in visiting:
            return set()
        visiting.add(name)
        direct_tables, calls = facts[name]
        tables = set(direct_tables)
        for called in calls & facts.keys():
            tables.update(protected_tables(called, visiting))
        visiting.remove(name)
        return tables

    dependency_names = _plain_db_dependency_names(tree)
    findings: list[tuple[str, str, tuple[str, ...]]] = []
    for name, function in functions.items():
        if not _is_route_handler(function):
            continue
        if not _depends_on_plain_db(function, dependency_names):
            continue
        tables = protected_tables(name)
        if tables:
            findings.append((filename, name, tuple(sorted(tables))))
    return findings


def _offenders() -> list[tuple[str, str, tuple[str, ...]]]:
    model_to_table = _model_to_table()
    rls_tables = _rls_tables()
    findings: list[tuple[str, str, tuple[str, ...]]] = []
    for path in sorted(API_DIR.glob("*.py")):
        findings.extend(
            _find_offenders_in_source(
                path.read_text(),
                model_to_table,
                rls_tables,
                filename=path.name,
            )
        )
    return findings


def test_rls_metadata_is_detected_without_comment_false_positives():
    tables = _rls_tables()
    models = _model_to_table()
    assert {"assets", "audit_logs", "integration_configurations"} <= tables
    assert "t" not in tables  # example SQL in a migration comment
    assert len(tables) >= 50, f"suspiciously few RLS tables found: {len(tables)}"
    assert models["Asset"] == "assets"
    assert models["IntegrationConfiguration"] == "integration_configurations"


def test_guard_detects_only_plain_session_handlers_touching_rls_models():
    source = '''
from fastapi import Depends

async def load_asset(db):
    return await db.execute(select(Asset))

@router.get("/bad")
async def bad(db=Depends(get_db)):
    return await load_asset(db)

@router.get("/good")
async def good(db=Depends(get_tenant_db)):
    return await db.execute(select(Asset))

@router.get("/global")
async def global_route(db=Depends(get_db)):
    return await db.execute(select(User))
'''
    findings = _find_offenders_in_source(
        source,
        {"Asset": "assets", "User": "users"},
        {"assets"},
        filename="fixture.py",
    )
    assert findings == [("fixture.py", "bad", ("assets",))]


def test_guard_detects_protected_raw_sql_and_aliased_get_db():
    source = '''
from app.db.database import get_db as plain_db
from app.db.models import Asset as AssetRow

@router.post("/bad")
async def bad(db=Depends(plain_db)):
    await db.execute(select(AssetRow))
    return await db.execute(text("UPDATE audit_logs SET action = 'x'"))
'''
    assert _find_offenders_in_source(
        source,
        {"Asset": "assets"},
        {"assets", "audit_logs"},
    ) == [
        ("<source>", "bad", ("assets", "audit_logs"))
    ]


def test_no_api_handler_uses_get_db_for_an_rls_protected_table():
    findings = _offenders()
    rendered = "\n".join(
        f"  {filename}:{handler} -> {', '.join(tables)}"
        for filename, handler, tables in findings
    )
    assert not findings, (
        "These route handlers touch RLS-protected tables through get_db. "
        "Use get_tenant_db for user-authenticated routes or tenant_session for "
        f"trusted machine/background authentication:\n{rendered}"
    )
