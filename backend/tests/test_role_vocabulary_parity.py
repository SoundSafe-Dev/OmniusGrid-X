"""The role vocabulary must agree everywhere it is written down (FS-222).

`users.role` was an unconstrained VARCHAR(50) and the vocabulary existed in three
independent places — a private frozenset in sso.py, inline literals in rbac.py, and
a tuple in compliance_reports.py. They had already drifted: two read-only
compliance endpoints were gated on ('admin', 'viewer'), which DENIES `operator`,
the default role every registered user receives.

These tests make the drift impossible to reintroduce silently: the Python
vocabulary, the migration's CHECK constraint, and the model default must all match.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import roles


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "048_user_role_constraint.sql"
)


def _roles_in_migration() -> set[str]:
    """Extract the vocabulary from the CHECK constraint itself."""
    sql = MIGRATION.read_text()
    match = re.search(r"CHECK \(role IN \(([^)]*)\)\)", sql)
    assert match, "could not find the CHECK constraint in migration 048"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


class TestVocabularyParity:
    def test_migration_check_matches_python(self):
        assert _roles_in_migration() == set(roles.ROLES), (
            "the CHECK constraint and app/core/roles.py disagree — one of them "
            "will start rejecting or admitting a role the other does not"
        )

    def test_sso_uses_the_shared_vocabulary(self):
        """sso.py kept its own frozenset; it must now be the same object."""
        from app.core.sso import _APP_ROLES

        assert set(_APP_ROLES) == set(roles.ROLES)

    def test_model_default_is_the_documented_default(self):
        from app.db.models import User

        column = User.__table__.columns["role"]
        assert column.default.arg == roles.DEFAULT_ROLE
        # A server default too: a raw INSERT that omits role would otherwise write
        # NULL, producing an account that matches no dependency.
        assert column.server_default is not None
        assert roles.DEFAULT_ROLE in str(column.server_default.arg)
        assert column.nullable is False


class TestOrdering:
    def test_rank_is_total_and_ascending(self):
        assert roles.ROLE_RANK[roles.VIEWER] < roles.ROLE_RANK[roles.OPERATOR]
        assert roles.ROLE_RANK[roles.OPERATOR] < roles.ROLE_RANK[roles.ADMIN]

    def test_at_least_includes_more_privileged_roles(self):
        assert roles.at_least(roles.ADMIN, roles.VIEWER) is True
        assert roles.at_least(roles.OPERATOR, roles.VIEWER) is True
        assert roles.at_least(roles.VIEWER, roles.OPERATOR) is False

    def test_unknown_role_never_satisfies_a_floor(self):
        """A typo must fail closed, not clear the lowest bar."""
        for bogus in ("Admin", "opperator", "", None, "superuser"):
            assert roles.at_least(bogus, roles.VIEWER) is False

    def test_roles_at_least_viewer_is_everyone(self):
        assert roles.roles_at_least(roles.VIEWER) == roles.ROLES

    def test_roles_at_least_rejects_an_unknown_floor(self):
        with pytest.raises(ValueError):
            roles.roles_at_least("root")


class TestNoHardCodedVocabularyRemains:
    def test_rbac_does_not_hard_code_role_strings(self):
        """The regression guard: rbac.py used to carry "admin" and
        {"admin", "operator"} inline, which is how the drift started.

        Parsed with `ast` rather than grepped. A text search also matches the
        module docstring, which legitimately names the roles while explaining this
        history — a line-based filter cannot tell a multi-line docstring from code,
        and a guard that fails on its own explanation is a guard nobody keeps.
        Only string constants in VALUE positions are a real hard-coding.
        """
        import ast

        src = (
            Path(__file__).resolve().parents[1] / "app" / "middleware" / "rbac.py"
        ).read_text()
        tree = ast.parse(src)

        # Docstrings are Expr(Constant) statements; everything else that is a str
        # constant is being used as a value.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    docstrings.add(id(body[0].value))

        offenders = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in roles.ROLES
            and id(node) not in docstrings
        ]
        assert offenders == [], (
            f"rbac.py hard-codes role literal(s) {sorted(set(offenders))}; "
            "use app/core/roles.py instead"
        )

    def test_require_roles_rejects_an_unknown_role_at_build_time(self):
        from app.middleware.rbac import require_roles

        with pytest.raises(ValueError):
            require_roles("Admin")
        with pytest.raises(ValueError):
            require_roles("operator", "superuser")
