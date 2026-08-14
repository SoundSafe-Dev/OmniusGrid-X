"""Upload sizing: the Content-Length guard and the no-read size measurement.

Neither needs a database or an object store — the point of both pieces is that
they decide before any of that is touched.
"""

from __future__ import annotations

import io
import tempfile

import pytest
from fastapi import FastAPI, File, UploadFile
from httpx import ASGITransport, AsyncClient

from app.middleware.upload_limit import UploadLimitMiddleware
from app.services.document_store import stream_size


def _app(max_bytes: int) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        UploadLimitMiddleware, max_bytes=max_bytes, prefixes=("/guarded",)
    )

    @app.post("/guarded/ingest")
    async def guarded(file: UploadFile = File(...)):
        return {"read": len(await file.read())}

    @app.post("/unguarded/ingest")
    async def unguarded(file: UploadFile = File(...)):
        return {"read": len(await file.read())}

    return app


async def _post(app: FastAPI, path: str, payload: bytes):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, files={"file": ("f.txt", payload, "text/plain")})


async def test_oversized_upload_is_rejected_with_413():
    resp = await _post(_app(max_bytes=1024), "/guarded/ingest", b"x" * 200_000)

    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()


async def test_upload_within_the_limit_passes_through():
    payload = b"x" * 512
    resp = await _post(_app(max_bytes=1024), "/guarded/ingest", payload)

    assert resp.status_code == 200
    assert resp.json()["read"] == len(payload)


async def test_a_file_just_under_the_cap_is_not_rejected_for_its_envelope():
    """Multipart framing must not push a legal file over the limit."""
    payload = b"x" * 1024
    resp = await _post(_app(max_bytes=1024), "/guarded/ingest", payload)

    assert resp.status_code == 200, "envelope overhead was charged to the file"


async def test_unwatched_paths_are_untouched():
    resp = await _post(_app(max_bytes=1024), "/unguarded/ingest", b"x" * 200_000)

    assert resp.status_code == 200, "the guard is scoped to its prefixes only"


@pytest.mark.parametrize("size", [0, 1, 4096])
def test_stream_size_measures_without_consuming(size):
    stream = io.BytesIO(b"x" * size)

    assert stream_size(stream) == size
    assert stream.tell() == 0, "stream must be left rewound for the uploader"
    assert len(stream.read()) == size, "content must still be readable in full"


def test_stream_size_works_on_a_spooled_temp_file():
    """The real HTTP path hands over a SpooledTemporaryFile, not a BytesIO."""
    with tempfile.SpooledTemporaryFile(max_size=16) as spooled:
        spooled.write(b"y" * 128)  # forces the rollover to disk

        assert stream_size(spooled) == 128
        assert spooled.read() == b"y" * 128
