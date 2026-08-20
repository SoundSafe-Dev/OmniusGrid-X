""""Roll back to what was running" needs there to be an answer (FS-821).

`base/` ran the **database engine** on `timescale/timescaledb:latest-pg15` and the **broker**
on `redpandadata/redpanda:latest`. Both tags are repointed by their publishers whenever a
release is cut, so two clusters built a week apart ran different builds of the two components
every byte of customer data passes through — and during an incident, "which version is this"
and "roll back to the previous one" had no answer at all.

The backup image was the sharpest of the three. `postgres:15-alpine` floats across every 15.x
patch, so the `pg_dump` writing the archive could change minor version between runs, and a
dump written by a newer `pg_dump` than the `pg_restore` used to read it is a restore that
fails **during the recovery it exists for**.

AND ONE COMPONENT WAS NEVER PINNED AT ALL. `build-images` builds and pushes backend, frontend
AND edge-agent; `base/kustomization.yaml` deploys the edge-agent StatefulSet; but both deploy
jobs repointed only backend and frontend. The agent that receives OTA bundles and talks to
industrial equipment ran `omniusgrid/edge-agent:latest` — whatever was pushed last, with no
correlation to the release tag.

WHAT COUNTS AS PINNED. A `@sha256:` digest. A version tag is documentation, not a guarantee:
publishers move tags, and the only immutable reference a registry offers is the digest. The
tag is kept alongside for readability precisely because a bare digest tells a reader nothing.

AND THE OTHER HALF OF THE SUPPLY CHAIN. The first version of this file checked Kubernetes
manifests only — which image RUNS — and said nothing about the Dockerfiles, which decide what
is IN it. Every `FROM` in the repository was unpinned, and three named their image with **no
tag at all**, resolving to `:latest`. So two builds of the same release could sit on different
base images and "rebuild last month's release" was not a thing that could be done.

Measured against the backend base with trivy on 2026-08-20: **6,139 vulnerabilities, 0
CRITICAL, 193 HIGH of which 102 had a published fix.** That figure is why the image gate in
`ci-cd.yml` blocks on CRITICAL rather than HIGH — at HIGH it would fail on its first run, on
findings whose only remedy is a Red Hat base-image bump we do not control the cadence of.

Pinning a base image trades floating-and-unreproducible for frozen-and-stale, so the pin comes
with `tests/k8s/check_base_images_are_current.py`, run nightly: it compares each pinned digest
against what its tag resolves to today and reports the drift. A pin without a bump process is
the second problem wearing the first one's clothes.

WHAT IS EXEMPT, and why each is a decision rather than an oversight — see `DEPLOY_PINNED`,
`UNRESOLVABLE`, `NOT_DEPLOYED` and `OTHER_LANE_DOCKERFILES` below.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
K8S = REPO / "infrastructure" / "k8s"
WORKFLOW = REPO / ".github" / "workflows" / "ci-cd.yml"

#: Our own images. `base/` carries `:latest` as a placeholder and every deploy job repoints
#: it with `kustomize edit set image` to the exact tag that build pushed. The entry is only
#: honest while that is true, so `test_every_deploy_pinned_image_is_actually_pinned` checks it.
DEPLOY_PINNED = {
    "omniusgrid/backend",
    "omniusgrid/frontend",
    "omniusgrid/edge-agent",
}

#: Images that cannot be digest-pinned yet, each with the reason. An entry is a statement
#: that "roll back to what was running" has no answer for this workload, so the list must
#: stay short and each line must say what would close it.
UNRESOLVABLE = {
    "ghcr.io/omniusgrid/cnpg-timescaledb": (
        "OUR OWN image, and it is not published yet — the registry returns 401, so there is "
        "no digest to pin to. CNPG needs a PostgreSQL 15 image with timescaledb built in and "
        "preloaded, which the stock CloudNativePG image does not provide. cluster.yaml's own "
        "comment already says 'pin a digest in production'. Closing this means building and "
        "publishing that image, then pinning it here — and the CNPG stack is applied in no "
        "environment today, so nothing is currently running on the floating tag."
    ),
}

#: Dockerfiles belonging to another lane. Registered rather than edited, per the lane rule —
#: and named here so the exemption is visible rather than achieved by the sweep not looking.
OTHER_LANE_DOCKERFILES = {
    "rag-inference/Dockerfile": (
        "MLOps lane (HARSH). Still `FROM python:3.10-slim`, unpinned and a Python version "
        "behind the rest of the platform. Already registered by "
        "test_the_fips_claim_is_not_just_a_base_image.py, which records it as outside the "
        "CUI path today. Pinning it is that lane's call, not this one's."
    ),
}

#: Trees no kustomization builds. `legacy-patroni/` is superseded by database-ha and applied
#: nowhere — the repository keeps it rather than deleting it because the DR runbooks still
#: reference it, and deleting it would make those references dangle.
NOT_DEPLOYED = ("legacy-patroni",)

MUTABLE = re.compile(r":(latest|stable|main|master|edge)$|^[^:]+$|:[^@]*latest")


def _image_references() -> list[tuple[str, str]]:
    """(file, image) for every container image in a deployed manifest."""
    found = []
    for path in sorted(K8S.rglob("*.yaml")) + sorted(K8S.rglob("*.yml")):
        if any(part in path.parts for part in NOT_DEPLOYED):
            continue
        try:
            documents = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError:
            continue
        for document in documents:
            if not isinstance(document, dict):
                continue
            for image in _images_in(document):
                found.append((str(path.relative_to(REPO)), image))
    return found


def _images_in(node) -> list[str]:
    """Every `image:` value at any depth — Deployments, StatefulSets, DaemonSets, CronJobs,
    Jobs, and the CNPG Cluster's own top-level `imageName`."""
    out = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"image", "imageName"} and isinstance(value, str):
                out.append(value)
            else:
                out.extend(_images_in(value))
    elif isinstance(node, list):
        for item in node:
            out.extend(_images_in(item))
    return out


