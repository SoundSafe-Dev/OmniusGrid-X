"""Internal certificate authority for edge-agent enrollment (tasks 3, 5).

Signs agent CSRs so each edge agent gets a short-lived X.509 identity, and
verifies agent certificates presented on the uplink. The CA key/cert are loaded
from configured paths; in a dev environment where none are provisioned a
self-signed CA is generated on first use and cached on disk so restarts are
stable. Certificates are deliberately short-lived (default 30 days) to pair with
the agent-side rotation manager.

Config (read via getattr with safe defaults, so this stays independent of the
shared config.py and does not need a migration):

    EDGE_CA_CERT_PATH   PEM CA certificate            (default /certs/edge-ca.crt)
    EDGE_CA_KEY_PATH    PEM CA private key            (default /certs/edge-ca.key)
    EDGE_CERT_TTL_DAYS  issued-cert validity in days  (default 30)
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.core.config import settings

logger = structlog.get_logger()


class AgentPrincipal:
    """The verified identity extracted from an agent certificate."""

    def __init__(self, agent_id: str, serial: int, not_after: datetime):
        self.agent_id = agent_id
        self.serial = serial
        self.not_after = not_after

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"AgentPrincipal(agent_id={self.agent_id!r}, serial={self.serial})"


class CertificateVerificationError(Exception):
    """Raised when a presented agent certificate fails verification."""


class EdgeCA:
    """Loads (or bootstraps) the edge CA and signs/verifies agent certs."""

    def __init__(self) -> None:
        self.cert_path = Path(getattr(settings, "EDGE_CA_CERT_PATH", "/certs/edge-ca.crt"))
        self.key_path = Path(getattr(settings, "EDGE_CA_KEY_PATH", "/certs/edge-ca.key"))
        self.ttl_days = int(getattr(settings, "EDGE_CERT_TTL_DAYS", 30))
        self._ca_cert: Optional[x509.Certificate] = None
        self._ca_key: Optional[ec.EllipticCurvePrivateKey] = None

    # --- CA material ---------------------------------------------------------

    def _load_or_bootstrap(self) -> None:
        if self._ca_cert is not None and self._ca_key is not None:
            return
        if self.cert_path.exists() and self.key_path.exists():
            self._ca_cert = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
            self._ca_key = serialization.load_pem_private_key(
                self.key_path.read_bytes(), password=None
            )
            return
        self._bootstrap_self_signed()

    def _bootstrap_self_signed(self) -> None:
        logger.warning("edge_ca_bootstrapping_self_signed", path=str(self.cert_path))
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "opsgrid-edge-ca")])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256())
        )
        self._ca_cert, self._ca_key = cert, key
        try:
            self.cert_path.parent.mkdir(parents=True, exist_ok=True)
            self.cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            self.key_path.write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        except OSError as e:  # read-only fs in some envs — keep in-memory CA
            logger.warning("edge_ca_persist_failed", error=str(e))

    def ca_certificate_pem(self) -> bytes:
        self._load_or_bootstrap()
        return self._ca_cert.public_bytes(serialization.Encoding.PEM)

    # --- signing (task 3) ----------------------------------------------------

    def sign_csr(self, csr_pem: str, expected_agent_id: str) -> bytes:
        """Sign an agent CSR, returning the certificate PEM.

        The CSR's CN must equal ``expected_agent_id`` (the enrolling agent's id)
        so an agent cannot request a certificate for a different identity.
        """
        self._load_or_bootstrap()
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        if not csr.is_signature_valid:
            raise CertificateVerificationError("CSR signature is invalid")

        cn_attrs = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        cn = cn_attrs[0].value if cn_attrs else ""
        if cn != expected_agent_id:
            raise CertificateVerificationError(
                f"CSR CN '{cn}' does not match agent_id '{expected_agent_id}'"
            )

        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(self._ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=self.ttl_days))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(self._ca_key, hashes.SHA256())
        )
        logger.info("agent_csr_signed", agent_id=expected_agent_id)
        return cert.public_bytes(serialization.Encoding.PEM)

    # --- verification (task 5) ----------------------------------------------

    def verify_agent_certificate(self, cert_pem: str, now: Optional[datetime] = None) -> AgentPrincipal:
        """Verify a presented agent cert against the CA; return its principal.

        Checks the issuer signature (cert was signed by this CA) and validity
        window. Returns the :class:`AgentPrincipal` (agent_id from CN) on success.
        """
        self._load_or_bootstrap()
        now = now or datetime.now(timezone.utc)
        try:
            cert = x509.load_pem_x509_certificate(cert_pem.encode())
        except ValueError as e:
            raise CertificateVerificationError(f"unparseable certificate: {e}") from e

        # Verify the CA actually signed this cert.
        try:
            self._ca_cert.public_key().verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                ec.ECDSA(cert.signature_hash_algorithm),
            )
        except Exception as e:
            raise CertificateVerificationError("certificate not signed by edge CA") from e

        if now < cert.not_valid_before_utc or now > cert.not_valid_after_utc:
            raise CertificateVerificationError("certificate outside its validity window")

        cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if not cn_attrs:
            raise CertificateVerificationError("certificate has no CN / agent_id")
        return AgentPrincipal(cn_attrs[0].value, cert.serial_number, cert.not_valid_after_utc)


# Global instance (lazy — CA material is loaded on first use).
edge_ca = EdgeCA()
