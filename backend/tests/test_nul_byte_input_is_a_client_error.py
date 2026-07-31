"""A NUL byte in the request is 400, not 500.

Postgres text columns cannot store 0x00. A string containing one can never be written,
however the endpoint is changed, so the request is unstorable rather than the server
broken — and a 500 tells the caller the opposite: retry, it might work. It also files a
non-incident into error tracking.

Nothing in this codebase generates a NUL byte, so when asyncpg raises

    CharacterNotInRepertoireError: invalid byte sequence for encoding "UTF8": 0x00

the byte came from the payload. That is the whole argument for attributing it to the
client, and it is why this mapping is safe while a broader one would not be.

WHAT IS DELIBERATELY *NOT* DONE HERE. The tempting version maps every asyncpg DataError
to 400. That would also relabel our own bad values — a wrong cast, a miscomputed id — as
the caller's fault, turning real server defects into 4xxs nobody investigates. The
handler matches one exception type whose cause is unambiguous; every other database
error stays a 500. These tests pin both halves.
"""

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.errors import _is_nul_byte_error, register_exception_handlers


class FakeAsyncpgError(Exception):
    """Stands in for asyncpg's CharacterNotInRepertoireError.

    The real one is matched by class NAME, so a stand-in with the same name exercises
    the same path without importing the driver into a unit test.
    """


FakeAsyncpgError.__name__ = "CharacterNotInRepertoireError"


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    router = APIRouter()

    @router.post("/nul")
    async def _nul():
        # The shape SQLAlchemy produces: the driver error wrapped twice.
        inner = FakeAsyncpgError('invalid byte sequence for encoding "UTF8": 0x00')
        try:
            raise inner
        except FakeAsyncpgError as exc:
            raise RuntimeError("(sqlalchemy.dialects.postgresql.asyncpg.Error)") from exc

    @router.post("/other-db-error")
    async def _other():
        inner = ValueError("invalid input for query argument $1: 'x' (bad numeric)")
        try:
            raise inner
        except ValueError as exc:
            raise RuntimeError("(sqlalchemy.dialects.postgresql.asyncpg.Error)") from exc

    app.include_router(router)
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_a_nul_byte_is_reported_as_a_client_error(client: TestClient):
    response = client.post("/nul")

    assert response.status_code == 400, (
        "a NUL byte cannot be stored by Postgres under any fix, so the request is "
        "malformed; 500 tells the caller to retry something that can never succeed"
    )
    body = response.json()
    assert body["error"]["code"] == "bad_request"
    assert "NUL" in body["detail"]


def test_every_other_database_error_stays_a_500(client: TestClient):
    """The half that keeps this mapping honest.

    If this ever returns 400, the handler has been widened into "blame the client for
    any database error", and real server defects will start hiding behind 4xxs.
    """
    response = client.post("/other-db-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


def test_the_detector_walks_the_exception_chain():
    """SQLAlchemy wraps the driver error twice; matching the outermost type never fires."""
    inner = FakeAsyncpgError('invalid byte sequence for encoding "UTF8": 0x00')
    middle = RuntimeError("AsyncAdapt_asyncpg_dbapi.Error")
    middle.__cause__ = inner
    outer = RuntimeError("sqlalchemy.exc.DBAPIError")
    outer.__cause__ = middle

    assert _is_nul_byte_error(outer)
    assert not _is_nul_byte_error(RuntimeError("something else entirely"))


def test_the_detector_terminates_on_a_cyclic_chain():
    """A self-referencing __context__ must not hang the error handler.

    An exception handler that loops forever turns a failed request into a hung worker,
    which is worse than the error it was reporting.
    """
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__context__ = b
    b.__context__ = a

    assert _is_nul_byte_error(a) is False


def test_the_message_form_is_matched_even_without_the_class_name():
    """Driver classes get renamed; the message is the backstop."""
    assert _is_nul_byte_error(
        RuntimeError('invalid byte sequence for encoding "UTF8": 0x00')
    )
    # ...but a different bad byte is not this error, and must not be mislabelled.
    assert not _is_nul_byte_error(
        RuntimeError('invalid byte sequence for encoding "UTF8": 0x9c')
    )
