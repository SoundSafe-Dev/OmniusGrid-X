"""Downloading a release over a link that keeps dropping (FS-758).

THREE IMPLEMENTATIONS, THREE FAILURE MODES, none of them survivable on a DDIL link.

`executor.py` and `model_executor.py` both did this:

    response = await client.get(bundle_url)
    return response.content

The whole artifact in memory in one call, **with no size limit at all** — a release URL that
serves a gigabyte exhausts the gateway's memory, which is a denial of service reachable by
anyone who can influence a release record. And a disconnect at 99% discards everything.

`agent_executor.py` streamed and enforced a cap, which is better, and still accumulated into
a `bytearray` and then copied it with `bytes(content)` — two full copies resident at once, so
a 64 MB wheel peaked at 128 MB on a device that may have 512 MB total. It also restarted from
byte zero on any failure.

None of the three could resume. On a link that drops every few minutes — the DDIL case, and
the case where remote update matters most because nobody can drive to the site — a large
artifact is not slow to arrive. It never arrives, because every attempt starts again from
nothing and the link does not stay up long enough for any single attempt to finish.

WHAT THIS DOES. Streams to a `.part` file beside the destination, and on retry asks for
`Range: bytes=<already-have>-` and appends. Memory is one chunk, not one artifact, so the
size of the release stops being a memory question. Progress survives the process dying,
because the partial file is on disk and the next attempt reads its length.

THE RANGE RESPONSE IS CHECKED, NOT ASSUMED. A server that ignores `Range` answers 200 with
the whole body from byte zero; appending that to a partial file produces a corrupt artifact
whose checksum fails, which is a confusing way to discover a proxy does not support ranges.
A 200 to a ranged request therefore truncates and starts over, and a 206 must carry a
`Content-Range` whose start actually matches what we have.

WHAT IS STILL IN MEMORY ONCE. Checksum verification streams the file, but Ed25519 signature
verification needs the whole message — `cryptography` exposes no incremental API — so the
artifact is read into memory once for that step. Signing the digest rather than the artifact
would remove even that; it changes the release-signing contract, so it is registered for the
OTA lane rather than changed here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Optional

import httpx
import structlog

from ..resilience import ReconnectPolicy

logger = structlog.get_logger()

#: One mebibyte. Large enough that a 64 MB artifact is 64 reads rather than 64,000, small
#: enough that a chunk in flight is not itself a memory concern on a constrained gateway.
CHUNK_BYTES = 1024 * 1024


class DownloadFailed(Exception):
    """Raised when a download cannot be completed after exhausting the retry policy."""


class ResumableDownload:
    """Fetch a URL to a file, resuming from whatever is already on disk."""

    def __init__(
        self,
        url: str,
        destination: Path,
        *,
        max_bytes: int,
        policy: Optional[ReconnectPolicy] = None,
        max_attempts: int = 8,
        chunk_bytes: int = CHUNK_BYTES,
        timeout: float = 60.0,
        client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
        sleep: Optional[Callable] = None,
    ) -> None:
        self.url = url
        self.destination = Path(destination)
        self.part_path = self.destination.with_name(self.destination.name + ".part")
        self.max_bytes = max_bytes
        self.policy = policy or ReconnectPolicy()
        self.max_attempts = max_attempts
        self.chunk_bytes = chunk_bytes
        self.timeout = timeout
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=self.timeout)
        )
        if sleep is None:
            import asyncio

            sleep = asyncio.sleep
        self._sleep = sleep
        #: How many attempts it actually took, and how many of those resumed rather than
        #: started over. Read by the scenarios; also the honest answer to "did resume
        #: actually happen or did the link simply hold?"
        self.attempts = 0
        self.resumed_from: list[int] = []

    def bytes_on_disk(self) -> int:
        return self.part_path.stat().st_size if self.part_path.exists() else 0

    async def fetch(self) -> Path:
        """Download to `destination`, resuming across failures. Returns the path."""
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        backoff, breaker = self.policy.instruments("ota-download")
        last_error: Optional[Exception] = None

        while self.attempts < self.max_attempts:
            if not breaker.allow():
                # The breaker is open. Waiting it out here rather than failing keeps a
                # long outage recoverable — the partial file is the whole point.
                await self._sleep(max(breaker.time_until_retry(), self.policy.initial_delay))
                continue

            self.attempts += 1
            offset = self.bytes_on_disk()
            try:
                complete = await self._attempt(offset)
            except DownloadFailed:
                raise
            except Exception as exc:  # httpx errors, OSError, and anything a proxy invents
                last_error = exc
                breaker.record_failure()
                delay = backoff.next_delay()
                logger.warning(
                    "ota_download_interrupted",
                    url=self.url,
                    have_bytes=self.bytes_on_disk(),
                    attempt=self.attempts,
                    retry_in_seconds=round(delay, 1),
                    error=str(exc),
                )
                await self._sleep(delay)
                continue

            if complete:
                breaker.record_success()
                self.part_path.replace(self.destination)
                logger.info(
                    "ota_download_complete",
                    url=self.url,
                    bytes=self.destination.stat().st_size,
                    attempts=self.attempts,
                    resumed_from=self.resumed_from,
                )
                return self.destination

            # A clean end of stream that did not reach the declared length. Treated as an
            # interruption, not a success — a truncated artifact that passes for complete
            # is the failure that a checksum catches far too late.
            breaker.record_failure()
            await self._sleep(backoff.next_delay())

        raise DownloadFailed(
            f"gave up after {self.attempts} attempts with "
            f"{self.bytes_on_disk()} bytes on disk"
            + (f": {last_error}" if last_error else "")
        )

    async def _attempt(self, offset: int) -> bool:
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        async with self._client_factory() as client:
            async with client.stream("GET", self.url, headers=headers) as response:
                if offset and response.status_code == 416:
                    # Range not satisfiable: what we have is at least as long as the
                    # resource. Either it is complete, or the partial file is stale from a
                    # different release. Both are resolved by starting over — the checksum
                    # is what decides correctness, and a stale part file must never be
                    # allowed to masquerade as a finished download.
                    logger.warning(
                        "ota_download_range_rejected",
                        have_bytes=offset,
                        note="discarding the partial file and restarting",
                    )
                    self.part_path.unlink(missing_ok=True)
                    return False

                response.raise_for_status()

                append = offset > 0
                if offset:
                    if response.status_code == 200:
                        # The server ignored the range and is sending from byte zero.
                        # Appending would splice two overlapping copies together and
                        # produce a corrupt artifact whose only symptom is a checksum
                        # mismatch several minutes later.
                        logger.warning(
                            "ota_download_range_ignored",
                            status=response.status_code,
                            note="server sent the whole body; restarting from zero",
                        )
                        append = False
                        offset = 0
                    else:
                        self._assert_range_matches(response, offset)
                        self.resumed_from.append(offset)

                total = self._declared_total(response, offset)
                if total is not None and total > self.max_bytes:
                    raise DownloadFailed(
                        f"artifact is {total} bytes, over the {self.max_bytes} limit"
                    )

                written = offset
                with open(self.part_path, "ab" if append else "wb") as handle:
                    async for chunk in response.aiter_bytes(self.chunk_bytes):
                        written += len(chunk)
                        if written > self.max_bytes:
                            handle.close()
                            self.part_path.unlink(missing_ok=True)
                            raise DownloadFailed(
                                f"artifact exceeded the {self.max_bytes} byte limit"
                            )
                        handle.write(chunk)

                if total is not None:
                    return written >= total
                # No length declared — chunked transfer. A clean end of stream is all the
                # completion signal there is; the checksum is the real verdict.
                return True

    @staticmethod
    def _assert_range_matches(response: httpx.Response, offset: int) -> None:
        content_range = response.headers.get("content-range", "")
        # "bytes 1024-2047/2048"
        try:
            start = int(content_range.split()[1].split("-")[0])
        except (IndexError, ValueError):
            raise DownloadFailed(
                f"206 response with an unparseable Content-Range: {content_range!r}"
            )
        if start != offset:
            raise DownloadFailed(
                f"server resumed at byte {start}, we have {offset} — appending would "
                "corrupt the artifact"
            )

    @staticmethod
    def _declared_total(response: httpx.Response, offset: int) -> Optional[int]:
        content_range = response.headers.get("content-range")
        if content_range and "/" in content_range:
            total = content_range.rsplit("/", 1)[1].strip()
            if total.isdigit():
                return int(total)
        length = response.headers.get("content-length")
        if length and length.isdigit():
            return offset + int(length) if response.status_code == 206 else int(length)
        return None


def sha256_of_file(path: Path, *, chunk_bytes: int = CHUNK_BYTES) -> str:
    """Digest a file without holding it in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
