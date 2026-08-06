"""Every field the edge agent puts in a heartbeat is read, or declared unread (FS-460).

The agent builds one payload, `build_heartbeat_payload` in
`edge-agent/opsgrid_agent/versioning.py`, and the cloud consumes it in
`_process_agent_heartbeat`. Nothing connected the two: the agent could add a field, or the
worker could stop reading one, and both sides would keep passing their own tests.

**Three fields were computed on every device, serialised, transmitted, and dropped** —
`git_sha`, `collector_status` and `buffer_depth`. They are gone from the payload now
(FS-466), which is the right end for them: the worker persists `agent_id`, `agent_version`,
`config_hash` and `build_id`, reads `organization_id` and `asset_ids` to route the update and
`timestamp` to stamp it, and that is the whole job of this message.

WHY THAT IS WORTH A GUARD RATHER THAN A SHRUG — **and a correction, because the first
version of this docstring drew the wrong conclusion.**

It said device backlog was invisible to the cloud. It is not. A SECOND heartbeat path exists,
`POST /api/v1/edge/heartbeat` in `app/api/edge_fleet.py`, and the agent posts `buffer_pending`,
`dead_lettered`, `dropped` and `active_collectors` to it; the backend persists them on
`edge_agent_status` and publishes per-agent `edge_agent_*` gauges. Backlog is stored, gauged
and alertable.

The original claim came from reading this path and generalising. **A sweep that finds one
consumer and concludes there is no other is asserting a negative it did not check** — found
by coming at it from the opposite end, while checking whether a backend gauge had a producer.

So the same health was being assembled twice, under two names for one quantity
(`buffer_depth` here, `buffer_pending` there), and this path's copy was read by nobody —
redundant work on every device and two vocabularies for one fact, the condition that produced
six aliases in FS-435. **Closed by narrowing this payload rather than by widening the
worker**, because the other path already answers the question and answers it to something.

WHAT THIS ASSERTS. Not that the fields must be stored — persisting them needs a migration and
a decision about what the fleet surface should show, which is on the open-decisions page. Only
that the gap cannot widen silently, and that a field added to the payload has to be either
consumed or explicitly written down as ignored, with a reason someone can argue with.

This is the same shape as `test_frontend_fields_exist_on_the_wire.py` one boundary further
out: there the client declares fields the server never sends, here the agent sends fields the
server never reads. Both are a contract with only one side asserted.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
VERSIONING = ROOT / "edge-agent" / "opsgrid_agent" / "versioning.py"
INGESTION = ROOT / "backend" / "app" / "workers" / "ingestion.py"

#: Fields the worker deliberately does not persist, each with the reason. An entry is a
#: claim that someone looked; keep them short enough to check and specific enough to argue
#: with. Removing a field from here without consuming it fails the test.
#:
#: **This dict is nearly empty now, and that is the outcome** (FS-466). It once held
#: `git_sha`, `collector_status` and `buffer_depth` with reasons about why nobody read
#: them. Those three were removed from the payload instead: the cloud read none of them,
#: and device health travels the HTTP heartbeat, which has a consumer. An exemption is a
#: place to record a decision, not a place to keep one indefinitely.
DELIBERATELY_UNREAD: dict[str, str] = {
    # Routing and envelope, consumed but not by name in a `data.get(...)` the scan can see.
    "message_type": "the branch discriminator; read before dispatch",
}


def _payload_fields() -> set[str]:
    """The keys `build_heartbeat_payload` returns."""
    tree = ast.parse(VERSIONING.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_heartbeat_payload":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Dict):
                    return {
                        k.value
                        for k in inner.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    }
    return set()


def _fields_the_worker_reads() -> set[str]:
    """Names passed to `data.get(...)` or `data[...]` inside the heartbeat handler."""
    source = INGESTION.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == "_process_agent_heartbeat"
        ):
            segment = ast.get_source_segment(source, node) or ""
            return set(re.findall(r"data\.get\(['\"](\w+)['\"]", segment)) | set(
                re.findall(r"data\[['\"](\w+)['\"]\]", segment)
            )
    return set()


PAYLOAD = _payload_fields()
READ = _fields_the_worker_reads()


class TestBothSidesWereActuallyFound:
    """Neither half may be empty: an empty set makes the comparison below vacuous."""

    def test_the_agent_payload_was_parsed(self):
        assert len(PAYLOAD) >= 8, (
            f"only {len(PAYLOAD)} heartbeat fields parsed from {VERSIONING.name}; the AST "
            f"walk is broken and the comparison would pass over nothing"
        )
        assert "agent_id" in PAYLOAD, "the parse found a dict, but not the payload dict"

    def test_the_worker_handler_was_parsed(self):
        assert len(READ) >= 4, (
            f"only {len(READ)} fields found in _process_agent_heartbeat; the handler was "
            f"renamed or the scan is broken"
        )
        assert "organization_id" in READ

    def test_the_exemptions_still_name_real_fields(self):
        stale = sorted(f for f in DELIBERATELY_UNREAD if f not in PAYLOAD)
        assert not stale, (
            f"these fields are recorded as deliberately unread and the agent no longer "
            f"sends them: {stale}. An exemption naming nothing hides the next one."
        )


class TestTheContractHasNoSilentGap:
    def test_every_sent_field_is_read_or_declared_unread(self):
        unaccounted = sorted(PAYLOAD - READ - set(DELIBERATELY_UNREAD))
        assert not unaccounted, (
            "the edge agent sends these heartbeat fields and the cloud neither reads them "
            "nor records a reason:\n  "
            + "\n  ".join(unaccounted)
            + "\n\nEither consume them in `_process_agent_heartbeat` or add an entry to "
            "DELIBERATELY_UNREAD saying why not. A field computed on every device, "
            "serialised and transmitted to be discarded is either waste or a missing "
            "feature, and which one it is should be written down."
        )

    def test_the_worker_reads_nothing_the_agent_does_not_send(self):
        """The other direction, and the one that fails silently in production: a
        `data.get('x')` for a field no agent sends returns None forever, and the column it
        writes stays NULL while the code reads as though it were populated."""
        phantom = sorted(READ - PAYLOAD)
        assert not phantom, (
            f"the heartbeat handler reads these fields and no agent sends them: {phantom}. "
            f"`data.get` returns None rather than raising, so the column silently stays "
            f"NULL and nothing anywhere reports a problem."
        )


class TestNothingIsQuietlyDiscardedAgain:
    """The ratchet, at its floor.

    This class used to allow three discarded fields and assert the count had not grown.
    They were removed, so the allowance is zero and the assertion is that it stays there:
    a field added to this payload has to be consumed or explicitly exempted, and an
    exemption has to say why in a sentence someone can disagree with.
    """

    def test_no_payload_field_is_discarded(self):
        dropped = {f for f in DELIBERATELY_UNREAD if f != "message_type"}
        assert not dropped, (
            f"{sorted(dropped)} are exempted from being read. The last three exemptions "
            f"here were closed by DELETING the fields, because the agent was computing "
            f"them on every beat for nobody. Prefer that to writing a reason."
        )


class TestTheOtherHeartbeatPathStillConsumesTheseFields:
    """The correction, pinned (FS-460, Rule 92).

    This file originally asserted that a device's buffer depth reached the cloud and was
    thrown away. It was wrong: `POST /api/v1/edge/heartbeat` consumes the same quantity
    under the name `buffer_pending`, persists it, and publishes it as a per-agent gauge.

    The exemptions above now say so, which makes them claims about code in a different
    module — and an uncheckable claim in an exemption is how the original error survived
    review. So they are checked. If the HTTP path stops consuming device health, the
    reasons written beside `buffer_depth` and `collector_status` become false and the
    Kafka copy stops being the redundant one.
    """

    HTTP_HEARTBEAT = ROOT / "backend" / "app" / "api" / "edge_fleet.py"
    FLEET_SERVICE = ROOT / "backend" / "app" / "services" / "edge_fleet.py"

    def test_the_http_heartbeat_endpoint_exists(self):
        assert self.HTTP_HEARTBEAT.exists(), (
            "the HTTP heartbeat module is gone; the exemptions above claim it consumes "
            "device health"
        )
        assert "/edge/heartbeat" in self.HTTP_HEARTBEAT.read_text(), (
            "no /edge/heartbeat route found"
        )

    @pytest.mark.parametrize("field", ["buffer_pending", "dead_lettered", "active_collectors"])
    def test_it_reads_the_health_fields(self, field: str):
        assert field in self.HTTP_HEARTBEAT.read_text(), (
            f"the HTTP heartbeat no longer reads {field!r}, so device health is no longer "
            f"reaching the cloud by that path — and the exemption beside `buffer_depth` "
            f"above, which says this copy is the redundant one, is now false"
        )

    def test_buffer_depth_reaches_a_gauge(self):
        """Persisting it is not the same as making it visible. The claim in the exemption
        is that an operator can see device backlog, which needs the gauge."""
        service = self.FLEET_SERVICE.read_text()
        assert "edge_agent_buffer_pending" in service, (
            "the per-agent buffer gauge is gone; device backlog is no longer observable "
            "from the cloud and open-decisions #5 needs reopening at its original severity"
        )
        assert ".set(" in service, "the gauge is declared but nothing sets it"

    def test_the_agent_actually_sends_that_payload(self):
        """The last link. A consumer with no producer is the mirror image of the mistake
        this class was written to correct.

        The KEYS OF THE RETURNED DICT, not a substring search of the module. The first
        version searched the file text and passed when the emitted key was renamed,
        because `build_payload` reads the same name out of its health snapshot one line
        above — so the string was still present while the payload no longer carried it.
        Caught by mutating the key and watching this stay green.
        """
        reporter = ROOT / "edge-agent" / "opsgrid_agent" / "heartbeat.py"
        assert reporter.exists(), "the agent's HTTP heartbeat reporter is gone"

        tree = ast.parse(reporter.read_text())
        sent: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "build_payload":
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Dict):
                        sent |= {
                            k.value
                            for k in inner.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)
                        }
        assert sent, "build_payload not found or returns no literal dict"

        missing = sorted(
            {"buffer_pending", "dead_lettered", "active_collectors"} - sent
        )
        assert not missing, (
            f"the agent no longer sends {missing} on the HTTP heartbeat, so the cloud "
            f"consumer has nothing to consume and the exemptions above are false"
        )

