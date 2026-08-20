"""Point-in-time recovery, proven rather than described (FS-802..806).

`docs/runbooks/database-backup-restore.md` said PITR was **not operational**, and every DR
runbook describing a pgBackRest restore pointed at a repository nothing wrote to. FS-799 then
found the RPO table claiming 5 minutes via "Patroni failover + WAL archiving" — a mechanism
applied by no kustomization — when the real figure was 24 hours.

The CNPG cluster now archives WAL continuously, takes weekly base backups, and (FS-800) sets
`archive_timeout: 5min`, which is the parameter that actually bounds the number. All of that
is *configuration*. This file is the part that was still missing: **evidence that a recovery
to a chosen instant actually returns the data.**

WHAT IT PROVES, and it is the property a customer cares about rather than "the restore
completed":

    live database after a mistaken DELETE  ->  1 row  ("after the mistake")
    recovered to a timestamp before it     ->  2 rows ("before", "also before")

The rows destroyed after the target come back; the write made after the target does not. A
restore that returns *a* database is not the same as a restore that returns *the* database as
it was at 14:32.

WHY IT DRIVES DOCKER DIRECTLY rather than using testcontainers like its sibling drills. PITR
requires stopping the server, replacing its data directory with a restored base backup, and
starting it again against `recovery.signal`. The testcontainers postgres image runs postgres
as PID 1, so stopping it kills the container. This starts the image with `sleep infinity` and
drives `pg_ctl`, which is also closer to what a real recovery does.

WHAT IT DOES NOT PROVE. The production path is barman-via-CNPG writing to object storage, not
`cp` to a local directory. This proves the Postgres mechanics — base backup plus WAL replay to
a target time — and that our understanding of them is correct. The S3 half is FS-809 and is
named in `database-backup-restore.md` as still outstanding rather than implied to be done.
"""

from __future__ import annotations

import subprocess
import time
import uuid

import pytest

from tests._realdb import require_docker

require_docker()  # FS-808: skips without Docker, FAILS when REQUIRE_REALDB=1

IMAGE = "timescale/timescaledb:latest-pg15"

#: The whole drill, base backup through recovery, must finish inside this. Generous on
#: purpose: a ceiling tight enough to be interesting on a laptop flakes on a shared runner,
#: and a flaky gate gets disabled — which is how the FS-810 timing was nearly lost.
DRILL_SECONDS_CEILING = 240.0


def _run(*args: str, check: bool = True) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args[:4])}… failed ({result.returncode}):\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


@pytest.fixture()
def server():
    """A Postgres with continuous archiving on, that we control with pg_ctl."""
    name = f"pitr-drill-{uuid.uuid4().hex[:8]}"

    def exec_(*args: str, user: str = "postgres", check: bool = True) -> str:
        return _run("docker", "exec", "-u", user, name, *args, check=check)

    _run("docker", "run", "-d", "--name", name, "-e", "POSTGRES_PASSWORD=pw",
         "--entrypoint", "sleep", IMAGE, "infinity")
    try:
        _run("docker", "exec", name, "sh", "-c",
             "mkdir -p /pgdata /archive /backups && chown -R postgres /pgdata /archive /backups")
        exec_("initdb", "-D", "/pgdata", "-U", "postgres")
        # Exactly what the CNPG cluster configures: WAL archived continuously, and a
        # timeout so a quiet system still ships its tail rather than waiting for 16 MB.
        exec_("sh", "-c",
              "printf '%s\\n' "
              "\"wal_level = replica\" "
              "\"archive_mode = on\" "
              "\"archive_command = 'test ! -f /archive/%f && cp %p /archive/%f'\" "
              "\"archive_timeout = 60\" >> /pgdata/postgresql.conf")
        exec_("pg_ctl", "-D", "/pgdata", "-l", "/tmp/pg.log", "start")
        for _ in range(30):
            if subprocess.run(
                ["docker", "exec", "-u", "postgres", name, "pg_isready", "-U", "postgres"],
                capture_output=True,
            ).returncode == 0:
                break
            time.sleep(1)
        else:
            raise AssertionError("postgres never became ready")
        yield exec_
    finally:
        _run("docker", "rm", "-f", name, check=False)


def _sql(exec_, statement: str, port: int = 5432) -> str:
    return exec_("psql", "-U", "postgres", "-p", str(port), "-tAc", statement)


