import io
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.datastructures import UploadFile

from app.api.agent_releases import create_agent_release, router
from app.core.config import settings
from app.services.agent_release_storage import absolute_bundle_path
from app.services.agent_signing import public_key_to_base64, verify_bundle_signature


class _Result:
    @staticmethod
    def scalar_one_or_none():
        return None


class _FakeSession:
    def __init__(self):
        self.added = []

    async def execute(self, _query):
        return _Result()

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def refresh(self, _value):
        return None


def _wheel(version: str) -> bytes:
    output = io.BytesIO()
    dist_info = f"opsgrid_agent-{version}.dist-info"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "opsgrid_agent/__init__.py",
            f'__version__ = "{version}"\n',
        )
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\n"
            "Name: opsgrid-agent\n"
            f"Version: {version}\n\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
    return output.getvalue()


@pytest.mark.asyncio
async def test_agent_release_handler_stores_and_signs_validated_wheel(
    tmp_path,
    monkeypatch,
):
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "signing.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(settings, "OTA_SIGNING_PRIVATE_KEY_PATH", str(private_path))
    monkeypatch.setattr(
        settings,
        "OTA_SIGNING_PUBLIC_KEY",
        public_key_to_base64(private_key.public_key()),
    )
    monkeypatch.setattr(settings, "OTA_STORAGE_PATH", str(tmp_path / "ota"))
    monkeypatch.setattr(settings, "EXPORT_PUBLIC_BASE_URL", "https://api.example.test")

    wheel = _wheel("2.0.0")
    upload = UploadFile(
        filename="opsgrid_agent-2.0.0-py3-none-any.whl",
        file=io.BytesIO(wheel),
    )
    session = _FakeSession()
    org_id = uuid4()
    user_id = uuid4()

    response = await create_agent_release.__wrapped__(
        request=None,
        artifact=upload,
        version="2.0.0",
        channel="stable",
        release_notes="process update",
        minimum_bootstrap_version="1.0.0",
        current_user=SimpleNamespace(id=user_id),
        org_id=org_id,
        db=session,
    )

    assert response.artifact_type == "agent"
    assert response.artifact_format == "wheel"
    assert response.package_name == "opsgrid-agent"
    assert response.minimum_bootstrap_version == "1.0.0"
    assert response.artifact_url.startswith("https://api.example.test/")
    release = session.added[0]
    stored = absolute_bundle_path(release.bundle_storage_key).read_bytes()
    assert stored == wheel
    assert verify_bundle_signature(
        stored,
        response.signature_ed25519,
        settings.OTA_SIGNING_PUBLIC_KEY,
    )

    route = next(route for route in router.routes if route.path == "/releases/agent")
    assert route.methods == {"POST"}
