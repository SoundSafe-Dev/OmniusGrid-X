"""The pooler cutover is three facts that must agree, in three different files (FS-801).

`database-ha/README.md` described repointing `DATABASE_URL` at the PgBouncer pooler as a
MANUAL step. A manual step in a runbook is a step that gets skipped, and this one fails
silently in the worst possible direction: the HA cluster runs, WAL archiving works
perfectly, and it faithfully archives a database nothing is writing to. Every dashboard is
green and the RPO the archive buys applies to the wrong data.

Making it a kustomize component fixes that and creates a new way to be wrong, because the
cutover is now three facts in three files and any one of them can move alone:

  1. `overlays/production` includes the `cnpg-pooler` component;
  2. every database client in the built output resolves to the pooler — no duplicates, no
     leftover `database-credentials` reference, no phantom container;
  3. the production deploy applies `database-ha` FIRST, and refuses outright if the
     CloudNativePG CRDs are absent;
  4. it then runs the DATA preflight, which refuses if the customer data was never moved
     out of the legacy StatefulSet.

Break (3) and the next production deploy points every pod at a Service that does not
exist. Break (2) and the cutover looks wired and changes nothing.

Break (4) and the failure is the quietest of the four: a healthy but EMPTY CNPG cluster
accepts the connection, the migration Job builds the schema in it, the application answers
200, and every customer sees an empty product — while the probe-based availability SLI
reports perfect health, because the system genuinely is up. Nothing crashes; no alert fires.
The CRD check cannot see this, because the operator being installed says nothing about
whether anyone ran `pg_dump`.

THE SECOND ONE IS NOT HYPOTHETICAL. The component's first draft used one shared patch
naming `PLACEHOLDER` as the container, on the assumption that the patch *target* supplies
the name. It does not: kustomize merges containers by name, found no `PLACEHOLDER`, and
ADDED a second image-less container to all seven workloads while each real container went
on using the old secret. `kustomize build` exited 0. `kubeconform` was satisfied. Only
reading the built output caught it — rule 273 one layer up, where building is not
deploying.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
K8S = REPO / "infrastructure" / "k8s"
COMPONENT = K8S / "components" / "cnpg-pooler"
WORKFLOW = REPO / ".github" / "workflows" / "ci-cd.yml"

POOLER_HOST = "omniusgrid-db-pooler-rw"
#: Overlays that must NOT be cut over — staging and DR still run base's StatefulSet.
NOT_CUT_OVER = ("base", "overlays/staging", "overlays/dr")


def _kustomize(path: str) -> list[dict]:
    result = subprocess.run(
        ["kustomize", "build", str(K8S / path)],
        capture_output=True, text=True, cwd=REPO,
    )
    if result.returncode != 0:
        pytest.fail(f"kustomize build {path} failed:\n{result.stderr}")
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def _pod_specs(docs: list[dict]):
    """(kind, name, container) for every pod template in the build."""
    for doc in docs:
        kind = doc.get("kind")
        if kind == "CronJob":
            template = doc["spec"]["jobTemplate"]["spec"]["template"]
        elif kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
            template = doc["spec"].get("template")
        else:
            continue
        if not template:
            continue
        for container in template["spec"].get("containers", []):
            yield kind, doc["metadata"]["name"], container


@pytest.fixture(scope="module")
def production() -> list[dict]:
    if not shutil_which("kustomize"):
        pytest.skip("kustomize is not installed")
    return _kustomize("overlays/production")


def shutil_which(name: str):
    import shutil

    return shutil.which(name)


class TestTheMeasurementIsReal:
    def test_the_component_exists_and_patches_every_client(self):
        kustomization = yaml.safe_load((COMPONENT / "kustomization.yaml").read_text())
        patches = kustomization.get("patches") or []
        assert len(patches) == 7, (
            f"the component patches {len(patches)} workloads; seven read "
            f"database-credentials/url (backend, four workers, the migration Job and the "
            f"backup CronJob). A client left behind talks to the old database."
        )
        for patch in patches:
            assert patch.get("target", {}).get("namespace") == "omniusgrid", (
                f"{patch} has no namespace in its target. Base resources carry "
                f"`namespace: omniusgrid`, and under kustomize v5 a patch whose target "
                f"omits it matches nothing — the build fails with '[noNs]'."
            )

    def test_no_patch_names_a_placeholder_container(self):
        """The exact defect the first draft shipped, pinned by name."""
        for path in COMPONENT.glob("*.yaml"):
            if path.name == "kustomization.yaml":
                continue
            document = yaml.safe_load(path.read_text())
            template = (
                document["spec"]["jobTemplate"]["spec"]["template"]
                if document["kind"] == "CronJob"
                else document["spec"]["template"]
            )
            for container in template["spec"]["containers"]:
                assert container["name"] != "PLACEHOLDER", (
                    f"{path.name} names its container PLACEHOLDER. kustomize merges "
                    f"containers by name; it will ADD a second, image-less container and "
                    f"leave the real one pointing at the old secret, while the build "
                    f"exits 0."
                )


def test_production_is_cut_over_and_nothing_else_is(production):
    on_pooler = [
        f"{kind}/{name}/{c['name']}"
        for kind, name, c in _pod_specs(production)
        for e in c.get("env", [])
        if e["name"] == "DATABASE_URL" and POOLER_HOST in (e.get("value") or "")
    ]
    assert len(on_pooler) == 7, f"expected 7 clients on the pooler, got {on_pooler}"

    for overlay in NOT_CUT_OVER:
        docs = _kustomize(overlay)
        stragglers = [
            f"{kind}/{name}"
            for kind, name, c in _pod_specs(docs)
            for e in c.get("env", [])
            if e["name"] == "DATABASE_URL" and POOLER_HOST in (e.get("value") or "")
        ]
        assert not stragglers, (
            f"{overlay} points {stragglers} at the CNPG pooler. Only production is cut "
            f"over; {overlay} still runs base's single-replica StatefulSet, and a pooler "
            f"Service does not exist there."
        )


def test_no_client_keeps_a_second_database_url(production):
    """A duplicate env entry is not a build error — Kubernetes takes the last one. So a
    patch that APPENDS instead of replacing produces a manifest that looks cut over and
    connects to whichever database happens to sort last."""
    offenders = []
    for kind, name, container in _pod_specs(production):
        entries = [e for e in container.get("env", []) if e["name"] == "DATABASE_URL"]
        if len(entries) > 1:
            offenders.append(f"{kind}/{name}/{container['name']}: {len(entries)} entries")
        for entry in entries:
            if "value" in entry and "valueFrom" in entry:
                offenders.append(f"{kind}/{name}: DATABASE_URL has both value and valueFrom")
    assert not offenders, offenders


def test_no_phantom_container_reached_the_build(production):
    phantoms = [
        f"{kind}/{name}"
        for kind, name, c in _pod_specs(production)
        if c["name"] == "PLACEHOLDER" or "image" not in c
    ]
    assert not phantoms, (
        f"{phantoms} have a container with no image. That is what a strategic-merge patch "
        f"produces when it names a container that does not exist — it adds one."
    )


def test_the_production_deploy_applies_the_cnpg_stack_first():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["deploy-production"]["steps"]
    deploy = next(s for s in steps if s.get("name") == "Deploy to production")
    script = deploy["run"]

    assert "platform/production/database-ha" in script, (
        "the production deploy does not apply the CloudNativePG stack, but the production "
        "overlay includes the cnpg-pooler component. Every workload would be rolled out "
        "pointing at omniusgrid-db-pooler-rw, a Service nothing created."
    )
    assert script.index("database-ha") < script.index("prod-manifests.yaml"), (
        "database-ha is applied AFTER the application manifests. The pooler Service must "
        "exist before the pods that name it."
    )
    assert "exit 1" in script, (
        "the deploy does not fail when the CloudNativePG CRDs are absent. Rolling out "
        "against a missing pooler CrashLoopBackOffs the entire platform, which is a worse "
        "and far less legible outcome than a refused deploy."
    )


def test_the_production_deploy_checks_the_data_moved():
    """The CRD check proves the OPERATOR exists. It says nothing about whether the customer
    data was ever migrated — and an empty cluster fails silently rather than loudly."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["deploy-production"]["steps"]
    script = next(s for s in steps if s.get("name") == "Deploy to production")["run"]

    assert "preflight_cnpg_cutover.py" in script, (
        "the production deploy does not run the data preflight. The CRD check above it "
        "only proves the operator is installed; an empty CNPG cluster passes that and then "
        "serves every customer an empty product with the SLI reporting perfect health."
    )
    assert script.index("database-ha") < script.index("preflight_cnpg_cutover") < script.index(
        "prod-manifests.yaml"
    ), (
        "the preflight must run AFTER database-ha is applied (so the cluster exists to be "
        "inspected) and BEFORE the application manifests are built and applied (so it can "
        "still stop the deploy)."
    )
    assert (REPO / "tests" / "k8s" / "preflight_cnpg_cutover.py").exists(), (
        "the deploy calls tests/k8s/preflight_cnpg_cutover.py and the file is missing — the "
        "step would fail at run time, on the deploy, which is the worst place to find out."
    )
