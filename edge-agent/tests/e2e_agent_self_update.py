"""Manual container harness for a real good update and bad-update rollback.

This is intentionally not collected by pytest. The verification commands run
its subcommands inside the production edge image against an isolated Redpanda.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import hashlib
import io
import json
import os
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _wheel_variant(seed: Path, version: str, *, fail_on_boot: bool) -> bytes:
    with zipfile.ZipFile(seed) as archive:
        files = {
            name: archive.read(name)
            for name in archive.namelist()
            if not name.endswith("/")
        }

    old_dist_info = next(
        PurePosixPath(name).parts[0]
        for name in files
        if name.endswith(".dist-info/METADATA")
    )
    new_dist_info = f"opsgrid_agent-{version}.dist-info"
    transformed = {}
    for name, content in files.items():
        if name.endswith(".dist-info/RECORD"):
            continue
        if name.startswith(f"{old_dist_info}/"):
            name = f"{new_dist_info}/{name.split('/', 1)[1]}"
        if name == f"{new_dist_info}/METADATA":
            text = content.decode("utf-8")
            lines = [
                f"Version: {version}" if line.startswith("Version: ") else line
                for line in text.splitlines()
            ]
            content = ("\n".join(lines) + "\n").encode("utf-8")
        elif name == "opsgrid_agent/__init__.py":
            content = f'"""OpsGrid edge agent package metadata."""\n\n__version__ = "{version}"\n'.encode()
        elif name == "opsgrid_agent/main.py" and fail_on_boot:
            text = content.decode("utf-8")
            needle = 'async def main():\n    """Entry point"""\n'
            replacement = (
                needle
                + "    if os.getenv('OPSGRID_BOOTSTRAP_MANAGED') == 'true':\n"
                + "        raise RuntimeError('intentional bad agent boot')\n"
            )
            if needle not in text:
                raise RuntimeError("Cannot inject bad-agent boot failure")
            content = text.replace(needle, replacement, 1).encode("utf-8")
        transformed[name] = content

    record_path = f"{new_dist_info}/RECORD"
    record_buffer = io.StringIO()
    writer = csv.writer(record_buffer, lineterminator="\n")
    for name in sorted(transformed):
        content = transformed[name]
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=")
        writer.writerow([name, f"sha256={digest.decode()}", len(content)])
    writer.writerow([record_path, "", ""])
    transformed[record_path] = record_buffer.getvalue().encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in transformed.items():
            archive.writestr(name, content)
    return output.getvalue()


def prepare(seed: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    manifest = {
        "public_key": base64.b64encode(public_key).decode("ascii"),
        "releases": {},
    }
    for version, bad in (("2.0.0", False), ("3.0.0", True)):
        artifact = _wheel_variant(seed, version, fail_on_boot=bad)
        filename = f"opsgrid_agent-{version}-py3-none-any.whl"
        (output_dir / filename).write_bytes(artifact)
        manifest["releases"][version] = {
            "filename": filename,
            "size": len(artifact),
            "checksum": hashlib.sha256(artifact).hexdigest(),
            "signature": base64.b64encode(private_key.sign(artifact)).decode("ascii"),
        }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


async def send_update(
    *,
    broker: str,
    command_topic: str,
    ack_topic: str,
    organization_id: str,
    asset_id: str,
    agent_id: str,
    artifact_base_url: str,
    manifest_path: Path,
    version: str,
    expected_status: str,
    expected_running_version: str,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    release = manifest["releases"][version]
    command_id = str(uuid.uuid4())
    consumer = AIOKafkaConsumer(
        ack_topic,
        bootstrap_servers=broker,
        group_id=f"ota-e2e-{uuid.uuid4()}",
        auto_offset_reset="latest",
        enable_auto_commit=True,
    )
    producer = AIOKafkaProducer(bootstrap_servers=broker, acks="all")
    await consumer.start()
    await producer.start()
    try:
        command = {
            "schema_version": 1,
            "message_type": "command",
            "command_id": command_id,
            "agent_id": agent_id,
            "asset_id": asset_id,
            "organization_id": organization_id,
            "action_id": "agent_self_update",
            "parameters": {
                "release_id": f"release-{version}",
                "target_version": version,
                "bundle_url": f"{artifact_base_url.rstrip('/')}/{release['filename']}",
                "checksum_sha256": release["checksum"],
                "signature_ed25519": release["signature"],
                "artifact_format": "wheel",
                "artifact_filename": release["filename"],
                "artifact_size_bytes": release["size"],
                "package_name": "opsgrid-agent",
                "minimum_bootstrap_version": "1.0.0",
            },
            "timeout_seconds": 180,
        }
        await producer.send_and_wait(
            command_topic,
            json.dumps(command).encode("utf-8"),
            key=command_id.encode("utf-8"),
        )

        async def matching_ack():
            async for message in consumer:
                ack = json.loads(message.value.decode("utf-8"))
                if ack.get("command_id") == command_id:
                    return ack

        ack = await asyncio.wait_for(matching_ack(), timeout=180)
        if ack.get("status") != expected_status:
            raise AssertionError(ack)
        result = ack.get("result") or {}
        if result.get("attempted_version") != version:
            raise AssertionError(ack)
        if result.get("running_version") != expected_running_version:
            raise AssertionError(ack)
        if (expected_status == "failed") != bool(result.get("rolled_back")):
            raise AssertionError(ack)
        print(json.dumps(ack, sort_keys=True))
    finally:
        await producer.stop()
        await consumer.stop()


async def wait_heartbeat(
    *,
    broker: str,
    status_topic: str,
    agent_id: str,
    running_version: str,
    attempted_version: str | None,
) -> None:
    consumer = AIOKafkaConsumer(
        status_topic,
        bootstrap_servers=broker,
        group_id=f"heartbeat-e2e-{uuid.uuid4()}",
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        async def matching_heartbeat():
            async for message in consumer:
                heartbeat = json.loads(message.value.decode("utf-8"))
                if heartbeat.get("agent_id") != agent_id:
                    continue
                if heartbeat.get("agent_version") != running_version:
                    continue
                if attempted_version is not None:
                    update = heartbeat.get("agent_update") or {}
                    if update.get("attempted_version") != attempted_version:
                        continue
                return heartbeat

        heartbeat = await asyncio.wait_for(matching_heartbeat(), timeout=120)
        print(json.dumps(heartbeat, sort_keys=True))
    finally:
        await consumer.stop()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--seed", type=Path, required=True)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)

    send_parser = subparsers.add_parser("send")
    send_parser.add_argument("--broker", required=True)
    send_parser.add_argument("--command-topic", required=True)
    send_parser.add_argument("--ack-topic", required=True)
    send_parser.add_argument("--organization-id", required=True)
    send_parser.add_argument("--asset-id", required=True)
    send_parser.add_argument("--agent-id", required=True)
    send_parser.add_argument("--artifact-base-url", required=True)
    send_parser.add_argument("--manifest", type=Path, required=True)
    send_parser.add_argument("--version", required=True)
    send_parser.add_argument("--expected-status", required=True)
    send_parser.add_argument("--expected-running-version", required=True)

    heartbeat_parser = subparsers.add_parser("heartbeat")
    heartbeat_parser.add_argument("--broker", required=True)
    heartbeat_parser.add_argument("--status-topic", required=True)
    heartbeat_parser.add_argument("--agent-id", required=True)
    heartbeat_parser.add_argument("--running-version", required=True)
    heartbeat_parser.add_argument("--attempted-version")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "prepare":
        prepare(args.seed, args.output_dir)
        return
    if args.command == "send":
        asyncio.run(
            send_update(
                broker=args.broker,
                command_topic=args.command_topic,
                ack_topic=args.ack_topic,
                organization_id=args.organization_id,
                asset_id=args.asset_id,
                agent_id=args.agent_id,
                artifact_base_url=args.artifact_base_url,
                manifest_path=args.manifest,
                version=args.version,
                expected_status=args.expected_status,
                expected_running_version=args.expected_running_version,
            )
        )
        return
    asyncio.run(
        wait_heartbeat(
            broker=args.broker,
            status_topic=args.status_topic,
            agent_id=args.agent_id,
            running_version=args.running_version,
            attempted_version=args.attempted_version,
        )
    )


if __name__ == "__main__":
    main()
