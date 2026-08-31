"""The connection budget is computed over every client, and CI actually runs it (FS-839).

`tests/k8s/check_connection_budget.py` measures each environment's worst-case connection
demand against what its database will accept. Two ways that check can pass while meaning
nothing, and this file closes both:

**Its population can go empty or stale.** The budget sums over `DB_CLIENTS`, a hand-kept
set of workload names. A workload that opens a session and is not in that set is counted
at zero, which is exactly the shape of the defect the check exists for — the sum looks
fine because the biggest term is missing. So the set is asserted against the code:
anything importing the shared engine must be named.

**It can be written and never wired.** A gate nobody runs is indistinguishable from one
that passes, which `test_ci_gate_count_is_accurate.py` already records this repository
getting wrong. So the workflow is asserted to invoke it.

The arithmetic itself is not re-implemented here. Two copies of a calculation are two
things to keep true, and the numbers live in the manifests where the check reads them.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CHECK = REPO / "tests/k8s/check_connection_budget.py"
APP = REPO / "backend/app"
WORKFLOWS = REPO / ".github/workflows"

#: Modules that reach the database through something other than the shared engine, with
#: why. `_realdb` fixtures and scripts are not deployed workloads.
NOT_A_DEPLOYED_CLIENT = {
    "app/db/database.py": "defines the engine; it is not a client of itself",
}


def _db_clients_register() -> set[str]:
    """`DB_CLIENTS` as the check itself defines it, read rather than restated."""
    tree = ast.parse(CHECK.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DB_CLIENTS" for t in node.targets
        ):
            return {ast.literal_eval(e) for e in node.value.elts}
    raise AssertionError("DB_CLIENTS not found in check_connection_budget.py")


def _workloads_importing_the_engine() -> set[str]:
    """Worker modules that construct sessions from the shared engine."""
    found = set()
    for path in sorted((APP / "workers").glob("*.py")):
        if path.name.startswith("_") or path.name == "health_server.py":
            continue
        source = path.read_text()
        if "AsyncSessionLocal" in source or "from app.db.database" in source:
            found.add(path.stem)
    return found


def _module_to_workload() -> dict[str, str]:
    """Which Deployment runs which worker module, read from the manifests.

    NOT a name heuristic. The first version of this test guessed that
    `app/workers/foo.py` is deployed as `foo-worker`, and reported `export_delivery` as
    uncounted — but `export-worker` runs `python -m app.workers.export_delivery`, so the
    module was covered and the test was wrong. That is rule 37's confounded detector: a
    check whose failures are about its own mapping rather than about the code.

    The manifest states the mapping outright in the container's `command`, so it is read
    rather than inferred.
    """
    mapping: dict[str, str] = {}
    for path in sorted((REPO / "infrastructure/k8s/base").glob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            if not isinstance(doc, dict) or doc.get("kind") not in {"Deployment", "Job"}:
                continue
            spec = (doc.get("spec") or {}).get("template", {}).get("spec", {})
            for container in spec.get("containers") or []:
                command = " ".join(container.get("command") or []) + " " + " ".join(
                    container.get("args") or []
                )
                match = re.search(r"app\.workers\.([a-z_]+)", command)
                if match:
                    mapping[match.group(1)] = doc["metadata"]["name"]
    return mapping


class TestThePopulationIsNotEmpty:
    def test_the_register_names_something(self):
        """Vacuity. An empty register makes every budget zero and every environment fit."""
        clients = _db_clients_register()
        assert len(clients) >= 5, (
            f"DB_CLIENTS holds {len(clients)} workloads. The budget sums over this set, so "
            f"a short one produces a small number that passes for the wrong reason."
        )

    def test_the_backend_itself_is_counted(self):
        """The largest term. The API is 20 replicas at the largest pool in the fleet."""
        assert "backend" in _db_clients_register()


class TestEveryEngineUserIsCounted:
    def test_no_worker_touches_the_engine_without_being_in_the_budget(self):
        """A worker that opens sessions and is not in DB_CLIENTS is counted at zero.

        This is the failure the budget exists to catch, occurring inside the budget: the
        sum looks healthy because its largest term is absent.
        """
        register = _db_clients_register()
        deployed_by = _module_to_workload()
        missing = []
        for module in sorted(_workloads_importing_the_engine()):
            workload = deployed_by.get(module)
            if workload is None:
                continue  # not deployed as its own workload; nothing to count
            if workload not in register:
                missing.append(f"{module} (deployed as {workload})")
        assert not missing, (
            f"these workers construct database sessions and the workload running them is "
            f"not in DB_CLIENTS: {missing}. Each is counted at ZERO connections by "
            f"check_connection_budget.py, so the budget it reports is lower than the truth "
            f"by that workload's entire replica ceiling."
        )

    def test_the_mapping_itself_found_something(self):
        """If the manifest walk returns nothing, the test above passes over an empty set
        and proves nothing — the same vacuity it is meant to prevent elsewhere."""
        mapping = _module_to_workload()
        assert len(mapping) >= 4, (
            f"only {len(mapping)} worker modules were mapped to workloads from the base "
            f"manifests. The walk is broken, and the coverage check above is vacuous."
        )


class TestTheGateActuallyRuns:
    def test_a_workflow_invokes_the_check(self):
        """A check nobody runs passes and asserts nothing."""
        invoked = [
            path.name
            for path in sorted(WORKFLOWS.glob("*.yml"))
            if "check_connection_budget.py" in path.read_text()
        ]
        assert invoked, (
            "no workflow runs tests/k8s/check_connection_budget.py. The budget is only a "
            "gate if something fails when it fails — otherwise raising a replica ceiling "
            "past max_connections merges green."
        )


class TestTheEngineIsSizedAtAll:
    def test_the_engine_passes_explicit_pool_settings(self):
        """The defect was the absence of these, not a wrong value for them."""
        source = (APP / "db/database.py").read_text()
        for setting in ("pool_size", "max_overflow", "pool_timeout", "pool_recycle"):
            assert setting in source, (
                f"`{setting}` is not passed to create_async_engine. Without it SQLAlchemy "
                f"picks its own default — which is how 15 connections per process came to "
                f"be the deployed value nobody chose."
            )

    def test_the_defaults_are_smaller_than_sqlalchemys(self):
        """SQLAlchemy defaults to 5 + 10. Ours must be a decision, not a coincidence."""
        from app.core.config import Settings

        settings = Settings()
        assert settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW < 15, (
            "the configured pool matches SQLAlchemy's own default of 15 per process, which "
            "is the number FS-839 found nobody had chosen."
        )

    def test_the_pool_timeout_is_shorter_than_a_typical_ingress_timeout(self):
        """A request that waits 30s for a connection is usually answering nobody: the
        client and the ingress have both given up, and the connection is spent on a
        response no one reads. Fail while somebody is still listening."""
        from app.core.config import Settings

        assert Settings().DB_POOL_TIMEOUT <= 15, (
            "DB_POOL_TIMEOUT is long enough that a caller times out first, so the pool "
            "spends its scarcest resource producing responses nobody receives."
        )
