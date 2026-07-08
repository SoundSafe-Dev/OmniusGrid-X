"""Edge agent transport security: identity, enrollment, mTLS, rotation.

The edge->cloud uplink was previously unauthenticated. This package gives each
agent a durable cryptographic identity (:mod:`.identity`), an enrollment flow to
obtain a signed certificate from the backend (:mod:`.enrollment`), an mTLS
transport for the uplink (:mod:`.mtls`), and a rotation manager that renews
certificates before expiry (:mod:`.rotation`).
"""

from .identity import AgentIdentity, CertificateInfo

__all__ = ["AgentIdentity", "CertificateInfo"]
