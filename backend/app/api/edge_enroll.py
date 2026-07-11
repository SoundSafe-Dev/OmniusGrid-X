"""Edge agent enrollment + gateway authentication (tasks 3, 5).

`POST /api/v1/edge/enroll` — an agent presents a one-time bootstrap token and a
CSR; the backend authenticates the token, signs the CSR via the internal edge CA
(:mod:`app.services.edge_ca`), and returns the agent certificate + CA bundle.

`require_agent` — a FastAPI dependency that authenticates subsequent edge calls
by the agent certificate the TLS-terminating proxy forwards in a header. Other
edge endpoints (heartbeat, telemetry uplink) depend on it to obtain a verified
:class:`AgentPrincipal` instead of trusting a client-supplied agent_id.
"""

import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.core.config import settings
from app.services.edge_ca import (
    AgentPrincipal,
    CertificateVerificationError,
    edge_ca,
)

router = APIRouter()


class EnrollRequest(BaseModel):
    agent_id: str
    csr: str  # PEM-encoded certificate signing request


class EnrollResponse(BaseModel):
    certificate: str
    ca_certificate: str


def _bootstrap_token() -> str:
    return getattr(settings, "EDGE_BOOTSTRAP_TOKEN", "") or ""


@router.post("/api/v1/edge/enroll", response_model=EnrollResponse, tags=["Edge"])
async def enroll_agent(
    body: EnrollRequest,
    authorization: str = Header(default=""),
) -> EnrollResponse:
    """Authenticate a bootstrap token and sign the agent's CSR."""
    expected = _bootstrap_token()
    if not expected:
        # Fail closed: never sign CSRs when no bootstrap secret is configured.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="edge enrollment is not configured",
        )

    presented = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid bootstrap token")

    try:
        cert_pem = edge_ca.sign_csr(body.csr, body.agent_id)
    except CertificateVerificationError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return EnrollResponse(
        certificate=cert_pem.decode(),
        ca_certificate=edge_ca.ca_certificate_pem().decode(),
    )


POP_MAX_SKEW_SECONDS = 300  # signature timestamp freshness window (replay bound)


def _verify_proof_of_possession(pem: str, timestamp: str, signature_b64: str,
                                body_bytes: bytes) -> None:
    """Verify the request signature against the certificate's PUBLIC key.

    The certificate itself is public material (it rides every request), so the
    X-Client-Cert header alone proves nothing — anyone who observed one request
    could replay it. The signature over "<timestamp>.<sha256(body)>" proves the
    sender holds the matching PRIVATE key; the freshness window bounds replay.
    """
    import base64
    import hashlib
    from datetime import datetime, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.exceptions import InvalidSignature

    try:
        ts = datetime.fromisoformat(timestamp)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid signature timestamp")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if abs((datetime.now(timezone.utc) - ts).total_seconds()) > POP_MAX_SKEW_SECONDS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="stale request signature")

    digest = hashlib.sha256(body_bytes).hexdigest() if body_bytes else hashlib.sha256(b"").hexdigest()
    message = f"{timestamp}.{digest}".encode("utf-8")
    cert = x509.load_pem_x509_certificate(pem.encode())
    try:
        cert.public_key().verify(
            base64.b64decode(signature_b64), message, ec.ECDSA(hashes.SHA256())
        )
    except (InvalidSignature, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid request signature")


async def require_agent(
    request: Request,
    x_client_cert: str = Header(default=""),
    x_agent_timestamp: str = Header(default=""),
    x_agent_signature: str = Header(default=""),
) -> AgentPrincipal:
    """Authenticate an edge request by its forwarded client certificate.

    The TLS-terminating proxy (e.g. ingress/mesh doing mTLS) sets
    ``X-Client-Cert`` to the PEM the agent presented. We re-verify it against the
    edge CA here so trust does not rest on the proxy alone, and so the same check
    works in tests without a live TLS handshake.

    When the agent also sends X-Agent-Timestamp/X-Agent-Signature (proof of
    possession of the private key), the signature is verified. With
    EDGE_REQUIRE_PROOF_OF_POSSESSION=true, requests WITHOUT a signature are
    rejected — closing the header-replay hole outright.
    """
    if not x_client_cert:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="missing client certificate"
        )
    # Headers collapse newlines to spaces on some proxies; tolerate both forms.
    pem = x_client_cert.replace("\\n", "\n")
    try:
        principal = edge_ca.verify_agent_certificate(pem)
    except CertificateVerificationError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(e))

    if x_agent_signature and x_agent_timestamp:
        # The signature covers the CANONICAL json of the parsed body (the agent
        # signs its dict pre-serialization), so re-canonicalize here.
        import json as _json
        try:
            raw = await request.body()
            body = _json.loads(raw) if raw else {}
            canonical = _json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        except ValueError:
            canonical = b""
        _verify_proof_of_possession(pem, x_agent_timestamp, x_agent_signature, canonical)
    elif settings.EDGE_REQUIRE_PROOF_OF_POSSESSION:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="request signature required (proof of possession)",
        )
    return principal
