"""Tests for ERP test/sync helper logic (Phase A, tasks 2-3).

The DB-bound orchestration (run_erp_sync) is exercised end-to-end via `make up`;
here we unit-test the pure decision helpers it and the /test endpoint depend on.
"""

import pytest

from app.api.erp_integrations import extract_entity_id, interpret_health


@pytest.mark.parametrize("health,expected_status", [
    ({"healthy": True}, "success"),
    ({"healthy": False}, "error"),
    ({"status": "healthy"}, "success"),
    ({"status": "ok"}, "success"),
    ({"status": "down"}, "error"),
    ({}, "error"),
])
def test_interpret_health(health, expected_status):
    status, message = interpret_health(health)
    assert status == expected_status
    assert isinstance(message, str) and message


def test_interpret_health_uses_message():
    assert interpret_health({"healthy": True, "message": "pong"}) == ("success", "pong")


def test_extract_entity_id_prefers_id_fields():
    assert extract_entity_id({"id": "A1"}, 0) == "A1"
    assert extract_entity_id({"Number": "PO-9"}, 0) == "PO-9"
    assert extract_entity_id({"Key": 42}, 0) == "42"


def test_extract_entity_id_falls_back_to_index():
    assert extract_entity_id({"foo": "bar"}, 7) == "row-7"
