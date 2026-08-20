"""The two OpenTelemetry collector configs are copies, and one of them can silently rot (FS-791/792/793).

The compose collector reads `infra/otel/otel-collector-config.yaml`; the cluster one
reads an inline copy embedded in `infrastructure/k8s/base/otel-collector.yaml`. Two files
holding one intention, with nothing comparing them — the shape that produced the
`promtail.yml` / job-label / alert-rule divergences this sprint keeps finding, where the
environment that matters is the one that quietly stops working.

Three things are checked, each corresponding to a way this actually breaks:

  * **The pipelines match.** A processor added to one and not the other means a trace is
    sampled in production and not locally, or the reverse — and the reverse is worse,
    because it is the version nobody exercises.

  * **`tail_sampling` requires the CONTRIB distribution.** `otel/opentelemetry-collector`
    (core) does not ship it. A config naming a processor the binary does not have is a
    startup failure, so switching the image to core would take tracing down entirely —
    and the symptom, no traces, is indistinguishable from tracing being disabled, which
    it is by default.

  * **The sampler runs before the batcher.** `batch` ahead of `tail_sampling` makes the
    sampler hold batches rather than whole traces, so its decisions are taken on
    fragments. It still starts, still exports, and quietly samples on the wrong thing.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
COMPOSE_CONFIG = REPO / "infra" / "otel" / "otel-collector-config.yaml"
K8S_MANIFEST = REPO / "infrastructure" / "k8s" / "base" / "otel-collector.yaml"

#: Processors that exist only in otel/opentelemetry-collector-contrib.
CONTRIB_ONLY = {"tail_sampling", "k8sattributes", "resourcedetection", "spanmetrics"}


def _k8s_documents() -> list[dict]:
    return [d for d in yaml.safe_load_all(K8S_MANIFEST.read_text()) if d]


def _k8s_collector_config() -> dict:
    for doc in _k8s_documents():
        if doc.get("kind") != "ConfigMap":
            continue
        for value in (doc.get("data") or {}).values():
            parsed = yaml.safe_load(value)
            if isinstance(parsed, dict) and "receivers" in parsed:
                return parsed
    raise AssertionError("no collector config found in the k8s ConfigMap")


def _compose_collector_config() -> dict:
    return yaml.safe_load(COMPOSE_CONFIG.read_text())


def _collector_images() -> dict[str, str]:
    images = {}
    for doc in _k8s_documents():
        if doc.get("kind") not in {"Deployment", "StatefulSet", "DaemonSet"}:
            continue
        for container in doc["spec"]["template"]["spec"].get("containers", []):
            if "opentelemetry-collector" in container.get("image", ""):
                images["k8s"] = container["image"]
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    for name, service in (compose.get("services") or {}).items():
        if "opentelemetry-collector" in (service.get("image") or ""):
            images["compose"] = service["image"]
    return images


CONFIGS = {"compose": _compose_collector_config, "k8s": _k8s_collector_config}


class TestTheMeasurementIsReal:
    def test_both_configs_parse(self):
        for label, loader in CONFIGS.items():
            config = loader()
            assert "receivers" in config, f"{label}: no receivers parsed"
            assert config["service"]["pipelines"]["traces"], f"{label}: no traces pipeline"

    def test_it_found_both_images(self):
        images = _collector_images()
        assert set(images) == {"compose", "k8s"}, images


def test_the_trace_pipelines_match():
    compose = _compose_collector_config()["service"]["pipelines"]["traces"]
    k8s = _k8s_collector_config()["service"]["pipelines"]["traces"]
    assert compose["processors"] == k8s["processors"], (
        f"the two collectors run different processor chains:\n"
        f"  compose: {compose['processors']}\n"
        f"  k8s:     {k8s['processors']}\n\n"
        f"One environment is sampling, tracing or limiting differently from the other, "
        f"and the divergence is invisible until an incident in the environment nobody "
        f"exercises."
    )
    assert compose["receivers"] == k8s["receivers"]


def test_the_sampling_policies_match():
    def policies(config):
        block = config.get("processors", {}).get("tail_sampling")
        return None if not block else {p["name"]: p["type"] for p in block["policies"]}

    compose, k8s = policies(_compose_collector_config()), policies(_k8s_collector_config())
    assert compose == k8s, (
        f"tail-sampling policies differ:\n  compose: {compose}\n  k8s: {k8s}\n\n"
        f"A trace kept locally and discarded in production is the worst version of "
        f"this: it is retained exactly where nobody needs it."
    )
    assert compose, "no tail_sampling policies in either config"


@pytest.mark.parametrize("label", sorted(CONFIGS))
def test_the_sampler_runs_before_the_batcher(label):
    chain = CONFIGS[label]()["service"]["pipelines"]["traces"]["processors"]
    if "tail_sampling" not in chain:
        pytest.skip("no tail sampling in this pipeline")
    assert chain.index("tail_sampling") < chain.index("batch"), (
        f"{label}: `batch` runs before `tail_sampling` ({chain}). The sampler then "
        f"holds batches rather than whole traces and decides on fragments — it starts "
        f"cleanly, exports cleanly, and samples on the wrong thing."
    )


@pytest.mark.parametrize("label", sorted(CONFIGS))
def test_contrib_only_processors_have_a_contrib_image(label):
    used = set(CONFIGS[label]().get("processors", {}))
    needs_contrib = used & CONTRIB_ONLY
    if not needs_contrib:
        pytest.skip("no contrib-only processors configured")
    image = _collector_images()[label]
    assert "opentelemetry-collector-contrib" in image, (
        f"{label} configures {sorted(needs_contrib)}, which ship only in the contrib "
        f"distribution, but runs {image!r}. The collector fails to start on a processor "
        f"its binary does not have — and the symptom, no traces at all, is exactly what "
        f"tracing being disabled looks like."
    )


def test_jaeger_storage_survives_a_restart():
    """FS-792. `all-in-one` defaults to memory storage, so every trace was lost on
    restart — and a restart is what an incident produces. Yesterday's outage could not
    be investigated today."""
    jaeger = next(
        (
            d for d in _k8s_documents()
            if d.get("metadata", {}).get("name") == "jaeger"
            and d.get("kind") in {"Deployment", "StatefulSet"}
        ),
        None,
    )
    assert jaeger is not None, "no jaeger workload found"
    assert jaeger["kind"] == "StatefulSet", (
        "jaeger is a Deployment again; without a volume claim its spans live in the "
        "pod and vanish with it."
    )
    env = {
        e["name"]: e.get("value")
        for c in jaeger["spec"]["template"]["spec"]["containers"]
        for e in c.get("env", [])
    }
    assert env.get("SPAN_STORAGE_TYPE") == "badger", env
    assert env.get("BADGER_EPHEMERAL") == "false", (
        "BADGER_EPHEMERAL is not false. Left at its default badger writes to a temp "
        "directory, so the PVC is mounted, the manifest looks persistent, and the "
        "traces still do not survive a restart."
    )
    assert jaeger["spec"].get("volumeClaimTemplates"), "no PVC for the span store"
