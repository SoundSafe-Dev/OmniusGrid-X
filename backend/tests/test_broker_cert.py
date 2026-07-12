"""EdgeCA server-cert issuance (FS-65): SAN, EKU, chain, key match."""

import importlib

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


@pytest.fixture
def ca(tmp_path, monkeypatch):
    config_mod = importlib.import_module("app.core.config")
    monkeypatch.setattr(config_mod.settings, "EDGE_CA_CERT_PATH", str(tmp_path / "ca.crt"), raising=False)
    monkeypatch.setattr(config_mod.settings, "EDGE_CA_KEY_PATH", str(tmp_path / "ca.key"), raising=False)
    edge_ca_mod = importlib.import_module("app.services.edge_ca")
    return edge_ca_mod.EdgeCA()


def test_server_cert_has_sans_eku_and_chains_to_ca(ca):
    cert_pem, key_pem = ca.issue_server_cert(
        "redpanda", ["redpanda", "redpanda.omniusgrid.svc.cluster.local"], ttl_days=30
    )
    cert = x509.load_pem_x509_certificate(cert_pem)

    sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert set(sans.get_values_for_type(x509.DNSName)) == {
        "redpanda",
        "redpanda.omniusgrid.svc.cluster.local",
    }

    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert x509.oid.ExtendedKeyUsageOID.SERVER_AUTH in eku

    bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is False

    # chains to the CA agents trust
    ca_cert = x509.load_pem_x509_certificate(ca.ca_certificate_pem())
    ca_cert.public_key().verify(
        cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm)
    )

    # the emitted key pairs with the cert
    key = serialization.load_pem_private_key(key_pem, password=None)
    assert key.public_key().public_numbers() == cert.public_key().public_numbers()


def test_server_cert_requires_sans(ca):
    with pytest.raises(ValueError):
        ca.issue_server_cert("redpanda", [])


def test_server_cert_is_not_a_valid_agent_cert_grantor(ca):
    # verify_agent_certificate accepts anything the CA signed with a CN — a
    # broker cert would pass. Document the principal it yields so nothing
    # treats 'redpanda' as an agent id implicitly.
    cert_pem, _ = ca.issue_server_cert("redpanda", ["redpanda"])
    principal = ca.verify_agent_certificate(cert_pem.decode())
    assert principal.agent_id == "redpanda"  # callers must check agent_id semantics