def _dockerfile_bases() -> list[tuple[str, str]]:
    """(dockerfile, image reference) for every FROM in the repository."""
    found = []
    for path in sorted(REPO.rglob("Dockerfile*")):
        if any(part in path.parts for part in ("node_modules", "venv", ".git")):
            continue
        relative = str(path.relative_to(REPO))
        for line in path.read_text().splitlines():
            match = re.match(r"^FROM\s+(\S+)", line)
            if match:
                found.append((relative, match.group(1)))
    return found


def _repo_of(image: str) -> str:
    return image.split("@")[0].rsplit(":", 1)[0] if ":" in image.split("@")[0] else image.split("@")[0]


@pytest.mark.parametrize("image", sorted(UNRESOLVABLE))
def test_every_unresolvable_image_says_why(image: str):
    """An exemption without a reason is an exemption nobody will ever revisit."""
    reason = UNRESOLVABLE[image]
    assert len(reason) > 80, f"{image} is exempted without a real explanation"


class TestTheMeasurementIsReal:
    def test_it_found_the_dockerfile_bases(self):
        bases = _dockerfile_bases()
        assert len(bases) >= 6, f"only {len(bases)} FROM lines parsed: {bases}"
        assert any("backend/Dockerfile" == p for p, _i in bases)

    def test_it_found_the_images(self):
        images = _image_references()
        assert len(images) >= 15, f"only {len(images)} image references parsed"
        assert any("timescaledb" in i for _f, i in images), "the database image is not visible"
        assert any("redpanda" in i for _f, i in images), "the broker image is not visible"

    def test_it_recognises_a_digest_as_pinned(self):
        assert not MUTABLE.search("postgres:15-alpine@sha256:" + "a" * 64)

    def test_it_recognises_the_shapes_that_are_not(self):
        for bad in ("redis:latest", "timescale/timescaledb:latest-pg15", "nginx"):
            assert MUTABLE.search(bad), bad


def test_no_deployed_workload_runs_a_mutable_tag():
    offenders = []
    for path, image in _image_references():
        if _repo_of(image) in DEPLOY_PINNED or _repo_of(image) in UNRESOLVABLE:
            continue
        if "@sha256:" in image:
            continue
        offenders.append(f"{path}: {image}")
    assert not offenders, (
        "these deployed images are not pinned to a digest:\n  " + "\n  ".join(sorted(offenders))
        + "\n\nA tag is repointed by its publisher whenever they cut a release, so 'roll back "
        "to what was running' has no answer. Resolve the digest and write "
        "`image:tag@sha256:...` — the tag stays for readability, the digest is what "
        "Kubernetes enforces."
    )


def test_every_dockerfile_base_is_pinned_to_a_digest():
    """The half this file originally missed. A manifest pin says which image runs; a
    Dockerfile pin says what is inside it, and an unpinned FROM makes the build itself
    unreproducible."""
    offenders = [
        f"{path}: {image}"
        for path, image in _dockerfile_bases()
        if "@sha256:" not in image and path not in OTHER_LANE_DOCKERFILES
    ]
    assert not offenders, (
        "these Dockerfile base images are not pinned to a digest:\n  "
        + "\n  ".join(offenders)
        + "\n\nAn unpinned FROM means two builds of the same release can sit on different "
        "base images, so a release cannot be rebuilt. Resolve the digest with "
        "tests/k8s/check_base_images_are_current.py's helper and write "
        "`FROM image@sha256:...`."
    )


def test_the_base_image_freshness_check_runs_somewhere():
    """A digest pin with no bump process is frozen-and-stale rather than
    floating-and-unreproducible — the same problem wearing different clothes, and quieter,
    because nothing breaks while the CVE count climbs."""
    nightly = (REPO / ".github" / "workflows" / "nightly-e2e.yml").read_text()
    assert "check_base_images_are_current.py" in nightly, (
        "nothing runs the base-image freshness check. Every FROM in this repository is "
        "pinned, so without it the bases age out of security support silently."
    )


@pytest.mark.parametrize("dockerfile", sorted(OTHER_LANE_DOCKERFILES))
def test_every_other_lane_dockerfile_still_exists(dockerfile: str):
    """An exemption naming a file that has been deleted or renamed is an exemption nobody
    revisits — and it silently widens to whatever takes that path next."""
    assert (REPO / dockerfile).exists(), (
        f"{dockerfile} is exempted from digest pinning but no longer exists. Delete the "
        f"entry, or update it to the new path."
    )


@pytest.mark.parametrize("image", sorted(DEPLOY_PINNED))
def test_every_deploy_pinned_image_is_actually_pinned_by_a_deploy(image: str):
    """The exemption above is a CLAIM about the deploy jobs, and it was false for one of
    the three: edge-agent was built, pushed and deployed, and repointed by nothing."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    for job in ("deploy-staging", "deploy-production"):
        script = " ".join(str(step.get("run", "")) for step in workflow["jobs"][job]["steps"])
        assert f"{image}=" in script, (
            f"{job} does not repoint {image}. base/ carries it as `:latest` on the "
            f"understanding that every deploy pins it — so without this line the workload "
            f"runs whatever was pushed last, with no correlation to the release tag."
        )
