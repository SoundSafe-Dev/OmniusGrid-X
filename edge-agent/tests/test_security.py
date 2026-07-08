"""Tests for edge transport security: identity, enrollment, mTLS, rotation
(tasks 1-4)."""

from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from opsgrid_agent.security.enrollment import EnrollmentClient, EnrollmentError
from opsgrid_agent.security.identity import AgentIdentity
from opsgrid_agent.security.mtls import MTLSNotReady, build_client_context
from opsgrid_agent.security.rotation import CertificateRotationManager, should_renew


# --- a throwaway CA that signs CSRs, standing in for the backend --------------

class _FakeCA:
    def __init__(self, validity_days=30):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.validity_days = validity_days
        self.name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])

    def sign(self, csr_pem: str) -> str:
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(self.name)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=self.validity_days))
            .sign(self.key, hashes.SHA256())
        )
        return cert.public_bytes(serialization.Encoding.PEM).decode()

    def post_fn(self, url, body, headers):
        assert headers["Authorization"].startswith("Bearer ")
        return 200, {"certificate": self.sign(body["csr"]), "ca_certificate": None}


# --- task 1: identity ---------------------------------------------------------

def test_identity_created_once_and_stable(tmp_path):
    ident = AgentIdentity(str(tmp_path)).load_or_create()
    aid = ident.agent_id
    assert aid
    # reload from disk -> same id and key, not regenerated
    again = AgentIdentity(str(tmp_path)).load_or_create()
    assert again.agent_id == aid


def test_private_key_file_is_owner_only(tmp_path):
    AgentIdentity(str(tmp_path)).load_or_create()
    mode = (tmp_path / "agent.key").stat().st_mode & 0o777
    assert mode == 0o600


def test_csr_carries_agent_id_as_cn(tmp_path):
    ident = AgentIdentity(str(tmp_path)).load_or_create()
    csr = x509.load_pem_x509_csr(ident.build_csr())
    cn = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert cn == ident.agent_id


# --- task 3: enrollment -------------------------------------------------------

def test_enrollment_stores_signed_certificate(tmp_path):
    ident = AgentIdentity(str(tmp_path)).load_or_create()
    ca = _FakeCA()
    EnrollmentClient(ident, "https://cloud", "boot-tok", post_fn=ca.post_fn).enroll()

    assert ident.has_certificate()
    info = ident.certificate_info()
    assert info.subject_cn == ident.agent_id
    assert not info.is_expired()


def test_enrollment_rejected_raises(tmp_path):
    ident = AgentIdentity(str(tmp_path)).load_or_create()

    def reject(url, body, headers):
        return 401, {"detail": "bad bootstrap token"}

    with pytest.raises(EnrollmentError):
        EnrollmentClient(ident, "https://cloud", "nope", post_fn=reject).enroll()


# --- task 2: mTLS -------------------------------------------------------------

def test_mtls_context_requires_enrollment(tmp_path):
    ident = AgentIdentity(str(tmp_path)).load_or_create()
    with pytest.raises(MTLSNotReady):
        build_client_context(ident)


def test_mtls_context_built_after_enrollment(tmp_path):
    ident = AgentIdentity(str(tmp_path)).load_or_create()
    ca = _FakeCA()
    EnrollmentClient(ident, "https://cloud", "tok", post_fn=ca.post_fn).enroll()
    ctx = build_client_context(ident)
    assert ctx.verify_mode.name == "CERT_REQUIRED"


# --- task 4: rotation ---------------------------------------------------------

def test_should_renew_within_window():
    now = datetime(2026, 7, 8, tzinfo=timezone.utc)
    soon = now + timedelta(days=3)
    later = now + timedelta(days=30)
    assert should_renew(soon, now, renew_before_seconds=7 * 24 * 3600) is True
    assert should_renew(later, now, renew_before_seconds=7 * 24 * 3600) is False


def test_rotation_enrolls_when_no_cert(tmp_path):
    ident = AgentIdentity(str(tmp_path)).load_or_create()
    ca = _FakeCA()
    client = EnrollmentClient(ident, "https://cloud", "tok", post_fn=ca.post_fn)
    mgr = CertificateRotationManager(ident, client)
    assert mgr.check_once() is True          # no cert -> initial enroll
    assert mgr.check_once() is False         # fresh cert -> nothing to do


def test_rotation_renews_expiring_cert(tmp_path):
    ident = AgentIdentity(str(tmp_path)).load_or_create()
    ca = _FakeCA(validity_days=1)            # near-expiry cert
    client = EnrollmentClient(ident, "https://cloud", "tok", post_fn=ca.post_fn)
    # renew_before larger than the cert's whole life -> always renews
    mgr = CertificateRotationManager(ident, client, renew_before_seconds=2 * 24 * 3600)
    assert mgr.check_once() is True
    assert mgr.check_once() is True
