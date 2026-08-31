#!/usr/bin/env python3
"""Every replica every autoscaler allows, times its pool, fits the database (FS-839).

THE DEFECT. `app/db/database.py` created the engine with no `pool_size`, no
`max_overflow` and no `pool_timeout`, so every process ran SQLAlchemy's QueuePool
defaults — 5 + 10, **15 connections per process**. Nothing set `max_connections` on the
base StatefulSet either, so that was PostgreSQL's default of 100. Both numbers were
chosen by upstream projects; neither was chosen against this deployment.

The declared ceilings are not small. The backend HPA allows 20 replicas and KEDA allows
12 + 8 + 6 workers, which at 15 each is **675 connections asked of 100**.

WHY IT HAD NOT BLOWN UP. Production applies the CNPG pooler component (FS-801), and
PgBouncer in transaction mode multiplexes — so the arithmetic that matters there is
different, and it passes. **Staging applies the same KEDA ceilings with no pooler.** That
is the environment the sum lands in, and it is also the environment nobody load-tests,
so the first place it would have surfaced is production the day someone added the pooler
to the wrong overlay, or staging the day a topic backed up.

The failure mode is worth stating because it is not gradual: past `max_connections`
PostgreSQL refuses the NEXT connection from anybody. The backend and every worker fail
together, and they fail during the load spike that caused the scale-out that exhausted
the pool.

WHAT THIS CHECKS. Per environment, the worst case the manifests permit:

    sum over workloads of (max replicas x per-process pool ceiling)

against what that environment's database will accept. "Max replicas" is the autoscaler's
ceiling where one exists and the manifest's `replicas` otherwise — a workload's real
ceiling is not always in its own file, which is the same split `check_replica_floors.py`
was written for. "Per-process pool" is `DB_POOL_SIZE + DB_MAX_OVERFLOW` from the
container's env, falling back to the defaults in `app/core/config.py` so an unset pool is
counted at what it will actually use rather than at zero.

WHERE THE POOLER IS IN THE PATH the comparison changes rather than disappearing: client
connections terminate at PgBouncer, so they are measured against `max_client_conn`, and
what reaches PostgreSQL is `default_pool_size x instances`, measured against the
cluster's `max_connections`. Both halves are checked; a pooler that multiplexes 1000
clients into more server connections than the cluster allows has simply moved the
exhaustion one hop.

Usage:  ./check_connection_budget.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "backend/app/core/config.py"

#: (overlay, autoscaling stack or None, human name). The overlay is what deploys the
#: workloads; the stack is where their real ceilings live.
ENVIRONMENTS = [
    ("infrastructure/k8s/overlays/production",
     "infrastructure/k8s/platform/production/autoscaling",
     "infrastructure/k8s/platform/production/database-ha", "production"),
    ("infrastructure/k8s/overlays/staging",
     "infrastructure/k8s/platform/staging/autoscaling",
     "infrastructure/k8s/platform/staging/database-ha", "staging"),
    ("infrastructure/k8s/overlays/dr", None, None, "dr"),
]

#: How a workload says it is pooled. The `Pooler` object lives in the database-ha stack,
#: deployed on its own lifecycle by a different job, so an overlay cannot be asked whether
#: a pooler exists. What the overlay CAN say is where it points: the cnpg-pooler component
#: (FS-801) rewrites DATABASE_URL to the pooler service, and a workload is pooled exactly
#: when its own URL says so. Reading the deployed topology from the client's configuration
#: is the honest direction — a Pooler that exists but nothing points at is not in the path.
POOLER_HOST = "-pooler-"

#: Workloads that talk to PostgreSQL through SQLAlchemy. A workload absent here is not
#: counted, so the list is the thing to keep true — `test_the_connection_budget_counts_every_client`
#: asserts it against the manifests rather than trusting this comment.
DB_CLIENTS = {
    "backend",
    "ingestion-worker",
    "export-worker",
    "compliance-reports-worker",
    "ota-rollout-worker",
    "rag-indexing-worker",
    "db-migrate",
}


def _build(path: str, permissive: bool = False) -> list[dict]:
    cmd = ["kustomize", "build"]
    if permissive:
        cmd += ["--load-restrictor", "LoadRestrictionsNone"]
    cmd.append(str(REPO_ROOT / path))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"kustomize build failed for {path}:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _config_default(name: str, fallback: int) -> int:
    """The default from `config.py`, so this file cannot drift from the code it measures."""
    match = re.search(rf"^    {name}: int = (\d+)", CONFIG.read_text(), re.M)
    return int(match.group(1)) if match else fallback


def _strip_prefix(name: str) -> str:
    for prefix in ("prod-", "staging-", "dr-"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _pod_spec(doc: dict) -> dict:
    """Pod spec for a Deployment/StatefulSet/CronJob/Job alike."""
    spec = doc.get("spec") or {}
    template = spec.get("template")
    if template is None:
        template = ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template")
    return ((template or {}).get("spec")) or {}


def _pool_ceiling(doc: dict, default_pool: int, default_overflow: int) -> int:
    """`DB_POOL_SIZE + DB_MAX_OVERFLOW` for a workload, defaults included.

    An unset pool is the DANGEROUS case, not the neutral one — it is what the defect was —
    so it counts at the configured default rather than at zero.
    """
    total = 0
    for container in _pod_spec(doc).get("containers") or []:
        env = {e["name"]: e.get("value") for e in (container.get("env") or [])}
        size = int(env.get("DB_POOL_SIZE") or default_pool)
        overflow = int(env.get("DB_MAX_OVERFLOW") or default_overflow)
        total += size + overflow
    return total


def _ceilings(docs: list[dict], scaled: list[dict]) -> dict[str, int]:
    """Max replicas per base workload name: autoscaler ceiling if any, else the manifest."""
    ceilings: dict[str, int] = {}
    for doc in docs:
        if doc.get("kind") in {"Deployment", "StatefulSet"}:
            ceilings[_strip_prefix(doc["metadata"]["name"])] = (doc.get("spec") or {}).get(
                "replicas", 1
            )
        elif doc.get("kind") in {"Job", "CronJob"}:
            ceilings[_strip_prefix(doc["metadata"]["name"])] = 1

    for doc in scaled:
        kind = doc.get("kind")
        spec = doc.get("spec") or {}
        if kind == "ScaledObject":
            target = _strip_prefix((spec.get("scaleTargetRef") or {}).get("name", ""))
            ceilings[target] = max(ceilings.get(target, 0), spec.get("maxReplicaCount", 1))
        elif kind == "HorizontalPodAutoscaler":
            target = _strip_prefix((spec.get("scaleTargetRef") or {}).get("name", ""))
            ceilings[target] = max(ceilings.get(target, 0), spec.get("maxReplicas", 1))
    return ceilings


def _max_connections(docs: list[dict]) -> int | None:
    """`max_connections` of the in-overlay TimescaleDB, or None if it is left implicit."""
    for doc in docs:
        if doc.get("kind") == "StatefulSet" and "timescaledb" in doc["metadata"]["name"]:
            for container in _pod_spec(doc).get("containers") or []:
                match = re.search(r"max_connections=(\d+)", " ".join(container.get("args") or []))
                if match:
                    return int(match.group(1))
    return None


def _is_pooled(docs: list[dict]) -> bool:
    """Does any database client actually point at a pooler?"""
    for doc in docs:
        if doc.get("kind") not in {"Deployment", "StatefulSet", "Job", "CronJob"}:
            continue
        if _strip_prefix(doc["metadata"]["name"]) not in DB_CLIENTS:
            continue
        for container in _pod_spec(doc).get("containers") or []:
            for env in container.get("env") or []:
                if env.get("name") == "DATABASE_URL" and POOLER_HOST in (env.get("value") or ""):
                    return True
    return False


def _pooler_limits(stack: str | None) -> tuple[int, int, int] | None:
    """(max_client_conn, server connections the pooler opens, cluster max_connections)."""
    if stack is None:
        return None
    docs = _build(stack, permissive=True)
    pooler = next((d for d in docs if d.get("kind") == "Pooler"), None)
    cluster = next((d for d in docs if d.get("kind") == "Cluster"), None)
    if pooler is None or cluster is None:
        return None
    params = ((pooler.get("spec") or {}).get("pgbouncer") or {}).get("parameters", {})
    instances = int((pooler.get("spec") or {}).get("instances", 1))
    cluster_max = int(
        ((cluster.get("spec") or {}).get("postgresql") or {}).get("parameters", {}).get(
            "max_connections", 0
        )
    )
    return (
        int(params.get("max_client_conn", 0)),
        int(params.get("default_pool_size", 0)) * instances,
        cluster_max,
    )


def main() -> int:
    default_pool = _config_default("DB_POOL_SIZE", 5)
    default_overflow = _config_default("DB_MAX_OVERFLOW", 5)
    problems: list[str] = []
    reported = 0

    for overlay, autoscaling, ha_stack, label in ENVIRONMENTS:
        docs = _build(overlay)
        scaled = _build(autoscaling, permissive=True) if autoscaling else []
        scaled += [d for d in docs if d.get("kind") == "HorizontalPodAutoscaler"]

        ceilings = _ceilings(docs, scaled)

        demand = 0
        lines = []
        for doc in docs:
            if doc.get("kind") not in {"Deployment", "StatefulSet", "Job", "CronJob"}:
                continue
            name = _strip_prefix(doc["metadata"]["name"])
            if name not in DB_CLIENTS:
                continue
            replicas = ceilings.get(name, 1)
            pool = _pool_ceiling(doc, default_pool, default_overflow)
            demand += replicas * pool
            lines.append(f"      {name:<28} {replicas:>3} x {pool:>2} = {replicas * pool:>4}")

        if not lines:
            problems.append(
                f"{label}: no database clients found. The traversal is broken — DB_CLIENTS "
                f"names {len(DB_CLIENTS)} workloads and this overlay rendered none of them — "
                f"and a budget computed over nothing passes forever."
            )
            continue

        reported += 1
        detail = "\n".join(lines)

        if _is_pooled(docs):
            limits = _pooler_limits(ha_stack)
            if limits is None:
                problems.append(
                    f"{label}: its workloads point at a pooler ({POOLER_HOST}) but the "
                    f"database-ha stack defines no Pooler and Cluster to size them against. "
                    f"The clients believe they are pooled and nothing here can say by what."
                )
                continue
            client_cap, server_conns, cluster_max = limits
            print(f"  {label:<11} {demand:>4} client conns -> pooler cap {client_cap}; "
                  f"pooler opens {server_conns} -> cluster max_connections {cluster_max}")
            if demand > client_cap:
                problems.append(
                    f"{label}: workloads may open {demand} connections against a pooler "
                    f"accepting {client_cap}.\n{detail}"
                )
            if server_conns > cluster_max:
                problems.append(
                    f"{label}: the pooler opens up to {server_conns} server connections "
                    f"against a cluster allowing {cluster_max}. Multiplexing moved the "
                    f"ceiling one hop; it did not remove it."
                )
        else:
            max_connections = _max_connections(docs)
            if max_connections is None:
                problems.append(
                    f"{label}: nothing sets `max_connections`, so the limit is PostgreSQL's "
                    f"default of 100 by accident rather than by decision — and these "
                    f"workloads may open {demand}.\n{detail}"
                )
                continue
            print(f"  {label:<11} {demand:>4} connections -> max_connections {max_connections}")
            if demand > max_connections:
                problems.append(
                    f"{label}: workloads may open {demand} connections against "
                    f"max_connections={max_connections}. Past the limit PostgreSQL refuses "
                    f"the next connection from ANYBODY, so the backend and every worker fail "
                    f"together, during the load that caused the scale-out.\n{detail}"
                )

    if reported == 0:
        print("FAIL: no environment produced a budget — the walk is broken", file=sys.stderr)
        return 1

    if problems:
        print("\nFAIL: the connection budget does not fit:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        return 1

    print(f"OK: {reported} environments fit their database's connection limit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
