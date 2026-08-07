"""FS-153: prove a backup can actually be restored.

Staging and production have had no backups at all — the only pgBackRest CronJob
lived in legacy-patroni/, which CI never applies, while every DR runbook
described restoring from a repository nothing was writing to. The nightly
logical backup in infrastructure/k8s/base/db-backup-cronjob.yaml closes that,
and this drill is what stops it from becoming the same kind of fiction: a
backup nobody restores is not a backup.

Round-trips the exact commands the CronJob and the runbook use — `pg_dump -Fc`
then `pg_restore` — against a migrations-built schema, and asserts the restored
database matches the source in rows, schema version, and **tenant isolation**.

That last one is FS-522, and it is the assertion the other three cannot make. A
restore that brings back every row and drops every RLS policy satisfies all of
them, and hands the business a database serving one tenant's rows to another —
during an incident, when nobody is looking at authorization. The restore
succeeds; the security property does not.

pg_dump/pg_restore run INSIDE the container via docker exec, not on the host:
the host client is frequently older than the server (pg_dump refuses to dump a
newer server), and this way the drill exercises the same binaries the
postgres:15-alpine backup image ships.
"""

from __future__ import annotations

import pytest

pytest.importorskip("testcontainers")

RESTORE_DB = "restore_drill"

# Tables whose row counts must survive the round-trip. Deliberately concrete:
# a dump that "succeeds" but restores an empty schema would otherwise pass.
CHECKED_TABLES = ("schema_migrations", "organizations", "users", "assets")


def _exec(container, *argv: str) -> str:
    """Run a command in the database container, asserting it succeeded."""
    exit_code, output = container.exec(list(argv))
    text = output.decode() if isinstance(output, (bytes, bytearray)) else str(output)
    assert exit_code == 0, f"{' '.join(argv)} failed ({exit_code}):\n{text}"
    return text


def _psql_scalar(container, database: str, sql: str) -> str:
    out = _exec(
        container,
        "psql", "-U", "omniusgrid", "-d", database, "-tAc", sql,
    )
    return out.strip().splitlines()[-1].strip() if out.strip() else ""


def test_dump_restores_into_an_empty_database(pg_container):
    container, _sync_url = pg_container

    # Snapshot the source before dumping.
    source_counts = {
        table: _psql_scalar(container, "omniusgrid_test", f"SELECT count(*) FROM {table}")
        for table in CHECKED_TABLES
    }
    # A drill against an empty database proves nothing.
    assert int(source_counts["schema_migrations"]) > 0, (
        "source schema_migrations is empty — the migration chain did not run, "
        "so this drill would pass vacuously"
    )

    # 1. Dump, exactly as the CronJob's init container does.
    _exec(
        container,
        "pg_dump", "-U", "omniusgrid", "-d", "omniusgrid_test",
        "-Fc", "--no-owner", "--no-acl", "-f", "/tmp/drill.pgc",
    )
    # The CronJob refuses to upload a dump that pg_restore cannot read; assert
    # the same property here so the two stay in step.
    _exec(container, "pg_restore", "--list", "/tmp/drill.pgc")

    # 2. Restore into a fresh database.
    _exec(container, "dropdb", "-U", "omniusgrid", "--if-exists", RESTORE_DB)
    _exec(container, "createdb", "-U", "omniusgrid", RESTORE_DB)
    # pg_restore exits non-zero on benign notices for extensions it cannot
    # recreate as a non-superuser, so tolerate a partial exit and verify by
    # comparing the data instead.
    container.exec(
        ["pg_restore", "-U", "omniusgrid", "-d", RESTORE_DB, "--no-owner",
         "--no-acl", "/tmp/drill.pgc"]
    )

    # 3. The restored database must match the source.
    mismatches = []
    for table in CHECKED_TABLES:
        restored = _psql_scalar(
            container, RESTORE_DB, f"SELECT count(*) FROM {table}"
        )
        if restored != source_counts[table]:
            mismatches.append(
                f"{table}: source={source_counts[table]} restored={restored}"
            )
    assert not mismatches, "row counts diverged after restore:\n  " + "\n  ".join(
        mismatches
    )

    # 4. Schema version must match, or the restore is not a usable recovery
    #    point for an app that checks its migration state on boot.
    source_version = _psql_scalar(
        container, "omniusgrid_test",
        "SELECT max(version) FROM schema_migrations",
    )
    restored_version = _psql_scalar(
        container, RESTORE_DB,
        "SELECT max(version) FROM schema_migrations",
    )
    assert restored_version == source_version, (
        f"schema version drift: source={source_version} restored={restored_version}"
    )

    # 5. Tenant isolation must survive the restore (FS-522).
    #
    #    Everything above compares DATA. A restore that brings back every row and drops
    #    every policy passes all four checks — and hands the business a database where one
    #    tenant reads another's rows, during an incident, at the moment nobody is looking
    #    at authorization. **The restore succeeds and the security property does not.**
    #
    #    It is not a hypothetical property of pg_dump. The CronJob dumps with `--no-acl`,
    #    which drops GRANT/REVOKE; policies are separate objects and DO survive, but that
    #    is a fact about the current flags, not a guarantee. Adding `--section=data`,
    #    restoring into a database whose roles do not exist, or a migration writing a
    #    policy that names a role the restore target lacks would each break it silently,
    #    because the restore is deliberately tolerant of partial failure two steps above.
    #
    #    Measured before it was asserted: 66 policies, 65 tables with row security and 65
    #    with FORCE, identical on both sides. FORCE is counted separately on purpose — it
    #    is what stops the owning role from bypassing the policies, and losing only that
    #    would leave `pg_policies` looking untouched.
    isolation = {
        "policies": "SELECT count(*) FROM pg_policies",
        "tables with row security": (
            "SELECT count(*) FROM pg_class WHERE relrowsecurity"
        ),
        "tables with FORCE row security": (
            "SELECT count(*) FROM pg_class WHERE relforcerowsecurity"
        ),
    }
    lost = []
    for label, sql in isolation.items():
        source = _psql_scalar(container, "omniusgrid_test", sql)
        restored = _psql_scalar(container, RESTORE_DB, sql)
        if source != restored:
            lost.append(f"{label}: source={source} restored={restored}")

    # Vacuity: a schema with no policies would satisfy the comparison above trivially,
    # and this codebase's tenant isolation is entirely row-level.
    assert int(_psql_scalar(container, "omniusgrid_test", isolation["policies"])) > 0, (
        "the source database has no RLS policies at all, so the isolation comparison "
        "below proves nothing. Either the migrations no longer create them — which is a "
        "far larger problem than this drill — or the probe is broken."
    )
    assert not lost, (
        "tenant isolation did not survive the restore:\n  "
        + "\n  ".join(lost)
        + "\n\nEvery row came back and the policies that keep one tenant out of "
        "another's data did not. A recovery like this reads as a success — the row "
        "counts match, the schema version matches, the application starts — and the "
        "restored database serves every organization's rows to every user."
    )

    _exec(container, "dropdb", "-U", "omniusgrid", "--if-exists", RESTORE_DB)
