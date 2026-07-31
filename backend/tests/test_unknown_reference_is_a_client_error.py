"""A reference to a row that does not exist is 400, not 500.

`POST /api/v1/yard/moves` with a `trailer_id` that names no trailer raised
ForeignKeyViolationError and returned 500. The caller pointed at something absent — that
is their mistake, and a 500 both misleads them (retry will not help) and spends the error
budget on a 4xx.

TWO THINGS THIS DELIBERATELY DOES NOT DO.

**It does not echo the value.** Postgres's DETAIL line contains the offending key —
often a UUID the caller supplied, but on a tenant-scoped column it can be somebody else's
identifier. Reflecting it turns an error message into a probe for what exists. The
response names the column and the referenced table; nothing else. The constraint name is
withheld too — schema shape the caller has no use for.

**It does not stop logging at ERROR.** Our own code can insert a bad reference as easily
as a client can send one, and a 4xx that goes unlogged would hide that class of bug
completely. The status code answers the client; the log entry keeps the server honest.
`test_a_foreign_key_violation_is_still_logged_as_an_error` pins that, because it is the
half that quietly disappears when someone later "tidies" the handler.
"""

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.errors import _foreign_key_target, register_exception_handlers

FK_MESSAGE = (
    'insert or update on table "yard_moves" violates foreign key constraint '
    '"fk_yard_moves_trailer_id"\n'
    'DETAIL:  Key (trailer_id)=(f728b4fa-4248-1e3a-8a5d-2f346baa9455) '
    'is not present in table "yard_trailers".'
)


class FakeFKError(Exception):
    pass


FakeFKError.__name__ = "ForeignKeyViolationError"


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    router = APIRouter()

    @router.post("/unknown-ref")
    async def _unknown_ref():
        inner = FakeFKError(FK_MESSAGE)
        try:
            raise inner
        except FakeFKError as exc:
            raise RuntimeError("(sqlalchemy.dialects.postgresql.asyncpg.Error)") from exc

    @router.post("/other-error")
    async def _other():
        raise RuntimeError("something entirely unrelated")

    app.include_router(router)
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_an_unknown_reference_is_reported_as_a_client_error(client: TestClient):
    response = client.post("/unknown-ref")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_the_message_names_the_column_and_table_but_not_the_value(client: TestClient):
    body = client.post("/unknown-ref").json()
    detail = body["detail"]

    assert "trailer_id" in detail
    assert "yard_trailers" in detail
    # The supplied key must not come back: on a tenant-scoped column it can be another
    # tenant's identifier, and an error that reflects input is a existence oracle.
    assert "f728b4fa" not in detail
    # Nor the constraint name — internal schema shape.
    assert "fk_yard_moves_trailer_id" not in detail


def test_a_foreign_key_violation_is_still_logged_as_an_error(client: TestClient):
    """The half that keeps a 4xx from hiding a server bug.

    Uses `structlog.testing.capture_logs` rather than `caplog` or `capfd`. caplog sees
    nothing, because structlog renders through its own processor chain; capfd works in
    isolation but not in the full suite, where another module has already reconfigured
    structlog's sink — so the test passed alone and failed together, which is the least
    useful state for a guard to be in. capture_logs intercepts at the processor level and
    does not care where output eventually goes.
    """
    import structlog

    with structlog.testing.capture_logs() as logs:
        client.post("/unknown-ref")

    events = [entry for entry in logs if entry.get("event") == "foreign_key_violation"]
    assert events, (
        "the response is now the caller's fault, but the CAUSE may not be — our own code "
        "can insert a bad reference. Without an ERROR log that class of bug becomes "
        "invisible the moment the status changed from 500. Logged events: "
        f"{[entry.get('event') for entry in logs]}"
    )
    assert events[0]["log_level"] == "error"
    assert events[0]["referenced_table"] == "yard_trailers", (
        "the log must carry enough to locate the write"
    )


def test_an_unrelated_failure_is_still_a_500(client: TestClient):
    response = client.post("/other-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


def test_the_detector_reads_the_column_and_table():
    target = _foreign_key_target(FakeFKError(FK_MESSAGE))
    assert target == {"column": "trailer_id", "table": "yard_trailers"}


def test_a_violation_without_a_parseable_detail_still_returns_a_safe_message(client):
    """Postgres does not always attach DETAIL — the handler must not depend on it."""
    target = _foreign_key_target(
        FakeFKError('violates foreign key constraint "fk_something"')
    )
    assert target == {"column": "", "table": ""}


def test_an_unrelated_exception_is_not_matched():
    assert _foreign_key_target(RuntimeError("no constraint here")) is None


def test_the_detector_terminates_on_a_cyclic_chain():
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__context__ = b
    b.__context__ = a

    assert _foreign_key_target(a) is None
