"""S6 — resumable OTA (FS-758).

ACCEPTANCE, from the DDIL plan: *a 64 MB artifact completes across 5 forced disconnects, RSS
under 128 MB, resumed download byte-identical and signature-valid.*

WHAT IT REPLACES. Three download implementations, three different ways to fail:

  * `executor.py` and `model_executor.py`: `response.content` on an unbounded `get()`. The
    whole artifact in memory, **no size limit of any kind**, and a disconnect at 99% throws
    all of it away. The missing limit is a denial of service reachable by anyone who can
    influence a release URL, and it sits in FRONT of the signature check — the bytes are
    resident before anything has decided they are legitimate.
  * `agent_executor.py`: streamed with a cap, then accumulated into a `bytearray` and copied
    with `bytes(content)`. Two full copies resident, so 64 MB peaked at 128 MB on a device
    that may have 512 MB total. Also restarted from byte zero on any failure.

None could resume. On a link that drops every few minutes — which is the case where remote
update matters most, because nobody can drive to the site — a large artifact does not arrive
slowly. It never arrives, because no single attempt lives long enough to finish and every
attempt begins again at nothing.

The scenarios below serve the artifact from an in-process ASGI transport that drops the
connection at scripted byte offsets, so "five forced disconnects" is a fact about the run
rather than a description of one.
"""

from __future__ import annotations

import asyncio
import hashlib
import tracemalloc
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from opsgrid_agent.ota.download import (
    DownloadFailed,
    ResumableDownload,
    sha256_of_file,
)

pytestmark = pytest.mark.ddil

MEGABYTE = 1024 * 1024