def test_recovery_to_a_timestamp_returns_the_data_destroyed_after_it(server):
    exec_ = server
    started = time.monotonic()

    _sql(exec_, "CREATE TABLE readings (id int, note text)")
    _sql(exec_, "INSERT INTO readings VALUES (1,'before')")

    # THE BASE BACKUP. WAL alone cannot restore anything — it is a journal of changes to a
    # database that has to already exist. A repository with archiving on and no base backup
    # is a repository that can recover nothing, which is why the CNPG ScheduledBackup and
    # the archive config are a pair.
    exec_("pg_basebackup", "-U", "postgres", "-D", "/backups/base", "-Fp", "-Xs")

    _sql(exec_, "INSERT INTO readings VALUES (2,'also before')")
    time.sleep(1)
    target = _sql(exec_, "SELECT now()")
    time.sleep(1)

    # The mistake we are recovering from: a DELETE nobody meant to run, and a write after it.
    _sql(exec_, "DELETE FROM readings")
    _sql(exec_, "INSERT INTO readings VALUES (99,'after the mistake')")
    _sql(exec_, "SELECT pg_switch_wal()")

    live = _sql(exec_, "SELECT coalesce(string_agg(note, ','), '-') FROM readings")
    assert live == "after the mistake", f"fixture wrong: live table is {live!r}"

    exec_("pg_ctl", "-D", "/pgdata", "-m", "fast", "stop")

    # Restore the base backup and replay WAL up to the target instant.
    exec_("sh", "-c", "rm -rf /backups/restored && cp -r /backups/base /backups/restored")
    exec_("sh", "-c",
          f"printf '%s\\n' "
          f"\"restore_command = 'cp /archive/%f %p'\" "
          f"\"recovery_target_time = '{target}'\" "
          f"\"recovery_target_action = 'promote'\" "
          f"\"port = 5433\" "
          f"\"archive_mode = off\" >> /backups/restored/postgresql.conf")
    exec_("sh", "-c", "touch /backups/restored/recovery.signal")
    exec_("pg_ctl", "-D", "/backups/restored", "-l", "/tmp/restore.log", "start", check=False)

    # Recovery replays WAL before it accepts connections, so poll rather than sleep.
    for _ in range(60):
        probe = exec_("psql", "-U", "postgres", "-p", "5433", "-tAc", "SELECT 1", check=False)
        if probe.strip() == "1":
            break
        time.sleep(1)
    else:
        log = exec_("cat", "/tmp/restore.log", check=False)
        raise AssertionError(f"the restored instance never accepted connections:\n{log}")

    recovered = _sql(exec_, "SELECT coalesce(string_agg(note, ','), '-') FROM readings", port=5433)
    elapsed = time.monotonic() - started

    print(f"\n[FS-802] PITR drill completed in {elapsed:.1f}s")
    print(f"[FS-802]   live after the mistake : {live!r}")
    print(f"[FS-802]   recovered to {target}  : {recovered!r}")

    assert recovered == "before,also before", (
        f"recovery returned {recovered!r}. Expected the two rows that existed at the target "
        f"instant and NOT the row written after it. A restore that returns *a* database is "
        f"not a restore that returns *the* database as it was at the chosen moment — and the "
        f"second is what an RPO is a claim about."
    )
    assert elapsed < DRILL_SECONDS_CEILING, (
        f"the drill took {elapsed:.0f}s, over the {DRILL_SECONDS_CEILING:.0f}s ceiling"
    )


def test_the_cnpg_cluster_still_configures_what_pitr_needs():
    """The drill proves the mechanics. This proves the deployed cluster is still asking for
    them — archiving, a base-backup schedule, and the timeout that bounds RPO. Any one of the
    three going missing leaves a repository that recovers nothing, silently."""
    import pathlib

    import yaml

    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    documents = [
        d for d in yaml.safe_load_all(
            (repo / "infrastructure" / "k8s" / "database-ha" / "cluster.yaml").read_text()
        ) if d
    ]
    cluster = next(d for d in documents if d["kind"] == "Cluster")
    backup = cluster["spec"].get("backup", {}).get("barmanObjectStore")
    assert backup, "the CNPG cluster no longer archives to object storage"
    assert backup.get("wal"), "WAL archiving is not configured — PITR recovers nothing"
    assert backup.get("data"), "no base-backup configuration — WAL alone restores nothing"

    parameters = cluster["spec"]["postgresql"]["parameters"]
    assert parameters.get("archive_timeout"), (
        "archive_timeout is unset. Postgres archives a WAL segment when it FILLS (16 MB), so "
        "on a quiet system the tail sits unarchived for hours and the RPO is unbounded. This "
        "is the parameter the 15-minute target rests on."
    )

    assert any(d["kind"] == "ScheduledBackup" for d in documents), (
        "there is no ScheduledBackup. Continuous WAL archiving with no base backup is a "
        "repository that can recover nothing — the two are a pair."
    )
