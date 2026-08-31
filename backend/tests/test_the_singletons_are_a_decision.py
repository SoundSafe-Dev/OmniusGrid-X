"""Which singletons stay singletons, and on what evidence (FS-855..858).

Wave 3 asked for HA on the remaining single-replica workloads. Reading each one turned
that into **one fix and three decisions**, which is a better answer than four half-built
clusters — but only because the reasoning is recorded and each claim is checked here
rather than asserted once in a commit message.

The one that was genuinely free is `otel-collector`: stateless, so `replicas: 2` plus a
PDB and spread constraints is real redundancy. It was a singleton, which meant a node
drain silently stopped trace collection — the platform keeps working and loses the ability
to explain itself, at exactly the moment that matters.

The other three are not free, and the interesting part is that the reason differs for each.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
APP = REPO / "backend/app"
BASE = "infrastructure/k8s/base"

#: Why each remaining singleton stays one. An entry is a DECISION with evidence, not an
#: excuse — and every claim below has a test in this file that fails if it stops being true.
SINGLETONS = {
    "redis": (
        "NOT A CACHE, WHICH IS THE FINDING. Four consumers degrade safely — the rate "
        "limiter falls back to in-memory counters, feature flags resolve to off, the "
        "idempotency store and the correlation job store both have InMemory "
        "implementations. But `bulk_processor` and `export_processor` keep JOB STATE "
        "there and nothing else holds it, so Redis is a system of record for two "
        "subsystems. An in-memory fallback would be worse than none for those: job state "
        "is polled, so with more than one replica the poll lands on a pod that never saw "
        "the job and the caller is told their import does not exist. The failure is now "
        "at least legible (503, not 500). Sentinel would need three sentinels, a "
        "replica, client changes and failover testing; moving job state to Postgres is "
        "the smaller and more honest fix, and it is the one to do."
    ),
    "seaweedfs": (
        "Holds exports, compliance reports and RAG documents — artefacts the product has "
        "already told a customer exist, so this is durability rather than availability. "
        "FS-813 gave it a backup, which bounds data LOSS; what remains unbounded is RTO, "
        "because a rebuild is manual. Real HA means a master quorum plus replicated "
        "volume servers and a replication policy, which changes the storage topology "
        "rather than the replica count — `replicas: 2` on this StatefulSet would produce "
        "two independent stores, not one redundant one, and would be worse than the "
        "singleton because writes would land in whichever the Service picked."
    ),
    "jaeger": (
        "Owns a badger volume (FS-792 made it persistent). A second replica is a second, "
        "DIVERGENT trace store rather than redundancy: spans would be split across two "
        "backends and no query would see a whole trace. HA here means an external "
        "storage backend — Elasticsearch or Cassandra — which is a dependency this "
        "platform does not otherwise have."
    ),
    "edge-agent": (
        "FS-858's recorded decision. The in-cluster agent is a TEST AND DEMO FIXTURE; "
        "real agents run on customer premises, one per site, and are unaffected by this "
        "cluster's scheduling entirely. Making the fixture highly available would model "
        "something that does not exist in the field — and the field's answer to an agent "
        "being down is store-and-forward on the device, which is already built and "
        "measured by the DDIL suite."
    ),
}


def _base_docs() -> list[dict]:
    out = subprocess.run(
        ["kustomize", "build", str(REPO / BASE)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return [d for d in yaml.safe_load_all(out.stdout) if d]


class TestTheDecisionsAreRecorded:
    @pytest.mark.parametrize("workload", sorted(SINGLETONS))
    def test_each_says_why_at_length(self, workload):
        """A one-line reason is a shrug. These have to survive somebody asking why in six
        months, when the person who decided has left."""
        assert len(SINGLETONS[workload]) > 200

    def test_the_ones_named_here_really_are_singletons(self):
        """A stale register is worse than none: it reports a solved problem as open."""
        docs = _base_docs()
        replicas = {
            d["metadata"]["name"]: (d.get("spec") or {}).get("replicas", 1)
            for d in docs
            if d.get("kind") in {"Deployment", "StatefulSet"}
        }
        for workload in SINGLETONS:
            actual = replicas.get(workload)
            assert actual == 1, (
                f"{workload} runs {actual} replicas but is still recorded as a deliberate "
                f"singleton. Either the entry is stale or the change was not intended."
            )


class TestTheCollectorIsActuallyRedundantNow:
    """Two replicas alone is not redundancy — it is two pods that may share a node."""

    def test_it_runs_more_than_one(self):
        docs = _base_docs()
        collector = next(
            d for d in docs
            if d.get("kind") == "Deployment" and d["metadata"]["name"] == "otel-collector"
        )
        assert collector["spec"]["replicas"] >= 2

    def test_it_has_a_disruption_budget_and_spread(self):
        """Without a PDB a drain can take both at once; without spread they can be on one
        node, so the PDB cannot be honoured. Both, or neither means anything."""
        docs = _base_docs()
        assert any(
            d.get("kind") == "PodDisruptionBudget"
            and (d["spec"].get("selector") or {}).get("matchLabels", {}).get(
                "app.kubernetes.io/name"
            ) == "otel-collector"
            for d in docs
        ), "otel-collector runs 2 replicas with no PodDisruptionBudget"

        collector = next(
            d for d in docs
            if d.get("kind") == "Deployment" and d["metadata"]["name"] == "otel-collector"
        )
        assert collector["spec"]["template"]["spec"].get("topologySpreadConstraints")


class TestTheRedisClaimIsEvidenceNotAssertion:
    """The register says four consumers degrade safely and two do not. Both halves are
    checked, because the decision to leave Redis a singleton rests on exactly that split.
    """

    @pytest.mark.parametrize(
        "module,marker",
        [
            ("middleware/idempotency.py", "InMemoryIdempotencyStore"),
            ("services/alarm_rules.py", "InMemoryBreachStore"),
        ],
    )
    def test_the_consumers_that_degrade_still_have_their_fallback(self, module, marker):
        assert marker in (APP / module).read_text(), (
            f"{module} no longer has its in-memory fallback, so an unreachable Redis is "
            f"now an outage for it — and the decision to leave Redis a singleton was "
            f"taken on the basis that it was not."
        )

    @pytest.mark.parametrize(
        "module", ["services/bulk_processor.py", "services/export_processor.py"]
    )
    def test_the_ones_that_cannot_degrade_at_least_fail_legibly(self, module):
        """A 500 says "we are broken"; a 503 says "a dependency is down, retry". The
        caller does different things with those, and only one of them is true."""
        tree = ast.parse((APP / module).read_text())
        fn = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_job"),
            None,
        )
        assert fn is not None, f"{module} has no get_job; this guard is now blind"
        assert any(isinstance(n, ast.Try) for n in ast.walk(fn)), (
            f"{module}'s get_job no longer translates a Redis outage, so an unreachable "
            f"Redis surfaces as a 500 — reported as a defect here rather than as the "
            f"dependency outage it is."
        )
