"""Refuse to start with a message, rather than crash with a stack trace (FS-446).

`docker-compose.yml` mounts `./backend:/app` over the backend image, which splits the
container in two: the **code** comes from the working tree and is always current, the
**packages** come from the image and are as old as the last build. Every dependency change
therefore breaks every container built before it, and the symptom is whichever import
happens to come first:

    File "/app/app/api/auth.py", line 10, in <module>
        import jwt
    ModuleNotFoundError: No module named 'jwt'

That was a two-month-old image, three weeks after `PyJWT` replaced `python-jose` (FS-76).
Nothing in the trace says "your image predates a dependency change; rebuild it", which is
the only thing worth knowing — so the container restart-looped and a developer following
`DEVELOPER_SETUP.md` got a backend that never answered and no idea why.

The same failure wears other clothes: a laptop venv behind `requirements.txt` after a pull,
or a CI cache that survived a dependency bump. All three are "installed packages are older
than the code", and all three are worth one line at startup instead of a stack trace.

WHY NAMES AND NOT VERSIONS. A version check would be stricter and would fire constantly for
harmless drift — a patch release, a transitive pin, a local editable install. Absence is
unambiguous and is the failure that actually happens; version skew announces itself
differently and usually louder.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path
from typing import Iterable, Optional

import structlog
from sqlalchemy import text

logger = structlog.get_logger()

REQUIREMENTS = Path(__file__).resolve().parent.parent.parent / "requirements.txt"

#: `PyJWT[crypto]==2.10.1  # comment` -> `pyjwt`. Extras, specifiers and comments are noise;
#: the distribution name is the only part `importlib.metadata` can answer for.
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?:[<>=!~;].*)?$")

#: Distributions whose import name differs from their package name and which are pulled in
#: as extras rather than named directly. Absence of these is reported by the package that
#: requires them, so checking them here would add noise without adding coverage.
_SKIP = {"pip", "setuptools", "wheel"}


def _normalise(name: str) -> str:
    """PEP 503: lowercase, and every run of `-`, `_` or `.` becomes a single `-`."""
    return re.sub(r"[-_.]+", "-", name).lower()


class MissingDependencies(RuntimeError):
    """Raised at startup when installed packages are older than the code."""


def _requirement_names(lines: Optional[Iterable[str]] = None) -> set[str]:
    """Distribution names from `requirements.txt`, lowercased and normalised."""
    if lines is None:
        if not REQUIREMENTS.exists():  # pragma: no cover - defensive
            return set()
        lines = REQUIREMENTS.read_text().splitlines()

    names: set[str] = set()
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _REQUIREMENT.match(line)
        if match:
            names.add(match.group(1).strip().lower())
    return names - _SKIP


def verify_installed_dependencies(required: Optional[set[str]] = None) -> None:
    """Raise `MissingDependencies` naming everything absent, and what to do about it.

    Every missing name at once, deliberately: a developer who rebuilds for one package and
    hits the next has learned nothing about the size of the gap.
    """
    names = required if required is not None else _requirement_names()
    if not names:  # pragma: no cover - no requirements file to check against
        return

    # PEP 503 NORMALISATION, on both sides. PyPI treats `-`, `_` and `.` as the same
    # character, and the two sources disagree in practice: `requirements.txt` says
    # `prometheus-client` while `packages_distributions()` reports `prometheus_client`.
    # Comparing raw strings reported an installed, importable package as missing — a check
    # that cries wolf on a correct environment is one people learn to skip, which would have
    # made it worse than the crashloop it replaces.
    mapping = metadata.packages_distributions()
    present = {_normalise(name) for name in mapping}
    present |= {_normalise(dist) for dists in mapping.values() for dist in dists}

    missing = sorted(name for name in names if _normalise(name) not in present)
    if not missing:
        return

    raise MissingDependencies(
        f"{len(missing)} package(s) named in requirements.txt are not installed: "
        f"{', '.join(missing)}.\n"
        f"\n"
        f"The most likely cause is a stale image: docker-compose mounts ./backend over /app, "
        f"so the CODE is current while the PACKAGES are as old as the last build. Rebuild "
        f"with `docker compose build backend`.\n"
        f"\n"
        f"Outside a container, the same message means this environment is behind "
        f"requirements.txt — `pip install -r requirements.txt`."
    )


class TenantIsolationRestsOnNothing(RuntimeError):
    """Raised at startup when the app's own database role can bypass RLS.

    Postgres documents this plainly and this repository has already been bitten by a
    milder version of it once (docs/engineering/api-contract-gate.md): a superuser or a
    BYPASSRLS role sees every row regardless of policy, FORCE or not. Every tenant
    boundary this codebase enforces at the database layer — every `CREATE POLICY`, every
    `FORCE ROW LEVEL SECURITY`, the guard in `test_every_tenant_table_has_a_policy.py` —
    is decorative the moment the connection the app actually uses can ignore it, and
    nothing before this printed that in the one place an operator would see it before
    traffic arrived.
    """


async def verify_rls_is_not_bypassed(engine) -> None:
    """Refuse to start if the app's own role can bypass row-level security (FS-912).

    Takes the ENGINE rather than an open connection so this is one mockable call at
    the lifespan call site — a connection-taking version would need `engine.connect()`
    to succeed before this function is ever reached, which made it untestable in
    `test_ota_worker_topology.py` without a real database (that file only tests
    startup/shutdown ORDERING, and mocks `init_db` for the same reason).

    SQLite (the whole unit-test suite) has no roles or RLS at all and is skipped --
    this is a Postgres-specific guarantee, checked against whatever the app is actually
    connecting as. `tests/conftest.py` already provisions a `NOSUPERUSER NOBYPASSRLS`
    role for the real-DB suite for the same reason this check exists: "superusers bypass
    RLS even with FORCE" is Postgres's own documentation, not a hypothetical.
    """
    async with engine.connect() as conn:
        if conn.dialect.name != "postgresql":
            return

        result = await conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
        row = result.one()
        is_superuser, bypasses_rls = row[0], row[1]
        if is_superuser or bypasses_rls:
            raise TenantIsolationRestsOnNothing(
                f"the database role this application connects as "
                f"(rolsuper={is_superuser}, rolbypassrls={bypasses_rls}) can see every "
                f"tenant's rows regardless of row-level security policy. Every "
                f"`CREATE POLICY` and `FORCE ROW LEVEL SECURITY` in this schema is "
                f"decorative under this connection, and the tenant model rests on "
                f"application-level scoping alone. Provision a NOSUPERUSER NOBYPASSRLS "
                f"role for DATABASE_URL and grant it exactly the privileges "
                f"scripts/provision_app_role.py declares."
            )
        logger.info(
            "rls_bypass_check_passed",
            rolsuper=is_superuser,
            rolbypassrls=bypasses_rls,
        )
