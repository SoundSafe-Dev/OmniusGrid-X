"""mTLS transport for the edge->cloud uplink (task 2).

Builds a client-side :class:`ssl.SSLContext` presenting the agent certificate
and verifying the server against the enrolled CA bundle. Mutual TLS means the
gateway authenticates the agent by its client certificate (see the backend
gateway-auth work, task 5) and the agent authenticates the gateway — closing the
previously unauthenticated uplink in both directions.
"""

import ssl
from typing import Optional

import structlog

from .identity import AgentIdentity

logger = structlog.get_logger()


class MTLSNotReady(Exception):
    """Raised when an mTLS context is requested before enrollment completes."""


def build_client_context(identity: AgentIdentity) -> ssl.SSLContext:
    """Build a mutual-TLS client context from the agent's key/cert/CA.

    Requires the agent to be enrolled (certificate present). If a CA bundle was
    provisioned we pin verification to it; otherwise we fall back to the system
    trust store (still verified — never disabled).
    """
    if not identity.has_certificate():
        raise MTLSNotReady("agent is not enrolled; no client certificate available")

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True

    if identity.ca_path.exists():
        ctx.load_verify_locations(cafile=str(identity.ca_path))
    else:
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)

    ctx.load_cert_chain(certfile=str(identity.crt_path), keyfile=str(identity.key_path))
    logger.info("mtls_context_built", agent_id=identity.agent_id)
    return ctx


def uplink_context_or_none(identity: AgentIdentity) -> Optional[ssl.SSLContext]:
    """Best-effort context for optional-mTLS deployments.

    Returns ``None`` (plaintext/legacy uplink) when the agent is not yet enrolled
    instead of raising, so a fleet can be migrated to mTLS incrementally without a
    flag-day. Callers should prefer :func:`build_client_context` once enrollment
    is mandated.
    """
    try:
        return build_client_context(identity)
    except MTLSNotReady:
        logger.warning("mtls_not_ready_plaintext_uplink", agent_id=identity.agent_id)
        return None
