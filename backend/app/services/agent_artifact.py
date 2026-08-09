"""Validation helpers for untrusted edge-agent wheel artifacts."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import PurePosixPath

from packaging.utils import InvalidWheelFilename, parse_wheel_filename


EXPECTED_PACKAGE_NAME = "opsgrid-agent"
MAX_WHEEL_MEMBERS = 10_000
_NORMALIZE_NAME = re.compile(r"[-_.]+")
_COMPILED_SUFFIXES = (".so", ".pyd", ".dylib", ".dll")


class AgentArtifactError(ValueError):
    """The uploaded agent artifact is not a safe, compatible wheel."""


@dataclass(frozen=True)
class AgentWheelMetadata:
    package_name: str
    version: str
    filename: str
    size_bytes: int


def normalize_package_name(value: str) -> str:
    return _NORMALIZE_NAME.sub("-", value).lower()


def validate_agent_wheel(
    artifact: bytes,
    *,
    filename: str,
    expected_version: str,
    max_uncompressed_bytes: int,
) -> AgentWheelMetadata:
    """Validate wheel structure and metadata without importing its code."""
    if not artifact:
        raise AgentArtifactError("Agent wheel cannot be empty")
    if (
        not filename
        or filename != PurePosixPath(filename).name
        or "\\" in filename
    ):
        raise AgentArtifactError("Agent wheel filename must not contain a path")
    if not filename.endswith(".whl"):
        raise AgentArtifactError("Agent artifact must be a .whl file")
    try:
        filename_name, filename_version, _, filename_tags = parse_wheel_filename(
            filename
        )
    except InvalidWheelFilename as exc:
        raise AgentArtifactError("Agent artifact filename is not a valid wheel name") from exc
    if normalize_package_name(str(filename_name)) != EXPECTED_PACKAGE_NAME:
        raise AgentArtifactError("Agent wheel filename must identify opsgrid-agent")
    if str(filename_version) != expected_version:
        raise AgentArtifactError("Agent wheel filename version does not match release version")
    if any(tag.abi != "none" or tag.platform != "any" for tag in filename_tags):
        raise AgentArtifactError("Agent wheel filename must declare a pure-Python wheel")

    try:
        archive = zipfile.ZipFile(io.BytesIO(artifact))
    except zipfile.BadZipFile as exc:
        raise AgentArtifactError("Agent artifact is not a valid wheel archive") from exc

    with archive:
        members = archive.infolist()
        if not members or len(members) > MAX_WHEEL_MEMBERS:
            raise AgentArtifactError("Agent wheel has an invalid member count")

        total_uncompressed = 0
        seen_names: set[str] = set()
        metadata_members: list[zipfile.ZipInfo] = []
        wheel_members: list[zipfile.ZipInfo] = []
        for member in members:
            _validate_member(member)
            if member.filename in seen_names:
                raise AgentArtifactError("Agent wheel contains duplicate paths")
            seen_names.add(member.filename)
            total_uncompressed += member.file_size
            if total_uncompressed > max_uncompressed_bytes:
                raise AgentArtifactError("Agent wheel expands beyond the allowed size")
            if member.filename.endswith(".dist-info/METADATA"):
                metadata_members.append(member)
            elif member.filename.endswith(".dist-info/WHEEL"):
                wheel_members.append(member)
            if member.filename.lower().endswith(_COMPILED_SUFFIXES):
                raise AgentArtifactError("Agent wheel must be pure Python")

        if len(metadata_members) != 1 or len(wheel_members) != 1:
            raise AgentArtifactError("Agent wheel must contain one METADATA and WHEEL file")

        metadata = BytesParser().parsebytes(archive.read(metadata_members[0]))
        wheel_metadata = BytesParser().parsebytes(archive.read(wheel_members[0]))

    package_name = str(metadata.get("Name") or "").strip()
    version = str(metadata.get("Version") or "").strip()
    if normalize_package_name(package_name) != EXPECTED_PACKAGE_NAME:
        raise AgentArtifactError("Agent wheel package must be opsgrid-agent")
    if not version or version != expected_version:
        raise AgentArtifactError("Agent wheel version does not match release version")
    if str(wheel_metadata.get("Root-Is-Purelib") or "").lower() != "true":
        raise AgentArtifactError("Agent wheel must declare Root-Is-Purelib: true")
    tags = wheel_metadata.get_all("Tag") or []
    if not any(str(tag).endswith("-none-any") for tag in tags):
        raise AgentArtifactError("Agent wheel must use a platform-independent tag")

    return AgentWheelMetadata(
        package_name=EXPECTED_PACKAGE_NAME,
        version=version,
        filename=filename,
        size_bytes=len(artifact),
    )


def _validate_member(member: zipfile.ZipInfo) -> None:
    name = member.filename
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise AgentArtifactError("Agent wheel contains an unsafe path")
    if member.flag_bits & 0x1:
        raise AgentArtifactError("Agent wheel must not contain encrypted files")

    # Unix symlink file type bits live in the upper 16 bits.
    file_type = (member.external_attr >> 16) & 0o170000
    if file_type == 0o120000:
        raise AgentArtifactError("Agent wheel must not contain symbolic links")
