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

WHAT IS EXEMPT, and why each is a decision rather than an oversight — see `DEPLOY_PINNED`
and `NOT_DEPLOYED` below.
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


def _repo_of(image: str) -> str:
    return image.split("@")[0].rsplit(":", 1)[0] if ":" in image.split("@")[0] else image.split("@")[0]


@pytest.mark.parametrize("image", sorted(UNRESOLVABLE))
def test_every_unresolvable_image_says_why(image: str):
    """An exemption without a reason is an exemption nobody will ever revisit."""
    reason = UNRESOLVABLE[image]
    assert len(reason) > 80, f"{image} is exempted without a real explanation"


class TestTheMeasurementIsReal:
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
