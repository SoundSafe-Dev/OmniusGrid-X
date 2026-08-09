from opsgrid_agent.versioning import (
    build_heartbeat_payload,
    build_manifest,
    compute_config_hash,
    load_agent_state,
    persist_agent_state,
)


def test_config_hash_is_deterministic_for_key_order():
    left = [{"asset_id": "a1", "config": {"b": 2, "a": 1}}]
    right = [{"config": {"a": 1, "b": 2}, "asset_id": "a1"}]

    assert compute_config_hash(left) == compute_config_hash(right)
    assert compute_config_hash(left) != compute_config_hash(
        [{"asset_id": "a1", "config": {"a": 1, "b": 3}}]
    )


def test_manifest_lists_supported_collectors_sorted():
    manifest = build_manifest(
        ["modbus", "mqtt"],
        version="1.2.3",
        build_id="build-7",
        git_sha="abc123",
        build_time="2030-01-01T00:00:00Z",
    )

    assert manifest == {
        "agent_version": "1.2.3",
        "build_id": "build-7",
        "git_sha": "abc123",
        "build_time": "2030-01-01T00:00:00Z",
        "supported_collectors": ["modbus", "mqtt"],
    }


def test_agent_state_persists_atomically(tmp_path):
    path = tmp_path / "agent_state.json"
    state = {
        "agent_id": "agent-1",
        "agent_version": "1.2.3",
        "config_hash": "abc",
    }

    persist_agent_state(path, state)

    assert load_agent_state(path) == state


def test_heartbeat_payload_shape():
    """The Kafka heartbeat's exact shape after the 2026-08-08 merge.

    FS-466 had narrowed this to identity only — `git_sha`, `collector_status` and
    `buffer_depth` were sent every beat and the cloud read none of them. Hridyansh's OTA
    work re-widened it, and his `_process_agent_heartbeat` DOES consume `collector_status`,
    so the FS-466 argument no longer holds for that field. The merge kept his payload rather
    than dropping another lane's fields; `build_heartbeat_payload`'s docstring records which
    ones still have no reader, and `test_heartbeat_contract_is_fully_read` is where that is
    enforced.

    THE EXACT-EQUALITY ASSERTION IS STILL THE POINT. An added field nobody reads is how the
    original three got here, and `==` fails on an addition where `issubset` would not.
    """
    payload = build_heartbeat_payload(
        agent_id="agent-1",
        organization_id="org-1",
        asset_ids=["asset-1", "asset-2"],
        manifest={"agent_version": "1.2.3", "build_id": "build-7", "git_sha": "deadbee"},
        config_hash="abc123",
        collector_status={"collectors": {}},
        buffer_depth=0,
        timestamp="2030-01-01T00:00:00Z",
    )

    assert payload == {
        "message_type": "agent_heartbeat",
        "agent_id": "agent-1",
        "organization_id": "org-1",
        "asset_ids": ["asset-1", "asset-2"],
        "agent_version": "1.2.3",
        "config_hash": "abc123",
        "build_id": "build-7",
        "git_sha": "deadbee",
        "collector_status": {"collectors": {}},
        "buffer_depth": 0,
        "timestamp": "2030-01-01T00:00:00Z",
    }


def test_agent_update_is_only_sent_when_there_is_one():
    """`agent_update` is conditional, and that is deliberate: a key present on every beat
    with a null value is a field the consumer has to special-case. Hridyansh's OTA reports
    a self-update outcome only when one happened."""
    base = dict(
        agent_id="a", organization_id="o", asset_ids=[],
        manifest={"agent_version": "1", "build_id": "b"},
        config_hash="c", collector_status={}, buffer_depth=0,
        timestamp="2030-01-01T00:00:00Z",
    )
    assert "agent_update" not in build_heartbeat_payload(**base)
    assert build_heartbeat_payload(**base, update_status={"state": "succeeded"})[
        "agent_update"
    ] == {"state": "succeeded"}


def test_heartbeat_reports_restart_spanning_update_state():
    payload = build_heartbeat_payload(
        agent_id="agent-1",
        organization_id="org-1",
        asset_ids=["asset-1"],
        manifest={"agent_version": "1.0.0"},
        config_hash="abc123",
        collector_status={"active_collectors": 1, "total_collectors": 1},
        buffer_depth=0,
        update_status={
            "status": "rolled_back",
            "attempted_version": "2.0.0",
            "running_version": "1.0.0",
            "rolled_back": True,
        },
        timestamp="2030-01-01T00:00:00Z",
    )

    assert payload["agent_version"] == "1.0.0"
    assert payload["agent_update"] == {
        "status": "rolled_back",
        "attempted_version": "2.0.0",
        "running_version": "1.0.0",
        "rolled_back": True,
    }