def _artifact(size: int, seed: int = 7) -> bytes:
    """Deterministic pseudo-random bytes — compressible content would let a broken
    resume produce a plausible file, and random-looking content makes a splice obvious."""
    out = bytearray()
    value = seed
    while len(out) < size:
        value = (value * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        out.extend(value.to_bytes(8, "little"))
    return bytes(out[:size])


class _FlakyServer:
    """Serves `payload`, honouring Range, and cutting the connection at scripted points."""

    def __init__(self, payload: bytes, *, drop_after: list[int] | None = None,
                 ignore_range: bool = False, reject_range: bool = False,
                 wrong_range_start: bool = False, no_content_length: bool = False,
                 end_early_at: list[int] | None = None):
        self.payload = payload
        self.drop_after = list(drop_after or [])
        self.ignore_range = ignore_range
        self.reject_range = reject_range
        self.wrong_range_start = wrong_range_start
        self.no_content_length = no_content_length
        #: Ends the body CLEANLY at these offsets — no exception, just fewer bytes than
        #: `content-length` promised. Distinct from `drop_after`, which raises: a server
        #: that closes politely short is the case the completion check exists for, and a
        #: mutation proved no scenario reached it while one claimed to.
        self.end_early_at = list(end_early_at or [])
        self.requests: list[str] = []
        self.drops = 0
        self.short_endings = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        range_header = request.headers.get("range", "")
        self.requests.append(range_header)
        start = 0
        if range_header and not self.ignore_range:
            if self.reject_range:
                return httpx.Response(416)
            start = int(range_header.split("=")[1].split("-")[0])
            if start >= len(self.payload):
                return httpx.Response(416)

        # A MEMORYVIEW, NOT A SLICE. `self.payload[start:]` copies the remainder — 44 MB
        # for the resumed leg of the 64 MB scenario — and that copy is allocated by the
        # TEST SERVER, inside the window the memory assertion is measuring. It read as
        # 47 MB of peak and looked like the downloader materialising the artifact. The
        # instrument was measuring the instrument.
        body = memoryview(self.payload)[start:]
        cut = self.drop_after.pop(0) if self.drop_after else None
        stop = self.end_early_at.pop(0) if self.end_early_at else None

        server = self

        async def stream():
            sent = 0
            step = 64 * 1024
            for index in range(0, len(body), step):
                piece = body[index:index + step]
                if stop is not None and sent + len(piece) > stop:
                    yield bytes(piece[: max(0, stop - sent)])
                    server.short_endings += 1
                    return                      # clean end of stream, body incomplete
                if cut is not None and sent + len(piece) > cut:
                    yield bytes(piece[: max(0, cut - sent)])
                    server.drops += 1
                    raise httpx.ReadError("connection reset by peer")
                sent += len(piece)
                yield bytes(piece)

        headers = {}
        if not self.no_content_length:
            headers["content-length"] = str(len(body))
        if start and not self.ignore_range:
            reported = start + 1 if self.wrong_range_start else start
            headers["content-range"] = (
                f"bytes {reported}-{len(self.payload) - 1}/{len(self.payload)}"
            )
            return httpx.Response(206, headers=headers, content=stream())
        return httpx.Response(200, headers=headers, content=stream())


def _download(url: str, destination: Path, server: _FlakyServer, **kwargs):
    transport = httpx.MockTransport(server)
    return ResumableDownload(
        url,
        destination,
        max_bytes=kwargs.pop("max_bytes", 256 * MEGABYTE),
        client_factory=lambda: httpx.AsyncClient(transport=transport),
        sleep=_no_wait,
        **kwargs,
    )


async def _no_wait(_delay):
    return None


class TestSixtyFourMegabytesAcrossFiveDisconnects:
    """The headline acceptance criterion, run as stated."""

    def test_it_completes_and_the_bytes_are_identical(self):
        payload = _artifact(64 * MEGABYTE)
        expected = hashlib.sha256(payload).hexdigest()
        # Five cuts, at roughly 8, 20, 33, 45 and 57 MB of remaining body.
        server = _FlakyServer(payload, drop_after=[8 * MEGABYTE, 12 * MEGABYTE,
                                                   13 * MEGABYTE, 12 * MEGABYTE,
                                                   12 * MEGABYTE])

        with TemporaryDirectory() as directory:
            target = Path(directory) / "agent.whl"
            download = _download("https://releases/agent.whl", target, server)
            path = asyncio.run(download.fetch())

            assert server.drops == 5, f"the link dropped {server.drops} times, not 5"
            assert path.stat().st_size == len(payload), (
                f"{path.stat().st_size} bytes on disk, expected {len(payload)}"
            )
            assert sha256_of_file(path) == expected, (
                "the reassembled artifact does not match. A resume that splices overlapping "
                "or missing ranges produces exactly this, and the checksum is the only "
                "thing between it and an installed corrupt wheel."
            )
            assert len(download.resumed_from) == 5, download.resumed_from
            assert download.resumed_from == sorted(download.resumed_from), (
                f"the resume offsets did not advance: {download.resumed_from} — each "
                "attempt is starting further back than the last"
            )

    def test_it_does_not_hold_the_artifact_in_memory(self):
        """Under 128 MB for a 64 MB artifact — measured with `tracemalloc`, not `ru_maxrss`.

        WRITTEN WITH ru_maxrss FIRST, AND THAT WAS WRONG. `ru_maxrss` is a high-water mark
        for the whole process and never decreases, so once any earlier test in the run has
        allocated 64 MB the delta reads zero and the assertion passes while measuring
        nothing. It is the vacuity failure this repository keeps finding, in a test written
        to prevent a vacuity failure.

        `tracemalloc` reports the peak since it was reset, and it sees exactly what matters
        here: the Python `bytes` objects. The old path held a `bytearray` plus a `bytes`
        copy — 128 MB resident for this artifact before staging even began.
        """
        payload = _artifact(64 * MEGABYTE)
        server = _FlakyServer(payload, drop_after=[20 * MEGABYTE])

        with TemporaryDirectory() as directory:
            target = Path(directory) / "agent.whl"
            tracemalloc.start()
            tracemalloc.reset_peak()
            try:
                asyncio.run(_download("https://releases/agent.whl", target, server).fetch())
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()

            peak_mb = peak / MEGABYTE
            assert peak_mb < 32, (
                f"peak Python allocation was {peak_mb:.0f} MB downloading a 64 MB "
                "artifact; the download is materialising it rather than streaming it"
            )

    def test_progress_survives_the_process_dying(self):
        """Resume is on DISK, not in the object. An agent that is killed mid-update — a
        restart, a power cut, an OOM — must not begin again from zero."""
        payload = _artifact(16 * MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "agent.whl"

            first = _download("https://releases/agent.whl", target,
                              _FlakyServer(payload, drop_after=[6 * MEGABYTE]),
                              max_attempts=1)
            with pytest.raises(DownloadFailed):
                asyncio.run(first.fetch())
            partial = first.bytes_on_disk()
            assert 0 < partial < len(payload), partial

            # A completely new object, as after a restart.
            server = _FlakyServer(payload)
            second = _download("https://releases/agent.whl", target, server)
            path = asyncio.run(second.fetch())

            assert second.resumed_from == [partial], (
                f"the new attempt resumed from {second.resumed_from}, not {partial} — "
                "the partial file on disk was ignored"
            )
            assert sha256_of_file(path) == hashlib.sha256(payload).hexdigest()


class TestTheServerMayNotCooperate:
    """A resume that trusts the response is worse than no resume at all."""

    def test_a_server_that_ignores_range_restarts_instead_of_splicing(self):
        """The dangerous case. A proxy that does not support Range answers 200 with the
        whole body; appending it to a partial file produces a corrupt artifact whose only
        symptom is a checksum failure several minutes later."""
        payload = _artifact(4 * MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "a.bin"
            first = _download("https://releases/a.bin", target,
                              _FlakyServer(payload, drop_after=[MEGABYTE]),
                              max_attempts=1)
            with pytest.raises(DownloadFailed):
                asyncio.run(first.fetch())
            assert first.bytes_on_disk() > 0

            server = _FlakyServer(payload, ignore_range=True)
            path = asyncio.run(_download("https://releases/a.bin", target, server).fetch())

            assert path.stat().st_size == len(payload), (
                f"{path.stat().st_size} bytes for a {len(payload)} byte artifact — the "
                "ignored range was appended to the partial file"
            )
            assert sha256_of_file(path) == hashlib.sha256(payload).hexdigest()

    def test_a_206_that_resumes_from_the_wrong_offset_is_refused(self):
        payload = _artifact(4 * MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "a.bin"
            first = _download("https://releases/a.bin", target,
                              _FlakyServer(payload, drop_after=[MEGABYTE]),
                              max_attempts=1)
            with pytest.raises(DownloadFailed):
                asyncio.run(first.fetch())

            server = _FlakyServer(payload, wrong_range_start=True)
            with pytest.raises(DownloadFailed, match="appending would corrupt"):
                asyncio.run(_download("https://releases/a.bin", target, server,
                                      max_attempts=2).fetch())

    def test_a_416_discards_the_stale_partial_and_starts_over(self):
        """A `.part` left behind by a DIFFERENT release is longer than the new artifact.
        Treating 416 as "already complete" would install the wrong file."""
        payload = _artifact(2 * MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "a.bin"
            stale = target.with_name(target.name + ".part")
            stale.write_bytes(_artifact(3 * MEGABYTE, seed=99))

            server = _FlakyServer(payload, reject_range=True)
            path = asyncio.run(_download("https://releases/a.bin", target, server).fetch())

            assert sha256_of_file(path) == hashlib.sha256(payload).hexdigest(), (
                "the stale partial file was accepted as the new artifact"
            )

    def test_a_stream_that_ends_politely_short_is_not_taken_for_complete(self):
        """A body that ends CLEANLY before its declared length — no exception, the
        connection simply closes — is the case the completion check exists for.

        Written first with `drop_after`, which raises, so the exception path handled it and
        the completion check was never reached. A mutation replacing `written >= total`
        with `True` survived while this test passed, which is what surfaced it: the
        scenario named the behaviour and exercised a different one.
        """
        payload = _artifact(2 * MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "a.bin"
            server = _FlakyServer(payload, end_early_at=[MEGABYTE])
            path = asyncio.run(_download("https://releases/a.bin", target, server).fetch())

            assert server.short_endings == 1, "the server did not truncate; setup is wrong"
            assert path.stat().st_size == len(payload), (
                f"{path.stat().st_size} of {len(payload)} bytes were accepted as a "
                "complete download. The checksum would catch it — after the download has "
                "already reported success, and after the retry budget is spent."
            )
            assert sha256_of_file(path) == hashlib.sha256(payload).hexdigest()


class TestTheSizeLimitThatWasNotThere:
    def test_an_oversized_artifact_is_refused_before_it_is_resident(self):
        payload = _artifact(8 * MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "a.bin"
            server = _FlakyServer(payload)
            with pytest.raises(DownloadFailed, match="over the"):
                asyncio.run(_download("https://releases/a.bin", target, server,
                                      max_bytes=MEGABYTE).fetch())
            assert not target.exists()

    def test_a_body_that_lies_about_its_length_is_still_capped(self):
        """The declared length is a claim. A server that sends more than it promised — or
        promises nothing at all — must still be stopped, or the check is advisory."""
        payload = _artifact(8 * MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "a.bin"
            server = _FlakyServer(payload, no_content_length=True)
            with pytest.raises(DownloadFailed, match="exceeded"):
                asyncio.run(_download("https://releases/a.bin", target, server,
                                      max_bytes=2 * MEGABYTE).fetch())

    def test_a_download_inside_the_limit_still_succeeds(self):
        """The control case: a cap that refuses everything would pass both tests above."""
        payload = _artifact(MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "a.bin"
            path = asyncio.run(_download("https://releases/a.bin", target,
                                         _FlakyServer(payload),
                                         max_bytes=4 * MEGABYTE).fetch())
            assert sha256_of_file(path) == hashlib.sha256(payload).hexdigest()


class TestGivingUp:
    def test_it_stops_after_the_attempt_limit_rather_than_retrying_forever(self):
        payload = _artifact(MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "a.bin"
            server = _FlakyServer(payload, drop_after=[1024] * 20)
            download = _download("https://releases/a.bin", target, server, max_attempts=4)
            with pytest.raises(DownloadFailed, match="gave up after 4"):
                asyncio.run(download.fetch())
            assert download.attempts == 4

    def test_the_partial_file_is_kept_so_the_next_run_can_continue(self):
        payload = _artifact(4 * MEGABYTE)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "a.bin"
            server = _FlakyServer(payload, drop_after=[MEGABYTE] * 10)
            download = _download("https://releases/a.bin", target, server, max_attempts=3)
            with pytest.raises(DownloadFailed):
                asyncio.run(download.fetch())
            assert download.bytes_on_disk() > 0, (
                "giving up deleted the partial file, so the next run starts from zero and "
                "a link that never stays up for one full artifact never delivers one"
            )


class TestHashingDoesNotUndoTheStreaming:
    def test_the_digest_does_not_load_the_whole_file(self):
        """`sha256_of_file` reads in chunks. Swapping that for `handle.read()` produces an
        identical digest, so no assertion about the RESULT can tell the difference — and a
        512 MB model artifact read whole to hash it defeats the entire point of streaming
        it to disk in the first place."""
        with TemporaryDirectory() as directory:
            target = Path(directory) / "big.bin"
            with open(target, "wb") as handle:
                block = _artifact(4 * MEGABYTE)
                for _ in range(16):                      # 64 MB
                    handle.write(block)

            tracemalloc.start()
            tracemalloc.reset_peak()
            try:
                digest = sha256_of_file(target)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()

            peak_mb = peak / MEGABYTE
            assert len(digest) == 64
            assert peak_mb < 8, (
                f"hashing a 64 MB file peaked at {peak_mb:.0f} MB of Python allocation; it "
                "is being read whole rather than in chunks, which undoes the streaming "
                "that the rest of this file exists to establish"
            )
