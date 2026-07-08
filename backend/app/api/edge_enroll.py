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

from fastapi import APIRouter, Header, HTTPException, status
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


async def require_agent(x_client_cert: str = Header(default="")) -> AgentPrincipal:
    """Authenticate an edge request by its forwarded client certificate.

    The TLS-terminating proxy (e.g. ingress/mesh doing mTLS) sets
    ``X-Client-Cert`` to the PEM the agent presented. We re-verify it against the
    edge CA here so trust does not rest on the proxy alone, and so the same check
    works in tests without a live TLS handshake.
    """
    if not x_client_cert:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="missing client certificate"
        )
    # Headers collapse newlines to spaces on some proxies; tolerate both forms.
    pem = x_client_cert.replace("\\n", "\n")
    try:
        return edge_ca.verify_agent_certificate(pem)
    except CertificateVerificationError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(e))
