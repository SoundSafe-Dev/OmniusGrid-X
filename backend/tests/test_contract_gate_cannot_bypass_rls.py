"""The contract gate connects as a role RLS applies to (FS-307).

WHAT WAS WRONG, AND WHY IT IS WORSE THAN AN UNTESTED CONTRACT. The schemathesis job connected
as the postgres service container's `POSTGRES_USER`, and the official image makes that role a
**superuser**. A superuser bypasses `FORCE ROW LEVEL SECURITY` outright — not "mostly", not
"unless a policy says otherwise". Every policy in the schema is simply not applied.

So ~375 operations were exercised against a database with tenant isolation switched off, and
the gate's conformance number could not have moved if every RLS policy had been dropped in the
same commit. A red gate is a task. **A green gate that cannot fail in a whole dimension is a
belief**, and this one was cited in the burn-down as evidence about the API's behaviour.

Demonstrated rather than reasoned, on a throwaway database, with `FORCE ROW LEVEL SECURITY`
enabled and a tenant policy in place:

    superuser (owner)                sees 2 rows   <- both tenants
    NOSUPERUSER NOBYPASSRLS role     sees 1 row    <- its own

WHAT THIS FILE GUARDS. Not the database — the WORKFLOW. The fix is one URL in one YAML file,
and the failure mode if somebody reverts it is silence: the suite goes green, faster, and
nothing anywhere says the isolation dimension stopped being exercised. A change that is
invisible when undone needs a test, and this is a cheaper one than it looks: reading the job's
own `DATABASE_URL` and asserting which role it names.

IT DOES NOT NEED A DATABASE. It reads YAML. That is deliberate — a guard that only runs where
postgres is available is a guard that does not run on the machine where the mistake is made.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gates.yml"

#: The role the postgres service container creates. It is a superuser, and it owns every
#: table the migration makes — either property alone defeats a FORCE policy.
OWNER_ROLE = "omniusgrid"

#: The restricted role the contract suite must use instead.
APP_ROLE = "omniusgrid_contract"


def _job(name: str) -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    jobs = workflow.get("jobs", {})
    assert name in jobs, f"the {name!r} job is gone from quality-gates.yml"
    return jobs[name]


def _steps_with_database_url(job: dict) -> list[tuple[str, str]]:
    """(step name, DATABASE_URL) for every step in the job that sets one."""
    found = []
    for step in job.get("steps", []):
        url = (step.get("env") or {}).get("DATABASE_URL")
        if url:
            found.append((step.get("name", "<unnamed>"), url))
    return found


class TestTheReaderIsNotVacuous:
    def test_the_workflow_parses(self):
        assert WORKFLOW.exists(), f"{WORKFLOW} is gone; this guard checks nothing"
        assert yaml.safe_load(WORKFLOW.read_text()).get("jobs")

    def test_the_contract_job_sets_a_database_url(self):
        urls = _steps_with_database_url(_job("api-contract"))
        assert urls, (
            "no step in api-contract sets DATABASE_URL. Either the job stopped using a "
            "database — in which case this guard is measuring nothing — or the reader broke."
        )


class TestTheSuiteRunsAsARoleRLSAppliesTo:
    def test_the_schemathesis_step_does_not_use_the_owner(self):
        offenders = [
            f"{name!r} connects as {OWNER_ROLE!r}"
            for name, url in _steps_with_database_url(_job("api-contract"))
            if "schemathesis" in name.lower() and f"{OWNER_ROLE}:" in url
        ]
        assert not offenders, (
            "the contract suite is back on the owning superuser, so FORCE ROW LEVEL "
            "SECURITY does not apply to it and its conformance number says nothing about "
            "tenant isolation: " + "; ".join(offenders)
        )

    def test_the_schemathesis_step_uses_the_restricted_role(self):
        # The other direction. Removing the URL entirely, or pointing it at a third role
        # nobody provisions, would pass the test above and break the job in a way that
        # looks like an infrastructure flake.
        urls = [
            url
            for name, url in _steps_with_database_url(_job("api-contract"))
            if "schemathesis" in name.lower()
        ]
        assert urls, "the schemathesis step no longer sets DATABASE_URL"
        assert all(f"{APP_ROLE}:" in url for url in urls), (
            f"the schemathesis step does not connect as {APP_ROLE!r}: {urls}"
        )

    def test_the_role_is_provisioned_before_it_is_used(self):
        """A URL naming a role nobody creates fails at connect, which reads as a flake."""
        steps = _job("api-contract").get("steps", [])
        names = [s.get("name", "") for s in steps]
        provision = next(
            (i for i, s in enumerate(steps) if "provision" in s.get("name", "").lower()), None
        )
        assert provision is not None, (
            f"no step provisions {APP_ROLE}; the contract step would fail at connect. "
            f"Steps: {names}"
        )
        uses = next(
            (i for i, s in enumerate(steps) if "schemathesis" in s.get("name", "").lower()),
            None,
        )
        assert uses is not None and provision < uses, (
            f"the role is provisioned at step {provision} and used at step {uses}"
        )

    def test_migrations_still_run_as_the_owner(self):
        """The restricted role has no DDL on purpose, exactly as in production. Pointing
        the migration at it would fail — and 'grant it DDL' is the fix that would quietly
        undo this whole item, since an owning role defeats FORCE RLS as surely as a
        superuser does."""
        migrate = [
            url
            for name, url in _steps_with_database_url(_job("api-contract"))
            if "migrate" in name.lower()
        ]
        assert migrate, "no migration step with a DATABASE_URL in api-contract"
        assert all(f"{OWNER_ROLE}:" in url for url in migrate), (
            f"the migration step no longer runs as {OWNER_ROLE!r}: {migrate}"
        )


class TestTheProvisioningScriptStillRefusesABypass:
    def test_it_asserts_the_role_cannot_bypass(self):
        # The script checks pg_roles after creating the role rather than trusting its own
        # DDL. If that assertion goes, a role created with the wrong attributes — by a
        # future edit, or an existing role of the same name — would be used silently.
        source = (ROOT / "backend" / "scripts" / "provision_app_role.py").read_text()
        assert "rolbypassrls" in source and "rolsuper" in source, (
            "provision_app_role.py no longer verifies the role it created is neither a "
            "superuser nor BYPASSRLS, so it can hand back a role RLS does not apply to"
        )

    def test_it_grants_no_ddl(self):
        source = (ROOT / "backend" / "scripts" / "provision_app_role.py").read_text()
        grants = re.findall(r"GRANT ([A-Z, ]+) ON", source)
        forbidden = {"CREATE", "ALL", "ALL PRIVILEGES"}
        offenders = [g for g in grants if any(f in g for f in forbidden)]
        assert not offenders, (
            f"the application role is granted {offenders}, which is more than it has in "
            f"production and moves it toward ownership — and an owner defeats FORCE RLS"
        )


@pytest.mark.parametrize("role", [OWNER_ROLE, APP_ROLE])
def test_the_two_roles_are_actually_different(role: str):
    """Guards the embarrassing version of this fix: provisioning a 'restricted' role that
    is the same name as the owner, so nothing changed and everything reports success."""
    assert OWNER_ROLE != APP_ROLE
