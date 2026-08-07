"""Every safety switch the agent reads has a decided value in the shipped manifest (FS-508).

THE FINDING, which is wider than the item that started it. The agent reads four switches that
choose between a permissive and a safe behaviour:

    EDGE_REQUIRE_TLS              main.py:245,257   false  -> uplink may degrade to plaintext
    KAFKA_SECURITY_PROTOCOL       main.py:246       PLAINTEXT -> no mTLS on the telemetry uplink
    EDGE_REQUIRE_EXPLICIT_SOURCES base.py:44        false  -> an omitted source SYNTHESIZES data
    ENROLLMENT_CA_FINGERPRINT     enrollment.py:105 unset  -> the trust root is whatever the
                                                             network returned

**Every one defaults to the permissive branch, and all four were set in exactly one place in
the repository: a commented-out block in `deploy/install.sh:35-38` headed "Production
posture".** Nothing in `infrastructure/k8s/base/edge-agent-statefulset.yaml` set any of them,
no overlay patches the edge agent at all (`grep -rln edge-agent overlays/` is empty), and the
StatefulSet is therefore what production runs verbatim.

WHY THAT IS A DEFECT AND NOT A PREFERENCE. The production overlay sets `MTLS_ENABLED=true` for
the backend (`overlays/production/kustomization.yaml`). One side of the connection is
configured to require mTLS and the other side is configured for plaintext, in the same tree, by
the same operator, and nothing compares them. A commented line is documentation of an
intention; it configures nothing. The manifest is the only artefact that decides.

WHAT THIS FILE DOES. It requires every switch to appear in the StatefulSet with an explicit
value — or to be listed below with the reason it is deliberately left at its default and what
has to happen first. The distinction is between a default nobody chose and a default somebody
chose, and only the second is safe to ship.

WHAT IS FIXED HERE AND WHAT IS NOT. `EDGE_REQUIRE_EXPLICIT_SOURCES=true` is set: it refuses
only a config that omits `source` on a synthetic-capable collector, so it cannot break a
running fleet. The two TLS switches are NOT flipped — fail-closed TLS aborts startup on an
agent that has not enrolled (`main.py:608-611` documents that ordering hazard), so turning
them on before mTLS enrollment is proven end-to-end in a cluster would brick the fleet on
deploy. That is a Wave L item with a cluster behind it, and it is recorded below rather than
guessed at here.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
STATEFULSET = REPO / "infrastructure" / "k8s" / "base" / "edge-agent-statefulset.yaml"

#: Switches that choose between a permissive and a safe behaviour, with what the permissive
#: branch costs. Each must be set in the StatefulSet or excused below.
POSTURE_SWITCHES = {
    "EDGE_REQUIRE_EXPLICIT_SOURCES":
        "an audio or video collector with no `source` synthesizes its readings instead of "
        "refusing to start (collectors/base.py:44-50)",
    "EDGE_REQUIRE_TLS":
        "a failure to build the mTLS context degrades the telemetry uplink to plaintext "
        "instead of aborting (main.py:245-253)",
    "KAFKA_SECURITY_PROTOCOL":
        "the uplink runs PLAINTEXT with no client certificate, while the production overlay "
        "sets MTLS_ENABLED=true for the backend it connects to (main.py:246)",
    "ENROLLMENT_CA_FINGERPRINT":
        "the CA bundle returned by the enrollment call is trusted unpinned — the enrollment "
        "response is the trust root for the whole fleet (security/enrollment.py:105-108)",
}

#: Switches deliberately left at their default, with why and what closes it.
DEFERRED = {
    "EDGE_REQUIRE_TLS":
        "Fail-closed. An agent that has not completed enrollment aborts at startup rather "
        "than degrading, and main.py:608-611 records that the cloud link must come up before "
        "the producer for exactly this reason. Turning it on before mTLS enrollment is proven "
        "against a real cluster would brick the fleet on the deploy that enabled it. Blocked "
        "on Wave L (a cluster, or a --dry-run=server gate standing in for one).",
    "KAFKA_SECURITY_PROTOCOL":
        "Same blocker and the same change as EDGE_REQUIRE_TLS: SSL here without an enrolled "
        "identity produces no context, and with EDGE_REQUIRE_TLS still false that silently "
        "falls back to plaintext, which is worse than the honest default. The two flip "
        "together or not at all.",
    "ENROLLMENT_CA_FINGERPRINT":
        "Not a boolean — it is the sha256 of the operator's own CA cert DER, so there is no "
        "value this repository can supply. It belongs in the per-environment ConfigMap "
        "alongside organization_id. Recorded here so it is a gap with an owner rather than "
        "an omission nobody sees.",
}


def _statefulset_env() -> dict[str, str]:
    """The env names the edge-agent container actually sets, with their literal values.

    Reads YAML rather than grepping, because the variable this file exists for was findable
    by grep in `install.sh` — as a comment. A commented line configures nothing, and a
    detector that cannot tell the difference would have passed on the broken tree.
    """
    doc = yaml.safe_load(STATEFULSET.read_text())
    containers = doc["spec"]["template"]["spec"]["containers"]
    env: dict[str, str] = {}
    for container in containers:
        for entry in container.get("env") or []:
            if "value" in entry:
                env[entry["name"]] = str(entry["value"])
            else:
                env[entry["name"]] = "<from:{}>".format(
                    ",".join(sorted(entry.get("valueFrom", {})))
                )
    return env


class TestTheReaderCanTellCodeFromComments:
    def test_it_reads_values_not_text(self):
        """The whole point. `install.sh` "sets" all four of these — in comments."""
        env = _statefulset_env()
        assert "REDPANDA_URL" in env and env["REDPANDA_URL"], (
            "the StatefulSet env could not be parsed; every assertion below would then "
            "report the manifest as setting nothing"
        )
        commented = STATEFULSET.read_text()
        assert re.search(r"^\s*#\s*-\s*name:\s*COLLECTORS_FILE", commented, re.M), (
            "the commented-out COLLECTORS_FILE block is gone from the manifest, so this "
            "test no longer proves the reader ignores comments — point it at another one "
            "or drop it"
        )
        assert "COLLECTORS_FILE" not in env, (
            "the reader counted a COMMENTED env entry as set. That is precisely the mistake "
            "that let four posture switches read as configured while living in a comment "
            "block in install.sh."
        )


class TestEverySwitchHasADecidedValue:
    @pytest.mark.parametrize("switch,cost", sorted(POSTURE_SWITCHES.items()))
    def test_the_manifest_decides_it(self, switch: str, cost: str):
        env = _statefulset_env()
        if switch in env:
            return
        assert switch in DEFERRED, (
            f"{switch} is not set by the shipped StatefulSet, so production inherits the "
            f"permissive default: {cost}. Set it in the manifest, or add it to DEFERRED with "
            f"why it is deliberately left alone and what closes it. A commented line in "
            f"install.sh is not a decision — that is how all four of these got here."
        )

    def test_the_synthetic_source_guard_is_on(self):
        """FS-508's own subject, stated separately so a future edit to DEFERRED cannot
        quietly re-permit it."""
        env = _statefulset_env()
        assert env.get("EDGE_REQUIRE_EXPLICIT_SOURCES") == "true", (
            "EDGE_REQUIRE_EXPLICIT_SOURCES is no longer 'true' in the shipped manifest. "
            "Without it, an audio or video collector whose `source` key is missing or "
            "mistyped synthesizes its readings and emits them through the ordinary pipeline "
            "— an asset that looks live and measures nothing."
        )


class TestTheDeferralsAreStillReal:
    @pytest.mark.parametrize("switch", sorted(DEFERRED))
    def test_a_deferred_switch_that_got_set_is_removed_from_the_list(self, switch: str):
        env = _statefulset_env()
        assert switch not in env, (
            f"{switch} is set in the manifest now, so its DEFERRED entry is stale and reads "
            f"as an outstanding gap that has been closed. Delete the entry."
        )

    @pytest.mark.parametrize("switch,reason", sorted(DEFERRED.items()))
    def test_each_deferral_says_what_closes_it(self, switch: str, reason: str):
        assert len(reason) > 100, (
            f"the DEFERRED entry for {switch} does not say what has to happen before it can "
            f"be set. Without that it is an excuse, not a decision."
        )


class TestTheAgentStillReadsWhatWeGuard:
    @pytest.mark.parametrize("switch", sorted(POSTURE_SWITCHES))
    def test_the_switch_is_still_read_by_the_agent(self, switch: str):
        """A guard whose subjects the code stopped reading protects nothing — and would sit
        here looking diligent. This is the failure mode FS-484, FS-492 and FS-504 each cost
        once."""
        sources = "".join(
            path.read_text() for path in (ROOT / "opsgrid_agent").rglob("*.py")
        )
        assert switch in sources, (
            f"{switch} appears nowhere in opsgrid_agent/ — the agent no longer reads it, so "
            f"setting it in the manifest does nothing. Remove it from POSTURE_SWITCHES, or "
            f"find out what replaced it."
        )
