"""Tests for edge enrollment + gateway agent-auth (tasks 3, 5)."""

import importlib

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


#: The organisation these unit tests enrol agents into.
ENROLMENT_ORG = "11111111-2222-3333-4444-555555555555"


@pytest.fixture()
def ca(tmp_path, monkeypatch):
    """A fresh EdgeCA rooted at a temp dir, with a known bootstrap token."""
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "EDGE_CA_CERT_PATH", str(tmp_path / "ca.crt"), raising=False)
    monkeypatch.setattr(config_mod.settings, "EDGE_CA_KEY_PATH", str(tmp_path / "ca.key"), raising=False)
    monkeypatch.setattr(config_mod.settings, "EDGE_BOOTSTRAP_TOKEN", "boot-secret", raising=False)
    monkeypatch.setattr(config_mod.settings, "EDGE_CERT_TTL_DAYS", 30, raising=False)
    # Enrolment now decides the agent's tenant server-side and refuses when it
    # cannot. Setting it explicitly keeps these unit tests off the database and
    # makes the tenant the certificate should carry visible in the assertions.
    monkeypatch.setattr(
        config_mod.settings, "EDGE_ENROLLMENT_ORGANIZATION_ID", ENROLMENT_ORG, raising=False
    )

    edge_ca_mod = importlib.import_module("app.services.edge_ca")
    fresh = edge_ca_mod.EdgeCA()
    return fresh


def _make_csr(agent_id: str):
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, agent_id)]))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


def test_sign_csr_matches_agent_id(ca):
    cert_pem = ca.sign_csr(_make_csr("agent-42"), "agent-42")
    principal = ca.verify_agent_certificate(cert_pem.decode())
    assert principal.agent_id == "agent-42"


def test_sign_csr_rejects_cn_mismatch(ca):
    from app.services.edge_ca import CertificateVerificationError

    with pytest.raises(CertificateVerificationError):
        ca.sign_csr(_make_csr("attacker"), "agent-42")


def test_a_certificate_without_an_organisation_is_still_verifiable(ca):
    """Certificates issued before agents carried a tenant must keep working. They authenticate
    exactly as before and report `organization_id is None` — the heartbeat logs that and leaves
    the row unattributed rather than rejecting a running fleet mid-upgrade."""
    principal = ca.verify_agent_certificate(
        ca.sign_csr(_make_csr("agent-legacy"), "agent-legacy").decode()
    )
    assert principal.agent_id == "agent-legacy"
    assert principal.organization_id is None


def test_verify_rejects_foreign_certificate(ca):
    from app.services.edge_ca import CertificateVerificationError

    # A cert signed by a *different* CA must not verify.
    other = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agent-x")])
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    foreign = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(other.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(other, hashes.SHA256())
    )
    with pytest.raises(CertificateVerificationError):
        ca.verify_agent_certificate(foreign.public_bytes(serialization.Encoding.PEM).decode())


def test_enroll_endpoint_flow(ca, monkeypatch):
    """End-to-end through the FastAPI route with a patched global CA."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import edge_enroll
    # Point the route's module-level CA at our temp-dir CA.
    monkeypatch.setattr(edge_enroll, "edge_ca", ca)

    app = FastAPI()
    app.include_router(edge_enroll.router)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/edge/enroll",
        json={"agent_id": "agent-7", "csr": _make_csr("agent-7")},
        headers={"Authorization": "Bearer boot-secret"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "BEGIN CERTIFICATE" in body["certificate"]
    assert "BEGIN CERTIFICATE" in body["ca_certificate"]

    # The issued certificate carries the tenant the SERVER chose. Without this the agent
    # authenticates fine, heartbeats fine, and never appears on anybody's fleet page.
    principal = ca.verify_agent_certificate(body["certificate"])
    assert principal.organization_id == ENROLMENT_ORG

    # wrong token rejected
    bad = client.post(
        "/api/v1/edge/enroll",
        json={"agent_id": "agent-7", "csr": _make_csr("agent-7")},
        headers={"Authorization": "Bearer wrong"},
    )
    assert bad.status_code == 401
