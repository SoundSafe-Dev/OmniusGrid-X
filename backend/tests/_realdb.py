"""Whether a real-database suite may skip, or must run (FS-808).

Eleven test modules began with the same line:

    pytest.importorskip("testcontainers")

That is right for a laptop — the real-DB suites need a Docker daemon, and a developer
without one should not be blocked. It is wrong for CI, where a skip and a pass are the
same exit code and the same green tick.

THE ONE THAT MATTERS MOST is `test_backup_restore_drill.py`. Its own docstring says "a
backup nobody restores is not a backup", and the whole point of the drill is to stop the
backup becoming a fiction. A drill that silently skips is the same fiction one level up:
the gate reports success, and nobody has restored anything.

`backend-realdb` already runs a preflight `import testcontainers.postgres` step that fails
the job if the dependency is missing, which covers the case it was written for. It does not
cover the shape this closes — the preflight being renamed, moved, or dropped in a workflow
edit, after which every one of these 11 suites skips and the job stays green. The
guarantee should live with the tests, not beside them.

So: `REQUIRE_REALDB=1` turns the skip into a hard failure. CI sets it; a laptop does not.
`test_the_realdb_suites_cannot_silently_skip.py` asserts the workflow still sets it, so
removing it from CI is itself a test failure.
"""

from __future__ import annotations

import os

import pytest


#: Set by the `backend-realdb` job in .github/workflows/quality-gates.yml.
REQUIRE_ENV = "REQUIRE_REALDB"


def realdb_required() -> bool:
    return os.getenv(REQUIRE_ENV, "").strip().lower() in {"1", "true", "yes"}


def require_testcontainers() -> None:
    """Import testcontainers, or skip — unless this environment forbids skipping.

    Call at module scope, in place of the bare `importorskip`.
    """
    try:
        import testcontainers.postgres  # noqa: F401
    except ImportError as exc:
        if realdb_required():
            raise RuntimeError(
                f"{REQUIRE_ENV}=1 but testcontainers is not importable ({exc}). This suite "
                f"exists to exercise a real database; skipping it here would report a green "
                f"gate for work that never ran. Install requirements-dev.txt, or unset "
                f"{REQUIRE_ENV} if this is genuinely a machine without Docker."
            ) from exc
        pytest.skip(
            "testcontainers not installed — real-DB suite skipped. Set "
            f"{REQUIRE_ENV}=1 to make this a failure instead.",
            allow_module_level=True,
        )
