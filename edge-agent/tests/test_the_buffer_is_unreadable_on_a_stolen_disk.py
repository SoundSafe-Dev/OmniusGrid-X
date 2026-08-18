"""Buffered payloads are unreadable without the key (FS-749).

THE SCENARIO, because "encryption at rest" means nothing without one. An edge gateway holds
up to 24 hours of readings in a local SQLite buffer — by design, and in a real DDIL outage
that backlog is the entire operational picture of the site. The device sits on a plant floor,
in a vehicle, or at a remote site, and it can be stolen, decommissioned without sanitisation,
returned as an RMA unit, or captured.

It was plaintext. `strings buffer.db` returned the telemetry.

WHAT THESE TESTS ASSERT, and the first one is the whole point: the ciphertext on disk does
not contain the plaintext. Everything else — round-tripping, legacy pass-through — is
satisfied by a cipher that returns its input, so without a test that reads the raw file this
file would pass over an encryption feature that encrypts nothing.

WHAT IS DELIBERATELY NOT CLAIMED. This defends the disk, not the running process: an
attacker with code execution reads the key file exactly as the agent does. And metadata
columns (`asset_id`, `timestamp_edge`, `topic`) stay in the clear because the buffer orders
and prunes by them — encrypting those would mean decrypting every row to sort it. Both
limits are asserted below rather than left to be discovered, so nobody reads more into the
control than it provides.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from opsgrid_agent.buffer.encryption import (
    BufferCipher,
    BufferEncryptionUnavailable,
)
from opsgrid_agent.buffer.store_forward import StoreForwardBuffer

SECRET_READING = "9911-COMPRESSOR-SERIAL-CUI"


def _buffer(directory: str, cipher: BufferCipher) -> StoreForwardBuffer:
    return StoreForwardBuffer(
        buffer_path=str(Path(directory) / "buffer.db"), cipher=cipher
    )


def _store(buffer: StoreForwardBuffer, value: str = SECRET_READING) -> None:
    asyncio.run(
        buffer.store(
            timestamp_edge=datetime.now(timezone.utc),
            asset_id="asset-1",
            topic="telemetry",
            payload={"serial": value, "temp": 81.4},
            sequence_num=1,
        )
    )


def _raw_bytes(directory: str) -> bytes:
    """Every file a stolen device would carry — `.db`, `-wal` and `-shm` together.

    READING ONLY `buffer.db` MADE THE HEADLINE TEST PASS FOR THE WRONG REASON. The buffer
    runs `PRAGMA journal_mode=WAL`, so a freshly written row lives in the `-wal` sidecar
    until a checkpoint: the main file genuinely does not contain the plaintext yet, and the
    "ciphertext is unreadable" assertion held whether or not anything was encrypted. The
    control case below is what exposed it — it asserts the UNencrypted reading IS findable,
    and it failed.

    A thief takes the directory, not one file. This reads what they would have."""
    return b"".join(
        path.read_bytes() for path in sorted(Path(directory).iterdir()) if path.is_file()
    )


class TheDiskDoesNotHoldThePlaintext(unittest.TestCase):
    def test_a_stolen_database_does_not_contain_the_reading(self):
        """THE ASSERTION THIS FILE EXISTS FOR. Every other test here passes for a cipher
        that returns its input unchanged."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, BufferCipher(b"device-secret-material"))
            _store(buffer)
            raw = _raw_bytes(directory)
            self.assertNotIn(SECRET_READING.encode(), raw,
                             "the reading is recoverable from the database file")
            self.assertNotIn(b"81.4", raw, "the measured value is on disk in the clear")

    def test_without_encryption_it_plainly_is_readable(self):
        """The control case. If this ever fails, the test above is passing for some reason
        other than encryption and proves nothing."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, BufferCipher(None, required=False))
            _store(buffer)
            self.assertIn(SECRET_READING.encode(), _raw_bytes(directory))

    def test_the_agent_can_still_read_its_own_buffer(self):
        with TemporaryDirectory() as directory:
            cipher = BufferCipher(b"device-secret-material")
            buffer = _buffer(directory, cipher)
            _store(buffer)
            pending = asyncio.run(buffer.get_pending_messages())
            self.assertEqual(len(pending), 1)
            self.assertEqual(json.loads(pending[0].payload)["serial"], SECRET_READING)

    def test_another_devices_key_cannot_read_it(self):
        with TemporaryDirectory() as directory:
            _store(_buffer(directory, BufferCipher(b"device-A-secret")))
            other = _buffer(directory, BufferCipher(b"device-B-secret"))
            with self.assertRaises(BufferEncryptionUnavailable):
                asyncio.run(other.get_pending_messages())


class TheMigrationDoesNotStrandExistingBacklogs(unittest.TestCase):
    """Every deployed device already has a buffer of plaintext rows. Refusing them would
    turn a security improvement into data loss for data that is already written."""

    def test_plaintext_rows_written_before_the_upgrade_still_drain(self):
        with TemporaryDirectory() as directory:
            _store(_buffer(directory, BufferCipher(None, required=False)))
            upgraded = _buffer(directory, BufferCipher(b"device-secret-material"))
            pending = asyncio.run(upgraded.get_pending_messages())
            self.assertEqual(len(pending), 1)
            self.assertEqual(json.loads(pending[0].payload)["serial"], SECRET_READING)

    def test_a_mixed_buffer_drains_completely(self):
        with TemporaryDirectory() as directory:
            _store(_buffer(directory, BufferCipher(None, required=False)), "legacy-row")
            _store(_buffer(directory, BufferCipher(b"k")), "encrypted-row")
            pending = asyncio.run(_buffer(directory, BufferCipher(b"k")).get_pending_messages())
            serials = {json.loads(m.payload)["serial"] for m in pending}
            self.assertEqual(serials, {"legacy-row", "encrypted-row"})

    def test_an_encrypted_row_with_no_key_is_loud_not_silent(self):
        """The operator must learn the backlog is UNREADABLE, not that it is empty —
        silently dropping it is the absence-as-success shape this codebase keeps closing."""
        with TemporaryDirectory() as directory:
            _store(_buffer(directory, BufferCipher(b"the-key")))
            keyless = _buffer(directory, BufferCipher(None, required=False))
            with self.assertRaises(BufferEncryptionUnavailable):
                asyncio.run(keyless.get_pending_messages())


class TheRequirementFailsClosed(unittest.TestCase):
    def test_required_without_a_key_refuses_to_start(self):
        with self.assertRaises(BufferEncryptionUnavailable):
            BufferCipher(None, required=True)

    def test_not_required_without_a_key_is_a_pass_through(self):
        cipher = BufferCipher(None, required=False)
        self.assertFalse(cipher.enabled)
        self.assertEqual(cipher.encrypt("x"), "x")


class TheLimitsAreStatedRatherThanImplied(unittest.TestCase):
    def test_metadata_stays_queryable_in_the_clear(self):
        """Not a defect — the buffer ORDERS and PRUNES by these columns, so encrypting them
        would mean decrypting every row to sort it. Pinned so the boundary of the control is
        a fact in a test rather than a sentence in a doc nobody reads."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, BufferCipher(b"device-secret-material"))
            _store(buffer)
            with sqlite3.connect(Path(directory) / "buffer.db") as conn:
                row = conn.execute(
                    "SELECT asset_id, topic FROM messages ORDER BY timestamp_edge"
                ).fetchone()
            self.assertEqual(row, ("asset-1", "telemetry"))

    def test_dead_lettered_rows_stay_encrypted(self):
        """The dead-letter move is INSERT...SELECT in SQL, so ciphertext travels as-is. A
        dead letter is the same CUI as a live one and must not be decrypted on the way."""
        with TemporaryDirectory() as directory:
            buffer = _buffer(directory, BufferCipher(b"device-secret-material"))
            _store(buffer)
            with sqlite3.connect(Path(directory) / "buffer.db") as conn:
                conn.execute("UPDATE messages SET retry_count = 99")
                conn.commit()
            asyncio.run(buffer.move_exhausted_to_dead_letter(max_retry=5))
            self.assertNotIn(SECRET_READING.encode(), _raw_bytes(directory))


if __name__ == "__main__":
    unittest.main()
