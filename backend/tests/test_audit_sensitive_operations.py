"""FS-111: audit coverage for the newly-mounted subsystem control-plane mutations.

The audit middleware records an entry only when
``{METHOD}:{normalized_path}`` is a key in ``SENSITIVE_OPERATIONS``. These tests
lock in that the new subsystem mutations are registered AND that path
normalization collapses the free-form ``model_id`` (a non-UUID string) so the
templated key actually matches at request time.
"""

from __future__ import annotations

import pytest

from app.middleware.audit import SENSITIVE_OPERATIONS, AuditLoggingMiddleware


NEW_OPERATIONS = [
    "POST:/api/v1/twin/optimize",
    "POST:/api/v1/model-monitoring/reset/{id}",
    "POST:/api/v1/admin/query-performance/record-snapshot",
    "POST:/api/v1/admin/query-performance/refresh-frequent-queries",
    "POST:/api/v1/admin/query-performance/reset-stats",
]


@pytest.mark.parametrize("op", NEW_OPERATIONS)
def test_new_subsystem_mutations_are_audited(op):
    assert op in SENSITIVE_OPERATIONS, f"{op} missing from audit coverage"
    # Every action name is a non-empty snake_case verb phrase.
    action = SENSITIVE_OPERATIONS[op]
    assert action and action == action.lower()


def _mw() -> AuditLoggingMiddleware:
    # BaseHTTPMiddleware needs an app arg; a sentinel is fine — we only call the
    # pure _normalize_path helper, which never touches it.
    return AuditLoggingMiddleware(app=object())


def test_normalize_collapses_non_uuid_model_reset_id():
    mw = _mw()
    # A free-form model id (not a UUID) must still collapse to the {id} template.
    normalized = mw._normalize_path("/api/v1/model-monitoring/reset/oee-predictor-v2")
    assert normalized == "/api/v1/model-monitoring/reset/{id}"
    assert f"POST:{normalized}" in SENSITIVE_OPERATIONS


def test_normalize_still_collapses_uuids():
    mw = _mw()
    uuid = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    assert mw._normalize_path(f"/api/v1/assets/{uuid}") == "/api/v1/assets/{id}"


def test_static_admin_paths_match_verbatim():
    mw = _mw()
    # No path params -> normalization is a no-op and the key matches directly.
    for path in (
        "/api/v1/admin/query-performance/reset-stats",
        "/api/v1/twin/optimize",
    ):
        assert mw._normalize_path(path) == path
        assert f"POST:{path}" in SENSITIVE_OPERATIONS
