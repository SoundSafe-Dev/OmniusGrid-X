import io
import zipfile

import pytest

from app.services.agent_artifact import AgentArtifactError, validate_agent_wheel


def _wheel(
    *,
    name: str = "opsgrid-agent",
    version: str = "2.0.0",
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    dist_info = f"opsgrid_agent-{version}.dist-info"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("opsgrid_agent/__init__.py", b"")
        archive.writestr(
            f"{dist_info}/METADATA",
            (
                "Metadata-Version: 2.1\n"
                f"Name: {name}\n"
                f"Version: {version}\n\n"
            ).encode(),
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            b"Wheel-Version: 1.0\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n\n",
        )
        for path, value in (extra_files or {}).items():
            archive.writestr(path, value)
    return output.getvalue()


def test_validates_pure_python_agent_wheel():
    artifact = _wheel()

    metadata = validate_agent_wheel(
        artifact,
        filename="opsgrid_agent-2.0.0-py3-none-any.whl",
        expected_version="2.0.0",
        max_uncompressed_bytes=1024 * 1024,
    )

    assert metadata.package_name == "opsgrid-agent"
    assert metadata.version == "2.0.0"
    assert metadata.size_bytes == len(artifact)


@pytest.mark.parametrize(
    ("artifact", "filename", "version", "message"),
    [
        (
            _wheel(name="other-package"),
            "opsgrid_agent-2.0.0-py3-none-any.whl",
            "2.0.0",
            "package must be opsgrid-agent",
        ),
        (
            _wheel(version="2.0.0"),
            "opsgrid_agent-2.0.0-py3-none-any.whl",
            "2.0.1",
            "version does not match",
        ),
        (
            _wheel(extra_files={"opsgrid_agent/native.so": b"binary"}),
            "opsgrid_agent-2.0.0-py3-none-any.whl",
            "2.0.0",
            "pure Python",
        ),
        (
            _wheel(extra_files={"../escape.py": b"bad"}),
            "opsgrid_agent-2.0.0-py3-none-any.whl",
            "2.0.0",
            "unsafe path",
        ),
        (
            _wheel(),
            "agent.whl",
            "2.0.0",
            "valid wheel name",
        ),
    ],
)
def test_rejects_unsafe_or_incompatible_wheels(
    artifact,
    filename,
    version,
    message,
):
    with pytest.raises(AgentArtifactError, match=message):
        validate_agent_wheel(
            artifact,
            filename=filename,
            expected_version=version,
            max_uncompressed_bytes=1024 * 1024,
        )
