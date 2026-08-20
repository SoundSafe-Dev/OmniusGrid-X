#!/usr/bin/env python3
"""Refuse the CNPG cutover if the data has not been migrated (FS-801).

WHAT THIS STOPS. `overlays/production` includes the `cnpg-pooler` component, so applying it
repoints every database client — the backend, the four workers, the migration Job and the
backup CronJob — at the CloudNativePG cluster. The deploy already fails if the operator's
CRDs are absent. It could not detect the *other* half of the prerequisite: that the customer
data has actually been moved out of `base/timescaledb-statefulset.yaml` into the new cluster.

The failure that leaves is quiet and total. A healthy but EMPTY CNPG cluster accepts the
connection. The migration Job builds the schema in it quite happily. The application starts,
answers 200 on `/health/ready`, and shows every customer an empty product. Nothing crashes,
and no alert fires — availability is measured by probe success and 5xx rate, and both are
perfect. The old data is still in the StatefulSet, so it is recoverable, but the incident is
a total outage that every instrument reports as a healthy deploy.

WHAT IT CHECKS, in the order that matters:

  1. The CNPG cluster exists and the OPERATOR says it is healthy — not merely that a pod is
     running.
  2. If the legacy StatefulSet is gone, the cutover already happened. Pass.
  3. Otherwise count both databases. The new one must hold at least as many rows in the
     tables that cannot be reconstructed by running migrations.

WHY ROW COUNTS AND NOT A MARKER. A marker file or an annotation records that somebody
*intended* to migrate. These counts are the migration itself: if they match, the data is
there, whatever route it took — pg_dump/restore, pg_basebackup, or CNPG's import. And if a
later deploy runs against a cluster that has since lost its data (a deleted PVC, a bad
restore), this refuses that too, which a marker would not.

EXIT CODES
    0  safe to proceed
    1  refuse: the cutover would point the application at a database that is not ready

Usage:
    python3 tests/k8s/preflight_cnpg_cutover.py --namespace omniusgrid
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

#: Tables whose contents cannot be reconstructed by running migrations. Deliberately small,
#: and deliberately not telemetry: telemetry is append-only and a short gap is survivable,
#: while an empty `organizations` means every tenant has vanished.
IRREPLACEABLE = ("organizations", "users", "assets")

LEGACY_STATEFULSET = "timescaledb"
CLUSTER = "omniusgrid-db"


def _kubectl(*args: str) -> tuple[int, str]:
    result = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    return result.returncode, (result.stdout or result.stderr).strip()


def _exists(namespace: str, kind: str, name: str) -> bool:
    code, _ = _kubectl("get", kind, name, "-n", namespace, "-o", "name")
    return code == 0


def _cluster_is_healthy(namespace: str) -> tuple[bool, str]:
    code, out = _kubectl(
        "get", "cluster.postgresql.cnpg.io", CLUSTER, "-n", namespace, "-o", "json"
    )
    if code != 0:
        return False, f"cluster/{CLUSTER} not found: {out}"
    status = json.loads(out).get("status", {})
    phase = status.get("phase", "<none>")
    ready, instances = status.get("readyInstances", 0), status.get("instances", 0)
    if "healthy" not in phase.lower():
        return False, f"phase is {phase!r} ({ready}/{instances} instances ready)"
    return True, f"{phase} ({ready}/{instances} instances ready)"


def _count(namespace: str, pod: str, container: str, table: str) -> int | None:
    """Row count, or None if the table is unreadable — which for a fresh cluster means the
    schema does not exist yet, and is itself the finding."""
    code, out = _kubectl(
        "exec", "-n", namespace, pod, "-c", container, "--",
        "psql", "-U", "omniusgrid", "-d", "omniusgrid", "-tAc",
        f"SELECT count(*) FROM {table}",
    )
    if code != 0:
        return None
    try:
        return int(out.splitlines()[-1].strip())
    except (ValueError, IndexError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="omniusgrid")
    args = parser.parse_args()
    ns = args.namespace

    healthy, detail = _cluster_is_healthy(ns)
    if not healthy:
        print(f"REFUSING CUTOVER: {detail}", file=sys.stderr)
        print(
            f"  overlays/production points every database client at {CLUSTER}-pooler-rw. "
            f"Applying it now rolls the whole platform onto a cluster that is not serving.",
            file=sys.stderr,
        )
        return 1
    print(f"cnpg cluster/{CLUSTER}: {detail}")

    if not _exists(ns, "statefulset", LEGACY_STATEFULSET):
        print(
            f"legacy statefulset/{LEGACY_STATEFULSET} is gone - the cutover already "
            f"happened. Proceeding."
        )
        return 0

    print(
        f"legacy statefulset/{LEGACY_STATEFULSET} is still present; comparing row counts "
        f"before allowing the cutover."
    )

    old_pod, new_pod = f"{LEGACY_STATEFULSET}-0", f"{CLUSTER}-1"
    problems: list[str] = []
    for table in IRREPLACEABLE:
        old = _count(ns, old_pod, LEGACY_STATEFULSET, table)
        new = _count(ns, new_pod, "postgres", table)
        if old is None:
            print(f"  {table}: unreadable in the legacy database - skipping")
            continue
        if new is None:
            problems.append(
                f"{table}: {old} rows in the legacy database, table ABSENT in {CLUSTER}"
            )
            print(f"  {table}: legacy={old} cnpg=ABSENT  [MISSING]")
            continue
        verdict = "ok" if new >= old else "MISSING DATA"
        print(f"  {table}: legacy={old} cnpg={new}  [{verdict}]")
        if new < old:
            problems.append(
                f"{table}: {old} rows in the legacy database, only {new} in {CLUSTER}"
            )

    if problems:
        print("\nREFUSING CUTOVER: the data has not been migrated.", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\n  Applying overlays/production now would repoint every client at a database "
            "missing this data. NOTHING WOULD CRASH: the migration Job would build the "
            "schema, the app would answer 200, and every customer would see an empty "
            "product while the probe-based availability SLI reported perfect health.\n"
            "\n  Complete step 2 of infrastructure/k8s/database-ha/README.md first "
            "(pg_dump/restore, or CNPG's import), then re-run this deploy.",
            file=sys.stderr,
        )
        return 1

    print("\nthe data is present in the CNPG cluster - safe to cut over.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
