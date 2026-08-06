"""Every field the edge agent puts in a heartbeat is read, or declared unread (FS-460).

The agent builds one payload, `build_heartbeat_payload` in
`edge-agent/opsgrid_agent/versioning.py`, and the cloud consumes it in
`_process_agent_heartbeat`. Nothing connected the two: the agent could add a field, or the
worker could stop reading one, and both sides would keep passing their own tests.

**Three fields are computed on every device, serialised, transmitted, and dropped.** The
worker persists `agent_id`, `agent_version`, `config_hash` and `build_id`; it reads
`organization_id` and `asset_ids` to route the update and `timestamp` to stamp it. It never
touches `git_sha`, `collector_status` or `buffer_depth`.

WHY THAT IS WORTH A GUARD RATHER THAN A SHRUG. `buffer_depth` is the single number that says
a device is falling behind, and the heartbeat is the path that works when the device is
behind NAT and its `/metrics` cannot be scraped. `collector_status` is per-collector health
from the same place. So the fleet view's answer to "is anything wrong out there" is arriving
at the cloud, in a message the cloud already parses, and being thrown away — while the
`EdgeBufferGrowing` alert that would say the same thing requires reaching the device that,
in the case worth catching, cannot be reached.

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
DELIBERATELY_UNREAD: dict[str, str] = {
    "git_sha": (
        "build provenance. `agent_build_id` already identifies the build and is persisted; "
        "the sha adds precision nothing currently asks for"
    ),
    "collector_status": (
        "per-collector health. Needs a column and a decision about what the fleet surface "
        "shows — open-decisions.md"
    ),
    "buffer_depth": (
        "pending messages on the device. The operationally sharpest of the three, and the "
        "reason this guard exists rather than a comment — open-decisions.md"
    ),
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


class TestTheThreeUnreadFieldsAreStillUnread:
    """A ratchet, so closing the gap is visible rather than quiet.

    If someone persists `buffer_depth`, this fails and the entry comes out of both this file
    and the open-decisions register in the same commit — which is the only way that page
    stays worth reading.
    """

    def test_the_count_has_not_grown(self):
        # `message_type` is envelope, not payload data — excluded from the count so the
        # number means "fields the cloud throws away".
        dropped = {f for f in DELIBERATELY_UNREAD if f != "message_type"}
        assert len(dropped) <= 3, (
            f"{len(dropped)} heartbeat fields are now discarded, up from three. The agent "
            f"is doing work on every device that reaches nobody."
        )
