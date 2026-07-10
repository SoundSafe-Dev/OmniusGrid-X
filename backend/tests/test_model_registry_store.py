"""Unit tests for the cloud model registry artifact store.

Covers ``services/model_registry_store.py``: atomic write + SHA-256 checksum,
round-trip load, path-traversal rejection, and the signed download URL. Pure
unit tests — no database/container required.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services import model_registry_store as store
from app.services.model_registry_store import ModelArtifactStorageError
from app.utils.signed_urls import (
    PURPOSE_AGENT_RELEASE,
    PURPOSE_MODEL_ARTIFACT,
    SignedTokenError,
    decode_signed_download_token,
)


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_STORAGE_PATH", str(tmp_path))
    return tmp_path


class TestStoreModelArtifact:
    def test_store_writes_file_and_returns_checksum(self, store_dir):
        org = uuid4()
        data = b"fake-torchscript-bytes"
        result = store.store_model_artifact(org, "anomaly", "v1", data)

        assert result.storage_key == f"{org}/anomaly/v1.pt"
        assert result.checksum_sha256 == hashlib.sha256(data).hexdigest()
        assert result.size_bytes == len(data)
        written = store_dir / str(org) / "anomaly" / "v1.pt"
        assert written.read_bytes() == data

    def test_load_round_trips(self, store_dir):
        org = uuid4()
        data = b"abc123"
        result = store.store_model_artifact(org, "oee_forecast", "v2", data)
        assert store.load_model_artifact(result.storage_key) == data

    def test_overwrite_is_atomic_and_leaves_no_temp(self, store_dir):
        org = uuid4()
        store.store_model_artifact(org, "anomaly", "v1", b"first")
        result = store.store_model_artifact(org, "anomaly", "v1", b"second-longer")

        assert store.load_model_artifact(result.storage_key) == b"second-longer"
        leftovers = list((store_dir / str(org) / "anomaly").glob(".*tmp*"))
        assert leftovers == []

    def test_empty_artifact_rejected(self, store_dir):
        with pytest.raises(ModelArtifactStorageError):
            store.store_model_artifact(uuid4(), "anomaly", "v1", b"")

    @pytest.mark.parametrize("bad", ["../evil", "a/b", "..", ".hidden", "na me", ""])
    def test_unsafe_name_rejected(self, store_dir, bad):
        with pytest.raises(ModelArtifactStorageError):
            store.store_model_artifact(uuid4(), bad, "v1", b"x")

    @pytest.mark.parametrize("bad", ["../evil", "a/b", "..", ".hidden"])
    def test_unsafe_version_rejected(self, store_dir, bad):
        with pytest.raises(ModelArtifactStorageError):
            store.store_model_artifact(uuid4(), "anomaly", bad, b"x")


class TestArtifactExists:
    def test_exists_reflects_store(self, store_dir):
        org = uuid4()
        assert store.artifact_exists(f"{org}/anomaly/v1.pt") is False
        result = store.store_model_artifact(org, "anomaly", "v1", b"x")
        assert store.artifact_exists(result.storage_key) is True


class TestIssueModelArtifactUrl:
    def test_url_round_trips_to_signed_token(self, store_dir):
        org = uuid4()
        model_id = uuid4()
        url, expires_at = store.issue_model_artifact_url(model_id, org)

        assert f"/api/v1/models/{model_id}/download" in url
        token = parse_qs(urlsplit(url).query)["token"][0]
        verified = decode_signed_download_token(token, PURPOSE_MODEL_ARTIFACT)
        assert verified.job_id == model_id
        assert verified.organization_id == org
        assert verified.purpose == PURPOSE_MODEL_ARTIFACT
        assert expires_at > datetime.now(timezone.utc)

    def test_token_rejected_for_wrong_purpose(self, store_dir):
        url, _ = store.issue_model_artifact_url(uuid4(), uuid4())
        token = parse_qs(urlsplit(url).query)["token"][0]
        with pytest.raises(SignedTokenError):
            decode_signed_download_token(token, PURPOSE_AGENT_RELEASE)
