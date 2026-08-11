"""OTA artifacts cannot be written outside their storage root (FS-655).

165 lines, **four production importers, and no test naming the module** — in the path that
writes the binary a fleet of edge agents will download, verify and execute.

WHY THE CONTAINMENT IS THE THING TO PIN. `resolve_bundle_path` builds a path from an
organisation id and a release id and then checks the result is still under the root. That
check is the only thing between a caller and an arbitrary write: both ids arrive as UUIDs
today, so the traversal is not reachable through the current callers — which is exactly what
makes it worth a test rather than a comment. A future caller that passes a string, or a
`storage_key` read back from a database row somebody edited, meets this function and nothing
else.

`absolute_bundle_path` is the one with a real surface: it takes a **storage_key string**
straight from a database column, and `delete_release_artifact` passes it to `unlink`.

THE WRITE IS ATOMIC, and that is also asserted. An agent downloading a half-written bundle
fails its signature check — recoverable — but the release row would already claim a checksum
for bytes nobody wrote.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.agent_release_storage import (
    AgentReleaseStorageError,
    absolute_bundle_path,
    delete_release_artifact,
    ota_storage_root,
    resolve_bundle_path,
    store_release_artifact,
)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Point the storage root at a temp directory. Without this the tests write to
    `/var/lib/omniusgrid/ota`, which is the path that made `POST /fleet/releases` raise a
    PermissionError in the contract gate."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "OTA_STORAGE_PATH", str(tmp_path))
    return tmp_path


class TestThePathStaysUnderTheRoot:
    def test_a_normal_release_resolves_inside(self, storage):
        org, release = uuid4(), uuid4()
        absolute, key = resolve_bundle_path(org, release)
        assert absolute.is_relative_to(ota_storage_root())
        assert key == f"{org}/{release}.bundle"

    def test_only_the_two_known_suffixes_are_accepted(self, storage):
        """`.bundle` and `.whl` are what the OTA path ships. An open suffix is a way to
        write a `.py` or a `.service` file into a directory an agent reads."""
        with pytest.raises(AgentReleaseStorageError, match="suffix"):
            resolve_bundle_path(uuid4(), uuid4(), suffix=".sh")

    @pytest.mark.parametrize(
        "key",
        [
            "../../etc/cron.d/agent",
            "../outside.bundle",
            "org/../../escape.bundle",
        ],
    )
    def test_a_traversing_storage_key_is_refused(self, storage, key):
        """THE REACHABLE SURFACE. `storage_key` is a string read back from a database
        column, not a UUID — and `delete_release_artifact` hands it to `unlink`. A key that
        climbs out of the root would delete a file the product does not own."""
        with pytest.raises(AgentReleaseStorageError, match="escapes storage root"):
            absolute_bundle_path(key)

    def test_an_absolute_key_cannot_replace_the_root(self, storage):
        with pytest.raises(AgentReleaseStorageError, match="escapes storage root"):
            absolute_bundle_path("/etc/passwd")

    def test_a_legitimate_key_resolves(self, storage):
        org, release = uuid4(), uuid4()
        assert absolute_bundle_path(f"{org}/{release}.bundle").is_relative_to(ota_storage_root())


class TestTheWriteIsAtomicAndDescribesItself:
    def test_it_writes_the_bytes_and_reports_their_checksum(self, storage, monkeypatch):
        monkeypatch.setattr(
            "app.services.agent_release_storage.sign_bundle", lambda _b: "sig"
        )
        payload = b"an agent wheel"
        stored = store_release_artifact(uuid4(), uuid4(), payload, suffix=".whl")
        written = (ota_storage_root() / stored.storage_key).read_bytes()
        assert written == payload
        assert stored.checksum_sha256 == hashlib.sha256(payload).hexdigest()
        assert stored.size_bytes == len(payload)

    def test_no_temp_file_is_left_behind(self, storage, monkeypatch):
        """The write goes to a temp file and is `os.replace`d into position, so an agent
        never sees a partial bundle. A leaked `.tmp` beside it would be collected by any
        directory listing and served as a release."""
        monkeypatch.setattr(
            "app.services.agent_release_storage.sign_bundle", lambda _b: "sig"
        )
        org = uuid4()
        store_release_artifact(org, uuid4(), b"x", suffix=".bundle")
        leftovers = [p.name for p in (ota_storage_root() / str(org)).iterdir() if ".tmp" in p.name]
        assert leftovers == []

    def test_delete_is_idempotent(self, storage):
        """`delete_release_artifact` is the cleanup for an artifact whose metadata
        transaction failed. It runs when things have already gone wrong, so raising on an
        absent file would turn one failure into two."""
        org, release = uuid4(), uuid4()
        (ota_storage_root() / str(org)).mkdir(parents=True, exist_ok=True)
        delete_release_artifact(f"{org}/{release}.bundle")
        delete_release_artifact(f"{org}/{release}.bundle")
