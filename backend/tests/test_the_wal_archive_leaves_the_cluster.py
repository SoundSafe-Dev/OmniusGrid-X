"""An archive inside the failure domain it protects is not a backup of that domain (FS-811).

`database-ha/cluster.yaml` configured continuous WAL archiving to
`http://seaweedfs:8333` — the **single-replica** object store running in the same cluster
(`base/object-store.yaml`, `replicas: 1`). The comment above it read "Continuous WAL archiving
+ base backups to S3 → point-in-time recovery. This is the PITR the pg_dump CronJob explicitly
could not provide."

Against the two RPO figures the runbooks quote:

    lost primary instance   RPO ~= 0     unaffected — a standby has confirmed every
                                          acknowledged commit and the archive is never read
    lost cluster or site    RPO <= 5min  **false.** The archive is in the cluster, so it goes
                                          with it, and the real recovery point falls back to
                                          the nightly pg_dump: 24 hours

The second is the scenario that figure was written for. And the failure is invisible until the
day it matters, because archiving works perfectly right up to the moment the cluster is gone —
FS-800 even set `archive_timeout` to bound the number this endpoint was quietly making
meaningless.

WHAT THIS ASSERTS. No environment overlay may point the archive at an in-cluster Service. The
base manifest keeps the SeaweedFS default deliberately, because kind and a laptop have nowhere
else to write and a stack that will not start teaches nobody anything — so the assertion is on
the OVERLAYS, which is what actually gets applied.

WHY A PLACEHOLDER RATHER THAN A REAL VALUE. The overlays ship
`https://REPLACE-ME…s3.example.invalid`, which fails. That is the same choice as
`alertmanager-secrets` and the placeholder-secret filter: a value that fails loudly beats one
that quietly works against the wrong store, and "the backup went somewhere" is the exact class
of quiet success this sprint keeps finding.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
PLATFORM = REPO / "infrastructure" / "k8s" / "platform"
BASE_CLUSTER = REPO / "infrastructure" / "k8s" / "database-ha" / "cluster.yaml"

ENVIRONMENTS = ("production", "staging")

#: A hostname with no dot is a Kubernetes Service in the same namespace — `seaweedfs`,
#: `minio`, `timescaledb`. A single label is the tell; anything routable off-cluster carries
#: a domain.
IN_CLUSTER = re.compile(r"^https?://[a-z0-9-]+(:\d+)?/?$", re.I)


def _built_cluster(environment: str) -> dict:
    if not shutil.which("kustomize"):
        pytest.skip("kustomize is not installed")
    result = subprocess.run(
        ["kustomize", "build", str(PLATFORM / environment / "database-ha")],
        capture_output=True, text=True, cwd=REPO,
    )
    if result.returncode != 0:
        pytest.fail(f"kustomize build {environment}/database-ha failed:\n{result.stderr}")
    for document in yaml.safe_load_all(result.stdout):
        if document and document.get("kind") == "Cluster":
            return document
    pytest.fail(f"{environment}/database-ha built no Cluster")


class TestTheMeasurementIsReal:
    def test_the_base_default_is_still_in_cluster(self):
        """The premise. If base ever stops defaulting to SeaweedFS, the overlays' whole
        reason for existing changes and this file should be re-read rather than trusted."""
        for document in yaml.safe_load_all(BASE_CLUSTER.read_text()):
            if document and document.get("kind") == "Cluster":
                endpoint = document["spec"]["backup"]["barmanObjectStore"]["endpointURL"]
                assert IN_CLUSTER.match(endpoint), (
                    f"base now points at {endpoint!r}, which is not an in-cluster Service. "
                    f"Good — but this guard's reasoning assumed otherwise."
                )
                return
        pytest.fail("no Cluster found in database-ha/cluster.yaml")

    def test_the_detector_tells_the_two_apart(self):
        assert IN_CLUSTER.match("http://seaweedfs:8333")
        assert IN_CLUSTER.match("http://minio:9000")
        assert not IN_CLUSTER.match("https://s3.us-east-1.amazonaws.com")
        assert not IN_CLUSTER.match("https://REPLACE-ME.s3.example.invalid")


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_no_environment_archives_wal_inside_its_own_cluster(environment: str):
    endpoint = _built_cluster(environment)["spec"]["backup"]["barmanObjectStore"]["endpointURL"]
    assert not IN_CLUSTER.match(endpoint), (
        f"{environment} archives WAL to {endpoint!r}, which is a Service in the same cluster.\n\n"
        f"For a lost primary that changes nothing — a standby confirmed every acknowledged "
        f"commit and the archive is never read. For a lost CLUSTER, which is the scenario the "
        f"<=5 minute RPO figure was written for, the archive is lost with it and the real "
        f"recovery point becomes the nightly pg_dump at 24 hours. Archiving keeps working "
        f"perfectly right up until the moment it is needed."
    )


@pytest.mark.parametrize("environment", ENVIRONMENTS)
def test_the_external_archive_is_encrypted_in_transit(environment: str):
    endpoint = _built_cluster(environment)["spec"]["backup"]["barmanObjectStore"]["endpointURL"]
    assert endpoint.startswith("https://"), (
        f"{environment} ships WAL to {endpoint!r} over plaintext HTTP. Acceptable to a "
        f"pod-local Service, not to anything off-cluster: every committed row travels through "
        f"the WAL stream (OG-SC-003)."
    )
