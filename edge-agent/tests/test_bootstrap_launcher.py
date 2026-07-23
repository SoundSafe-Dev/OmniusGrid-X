import json

import pytest

from bootstrap.launcher import AgentBootstrap, BootstrapError


def _installed(runtime_root, version):
    target = runtime_root / "versions" / version
    target.mkdir(parents=True)
    (target / "install.json").write_text(
        json.dumps({"version": version}),
        encoding="utf-8",
    )
    return target


def _bootstrap(tmp_path):
    seed = tmp_path / "seed.whl"
    seed.write_bytes(b"unused")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    return AgentBootstrap(
        runtime_root=runtime,
        seed_wheel=seed,
        ready_timeout_seconds=1,
        poll_interval_seconds=0.01,
    )


def test_selects_staged_version_with_durable_previous_pointer(tmp_path):
    bootstrap = _bootstrap(tmp_path)
    _installed(bootstrap.runtime_root, "1.0.0")
    _installed(bootstrap.runtime_root, "2.0.0")
    bootstrap._atomic_write_text(bootstrap.current_path, "1.0.0")
    journal = {
        "status": "restart_requested",
        "attempted_version": "2.0.0",
        "previous_version": "1.0.0",
    }
    bootstrap._atomic_write_json(bootstrap.journal_path, journal)

    selected = bootstrap._select_attempted_version("1.0.0", journal)

    assert selected == "2.0.0"
    assert bootstrap._read_pointer(bootstrap.current_path) == "2.0.0"
    assert bootstrap._read_pointer(bootstrap.previous_path) == "1.0.0"
    assert bootstrap._read_json(bootstrap.journal_path)["status"] == "booting"


def test_selection_recovers_pointer_swap_power_loss(tmp_path):
    bootstrap = _bootstrap(tmp_path)
    _installed(bootstrap.runtime_root, "1.0.0")
    _installed(bootstrap.runtime_root, "2.0.0")
    bootstrap._atomic_write_text(bootstrap.current_path, "2.0.0")
    bootstrap._atomic_write_text(bootstrap.previous_path, "1.0.0")
    journal = {
        "status": "restart_requested",
        "attempted_version": "2.0.0",
        "previous_version": "1.0.0",
    }

    selected = bootstrap._select_attempted_version("2.0.0", journal)

    assert selected == "2.0.0"
    assert bootstrap._read_json(bootstrap.journal_path)["status"] == "booting"


def test_failed_candidate_restores_previous_version_and_records_reason(tmp_path):
    bootstrap = _bootstrap(tmp_path)
    _installed(bootstrap.runtime_root, "1.0.0")
    _installed(bootstrap.runtime_root, "2.0.0")
    bootstrap._atomic_write_text(bootstrap.current_path, "2.0.0")
    journal = {
        "status": "booting",
        "attempted_version": "2.0.0",
        "previous_version": "1.0.0",
    }

    selected = bootstrap._rollback_candidate(
        attempted="2.0.0",
        journal=journal,
        failure_phase="process_exit",
        detail="return code 7",
    )

    assert selected == "1.0.0"
    assert bootstrap._read_pointer(bootstrap.current_path) == "1.0.0"
    state = bootstrap._read_json(bootstrap.journal_path)
    assert state["status"] == "rollback_booting"
    assert state["running_version"] == "1.0.0"
    assert state["rolled_back"] is True
    assert state["phase"] == "process_exit"


def test_archives_only_after_terminal_ack_state(tmp_path):
    bootstrap = _bootstrap(tmp_path)
    bootstrap._atomic_write_json(
        bootstrap.journal_path,
        {"status": "booting", "attempted_version": "2.0.0"},
    )

    with pytest.raises(BootstrapError, match="terminal update ack"):
        bootstrap._archive_finished_update()

    bootstrap._atomic_write_json(
        bootstrap.journal_path,
        {"status": "completed", "attempted_version": "2.0.0"},
    )
    bootstrap._archive_finished_update()

    assert not bootstrap.journal_path.exists()
    assert bootstrap._read_json(bootstrap.last_update_path)["status"] == "completed"
