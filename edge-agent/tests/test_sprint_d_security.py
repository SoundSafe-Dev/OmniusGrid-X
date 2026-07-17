"""Sprint D: uplink TLS enforcement, enrollment verification, request signing,
buffer resilience, and no-silent-synthetic collectors."""

import base64
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from opsgrid_agent.security.identity import AgentIdentity
from opsgrid_agent.security.mtls import MTLSNotReady, build_client_context, uplink_context_or_none
from opsgrid_agent.security.enrollment import EnrollmentClient, EnrollmentError
from opsgrid_agent.security.request_signing import sign_request, body_digest, TIMESTAMP_HEADER, SIGNATURE_HEADER


@pytest.fixture()
def identity(tmp_path):
    return AgentIdentity(str(tmp_path / "identity")).load_or_create()


# ---------------------------------------------------------------- FS-34 strict TLS

def test_strict_mtls_fails_closed_without_ca(identity, tmp_path):
    """Enrolled but no CA bundle: strict mode must refuse system-trust fallback."""
    # self-sign a cert for the identity so has_certificate() is true
    _self_sign(identity)
    identity.ca_path.unlink(missing_ok=True)
    with pytest.raises(MTLSNotReady, match="strict"):
        build_client_context(identity, strict=True)
    # non-strict still builds (system trust store)
    assert build_client_context(identity, strict=False) is not None


def test_strict_uplink_context_raises_when_unenrolled(identity):
    with pytest.raises(MTLSNotReady):
        uplink_context_or_none(identity, strict=True)
    assert uplink_context_or_none(identity, strict=False) is None


# ------------------------------------------------------------ FS-33 enrollment verify

def _self_sign(identity, key=None):
    """Sign the identity's CSR (or another key's cert) with a throwaway CA."""
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "test-ca")])
    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    subject_key = key or identity.private_key
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, identity.agent_id)]))
        .issuer_name(ca_name)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(now + timedelta(days=1))
        .sign(ca_key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    ca_pem = ca_cert.public_bytes(serialization.Encoding.PEM)
    identity.store_certificate(cert_pem, ca_pem)
    return cert_pem.decode(), ca_pem.decode()


def test_enrollment_rejects_wrong_key_certificate(identity):
    """A cert bound to a DIFFERENT key must be refused before persisting."""
    from cryptography.hazmat.primitives.asymmetric import ec
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    cert_pem, ca_pem = _self_sign(identity, key=attacker_key)

    client = EnrollmentClient(identity, "https://cloud", "tok",
                              post_fn=lambda u, b, h: (200, {"certificate": cert_pem,
                                                             "ca_certificate": ca_pem}))
    with pytest.raises(EnrollmentError, match="does not match"):
        client.enroll()


def test_enrollment_ca_fingerprint_pinning(identity, monkeypatch):
    cert_pem, ca_pem = _self_sign(identity)
    client = EnrollmentClient(identity, "https://cloud", "tok",
                              post_fn=lambda u, b, h: (200, {"certificate": cert_pem,
                                                             "ca_certificate": ca_pem}))
    monkeypatch.setenv("ENROLLMENT_CA_FINGERPRINT", "00" * 32)  # wrong pin
    with pytest.raises(EnrollmentError, match="fingerprint mismatch"):
        client.enroll()

    # correct pin passes
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    ca = x509.load_pem_x509_certificate(ca_pem.encode())
    good = hashlib.sha256(ca.public_bytes(serialization.Encoding.DER)).hexdigest()
    monkeypatch.setenv("ENROLLMENT_CA_FINGERPRINT", good)
    client.enroll()  # should not raise


# ------------------------------------------------------------ FS-32 request signing

def test_sign_request_roundtrip(identity):
    _self_sign(identity)
    body = {"agent_id": identity.agent_id, "health": {"ok": True}}
    headers = sign_request(identity, body)
    assert TIMESTAMP_HEADER in headers and SIGNATURE_HEADER in headers

    # verify like the backend does
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    cert = x509.load_pem_x509_certificate(identity.crt_path.read_bytes())
    message = f"{headers[TIMESTAMP_HEADER]}.{body_digest(body)}".encode()
    cert.public_key().verify(base64.b64decode(headers[SIGNATURE_HEADER]),
                             message, ec.ECDSA(hashes.SHA256()))

    # a tampered body must NOT verify
    tampered = f"{headers[TIMESTAMP_HEADER]}.{body_digest({'agent_id': 'evil'})}".encode()
    from cryptography.exceptions import InvalidSignature
    with pytest.raises(InvalidSignature):
        cert.public_key().verify(base64.b64decode(headers[SIGNATURE_HEADER]),
                                 tampered, ec.ECDSA(hashes.SHA256()))


# --------------------------------------------------------- FS-35 buffer resilience

def test_buffer_quarantines_corrupt_db(tmp_path):
    from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
    db = tmp_path / "buffer.db"
    db.write_bytes(b"this is not a sqlite database at all" * 100)
    buf = StoreForwardBuffer(buffer_path=str(db))
    # fresh DB works; corrupt original was quarantined alongside
    quarantined = list(tmp_path.glob("buffer.corrupt-*"))
    assert len(quarantined) == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_buffer_wal_mode_enabled(tmp_path):
    from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
    db = tmp_path / "buffer.db"
    StoreForwardBuffer(buffer_path=str(db))
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


# ------------------------------------------------- FS-37 no silent synthetic data

def test_video_requires_explicit_source_when_enforced(monkeypatch):
    from opsgrid_agent.collectors.video import VideoFrameCollector
    monkeypatch.setenv("EDGE_REQUIRE_EXPLICIT_SOURCES", "true")
    with pytest.raises(ValueError, match="explicit 'source'"):
        VideoFrameCollector({"asset_id": "a1"})
    # explicit simulate is still allowed (it's the operator's choice)
    VideoFrameCollector({"asset_id": "a1", "source": "simulate"})


def test_audio_requires_explicit_source_when_enforced(monkeypatch):
    from opsgrid_agent.collectors.audio import AudioFeatureCollector
    monkeypatch.setenv("EDGE_REQUIRE_EXPLICIT_SOURCES", "true")
    with pytest.raises(ValueError, match="explicit 'source'"):
        AudioFeatureCollector({"asset_id": "a1"})
    AudioFeatureCollector({"asset_id": "a1", "source": "simulate"})
