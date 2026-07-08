"""Agent cryptographic identity — device ID + local key/cert store (task 1).

Each agent owns a stable ``agent_id`` and an EC P-256 private key, persisted once
under a state directory with owner-only permissions. The key never leaves the
device; enrollment (see :mod:`.enrollment`) sends only a CSR and receives a
signed certificate back. EC over RSA: smaller keys, faster on constrained edge
hardware, and TLS 1.3-friendly.

Layout under ``state_dir`` (default ``/var/lib/opsgrid-agent/identity``)::

    agent_id           # plaintext UUID, generated once
    agent.key          # PEM EC private key, mode 0600
    agent.crt          # PEM certificate, written by enrollment (may be absent)
    ca.crt             # PEM CA bundle used to verify the server, if provisioned
"""

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

logger = structlog.get_logger()

DEFAULT_STATE_DIR = "/var/lib/opsgrid-agent/identity"


@dataclass(frozen=True)
class CertificateInfo:
    """Parsed view of the agent's current certificate."""

    subject_cn: str
    not_before: datetime
    not_after: datetime
    serial: int

    def seconds_until_expiry(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (self.not_after - now).total_seconds()

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        return self.seconds_until_expiry(now) <= 0


class AgentIdentity:
    """Durable per-agent key material and certificate store."""

    def __init__(self, state_dir: str = DEFAULT_STATE_DIR):
        self.state_dir = Path(state_dir)
        self.id_path = self.state_dir / "agent_id"
        self.key_path = self.state_dir / "agent.key"
        self.crt_path = self.state_dir / "agent.crt"
        self.ca_path = self.state_dir / "ca.crt"
        self._private_key: Optional[ec.EllipticCurvePrivateKey] = None

    # --- lifecycle -----------------------------------------------------------

    def load_or_create(self) -> "AgentIdentity":
        """Ensure an agent_id and private key exist on disk, creating once."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.state_dir, 0o700)
        except OSError:  # pragma: no cover - non-POSIX / restricted fs
            pass

        if not self.id_path.exists():
            self.id_path.write_text(str(uuid.uuid4()))
            logger.info("agent_id_generated", agent_id=self.agent_id)

        if not self.key_path.exists():
            self._generate_key()
        else:
            self._load_key()
        return self

    def _generate_key(self) -> None:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        # Write private key with owner-only perms, before content, via 0600 fd.
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        self._private_key = key
        logger.info("agent_key_generated", agent_id=self.agent_id)

    def _load_key(self) -> None:
        self._private_key = serialization.load_pem_private_key(
            self.key_path.read_bytes(), password=None
        )

    # --- accessors -----------------------------------------------------------

    @property
    def agent_id(self) -> str:
        return self.id_path.read_text().strip()

    @property
    def private_key(self) -> ec.EllipticCurvePrivateKey:
        if self._private_key is None:
            self._load_key()
        return self._private_key

    def has_certificate(self) -> bool:
        return self.crt_path.exists()

    # --- CSR + certificate ---------------------------------------------------

    def build_csr(self) -> bytes:
        """Build a PEM CSR whose CN is the agent_id, for the backend to sign."""
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, self.agent_id)])
            )
            .sign(self.private_key, hashes.SHA256())
        )
        return csr.public_bytes(serialization.Encoding.PEM)

    def store_certificate(self, cert_pem: bytes, ca_pem: Optional[bytes] = None) -> None:
        """Persist a signed certificate (and optional CA bundle) from enrollment."""
        self.crt_path.write_bytes(cert_pem)
        if ca_pem:
            self.ca_path.write_bytes(ca_pem)
        logger.info("agent_certificate_stored", agent_id=self.agent_id)

    def certificate_info(self) -> Optional[CertificateInfo]:
        """Parse the stored certificate, or ``None`` if not yet enrolled."""
        if not self.has_certificate():
            return None
        cert = x509.load_pem_x509_certificate(self.crt_path.read_bytes())
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return CertificateInfo(
            subject_cn=cn[0].value if cn else "",
            not_before=cert.not_valid_before_utc,
            not_after=cert.not_valid_after_utc,
            serial=cert.serial_number,
        )
