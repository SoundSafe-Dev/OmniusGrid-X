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
    payload = build_heartbeat_payload(
        agent_id="agent-1",
        organization_id="org-1",
        asset_ids=["asset-1", "asset-2"],
        manifest={"agent_version": "1.2.3", "build_id": "build-7"},
        config_hash="abc123",
        collector_status={"active_collectors": 2, "total_collectors": 2},
        buffer_depth=4,
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
        "git_sha": None,
        "collector_status": {"active_collectors": 2, "total_collectors": 2},
        "buffer_depth": 4,
        "timestamp": "2030-01-01T00:00:00Z",
    }


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
