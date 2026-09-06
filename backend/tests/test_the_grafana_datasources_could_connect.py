"""A provisioned datasource pointing at credentials nothing creates (FS-978).

`infra/grafana/provisioning/datasources/datasources.yml` declared a TimescaleDB datasource
that could never have connected, and was wrong in three independent ways at once:

    database: opsgrid            -- compose creates `omniusgrid` (docker-compose.yml)
    user: opsgrid_readonly       -- no CREATE ROLE for it exists anywhere in the repository
    password: readonly_password  -- a committed literal, set nowhere else

Any one of the three is fatal on its own. The panel it feeds has been empty since the file
was written, and the plaintext secret in git was protecting a login that did not exist.

THE SHAPE, not the instance, is what this file guards. It is the same one as
`test_the_alert_configs_would_actually_load.py` one file over: a configuration that reads
as complete, is syntactically valid, and cannot work -- the Alertmanager that never
started, the SLI that read 1.0 through an outage, the alert keyed to a job label no scrape
produces. A YAML-shape check passes on all of them, which is why this asks a different
question: do the credentials name things that exist?

WHY NOT JUST DELETE THE DATASOURCE. `infrastructure/k8s/monitoring/grafana-datasource.yml`
did exactly that, on the reasoning that "a secret in git is a worse problem than a missing
panel" -- correct for a cluster. Compose is the local-dev stack, where the panel earns its
place, so the fix there was to make it real: the actual database, the actual user, and the
password read from the environment at provisioning load.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
DATASOURCES = ROOT / "infra" / "grafana" / "provisioning" / "datasources" / "datasources.yml"

#: Secrets must arrive by environment substitution, never as a literal. Grafana expands
#: `$VAR` in provisioning files at load.
_ENV_REF = re.compile(r"^\$[A-Z_][A-Z0-9_]*$|^\$__env\{[A-Z_][A-Z0-9_]*\}$")


def _datasources() -> list[dict]:
    return yaml.safe_load(DATASOURCES.read_text())["datasources"]


def _compose_timescale_env() -> dict:
    """POSTGRES_* the timescaledb service actually bootstraps with."""
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    env = services["timescaledb"]["environment"]
    if isinstance(env, list):  # compose accepts both shapes
        env = dict(item.split("=", 1) for item in env)
    return env


def _strip_default(value: str) -> str:
    """`${POSTGRES_PASSWORD:-omniusgrid_dev_password}` -> its default."""
    match = re.fullmatch(r"\$\{[A-Z_]+:-(.*)\}", str(value))
    return match.group(1) if match else str(value)


class TestTheDetectorSeesItsSubject:
    """Vacuity: a guard over an empty list of datasources always passes."""

    def test_datasources_are_declared(self):
        assert len(_datasources()) >= 3, (
            "fewer than three datasources parsed from the provisioning file -- the parse "
            "broke rather than the config shrinking"
        )

    def test_a_postgres_datasource_is_present(self):
        assert any(d.get("type") == "postgres" for d in _datasources()), (
            "no postgres datasource found. If it was deliberately removed (the choice "
            "grafana-datasource.yml made for k8s), delete this file too rather than "
            "leaving it passing over nothing."
        )


class TestEveryDatasourceNamesCredentialsThatExist:
    @pytest.mark.parametrize(
        "datasource",
        [d for d in _datasources() if d.get("type") == "postgres"],
        ids=lambda d: d["name"],
    )
    def test_the_database_is_one_compose_creates(self, datasource):
        expected = _strip_default(_compose_timescale_env()["POSTGRES_DB"])
        assert datasource["database"] == expected, (
            f"datasource {datasource['name']!r} queries database "
            f"{datasource['database']!r}, but compose bootstraps {expected!r}. Grafana "
            f"will authenticate and then fail every query."
        )

    @pytest.mark.parametrize(
        "datasource",
        [d for d in _datasources() if d.get("type") == "postgres"],
        ids=lambda d: d["name"],
    )
    def test_the_user_is_one_something_actually_creates(self, datasource):
        """The original `opsgrid_readonly` appeared on exactly one line in the whole
        repository: its own. A role nothing creates cannot log in."""
        compose_user = _strip_default(_compose_timescale_env()["POSTGRES_USER"])
        user = datasource["user"]
        if user == compose_user:
            return  # bootstrapped by the database image itself

        provisioning = (ROOT / "backend" / "scripts" / "provision_app_role.py").read_text()
        migrations = " ".join(
            p.read_text() for p in (ROOT / "database" / "migrations").glob("*.sql")
        )
        assert user in provisioning or user in migrations, (
            f"datasource {datasource['name']!r} logs in as {user!r}, which is neither the "
            f"compose bootstrap user ({compose_user!r}) nor created by any migration or by "
            f"scripts/provision_app_role.py. Nothing creates this role, so the datasource "
            f"cannot connect."
        )

    @pytest.mark.parametrize(
        "datasource",
        [d for d in _datasources() if d.get("secureJsonData", {}).get("password")],
        ids=lambda d: d["name"],
    )
    def test_the_password_comes_from_the_environment(self, datasource):
        password = datasource["secureJsonData"]["password"]
        assert _ENV_REF.fullmatch(password), (
            f"datasource {datasource['name']!r} carries a literal password "
            f"({password!r}) rather than a `$VAR` reference Grafana expands at load. A "
            f"committed credential is a rotation nobody can perform."
        )

    @pytest.mark.parametrize(
        "datasource",
        [d for d in _datasources() if d.get("secureJsonData", {}).get("password")],
        ids=lambda d: d["name"],
    )
    def test_the_environment_variable_reaches_the_grafana_container(self, datasource):
        """The half that makes the previous check more than cosmetic. `$POSTGRES_PASSWORD`
        expands to an empty string unless compose passes it to the Grafana service, which
        is a different service from the database that defines it."""
        var = datasource["secureJsonData"]["password"].lstrip("$").strip("{}").replace("__env", "")
        services = yaml.safe_load(COMPOSE.read_text())["services"]
        env = services["grafana"]["environment"]
        if isinstance(env, list):
            env = dict(item.split("=", 1) for item in env)
        assert var in env, (
            f"datasource {datasource['name']!r} reads ${var}, but the grafana service in "
            f"docker-compose.yml does not pass it. The substitution resolves to an empty "
            f"string and the datasource fails to connect -- the same outcome as the "
            f"committed password it replaced."
        )
