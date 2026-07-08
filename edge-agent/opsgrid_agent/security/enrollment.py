"""Agent enrollment / onboarding flow (task 3, edge side).

On first boot an agent has a key but no certificate. Enrollment posts its CSR
plus a one-time bootstrap token to the backend, which authenticates the token,
signs the CSR, and returns the agent certificate + CA bundle. The signed cert is
then persisted by :class:`AgentIdentity` and used for all subsequent mTLS.

The HTTP call is injected (``post_fn``) so the flow is unit-testable without a
network and transport-agnostic (urllib default, or the agent's async client).
``post_fn(url, json_body, headers) -> (status_code, response_dict)``.
"""

import json as _json
import urllib.request
from typing import Callable, Dict, Optional, Tuple

import structlog

from .identity import AgentIdentity

logger = structlog.get_logger()

PostFn = Callable[[str, Dict, Dict], Tuple[int, Dict]]


def _default_post(url: str, body: Dict, headers: Dict) -> Tuple[int, Dict]:
    data = _json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec - operator-configured URL
        return resp.status, _json.loads(resp.read().decode("utf-8"))


class EnrollmentError(Exception):
    """Raised when the backend rejects or fails an enrollment request."""


class EnrollmentClient:
    """Drives the CSR -> signed-certificate exchange with the backend."""

    def __init__(
        self,
        identity: AgentIdentity,
        server_url: str,
        bootstrap_token: str,
        post_fn: Optional[PostFn] = None,
    ):
        self.identity = identity
        self.server_url = server_url.rstrip("/")
        self.bootstrap_token = bootstrap_token
        self._post = post_fn or _default_post

    def enroll(self) -> None:
        """Enroll (or re-enroll) this agent, persisting the returned cert.

        Idempotent to call repeatedly; the backend re-signs the CSR each time,
        which is exactly what rotation (:mod:`.rotation`) relies on.
        """
        csr_pem = self.identity.build_csr().decode("utf-8")
        url = f"{self.server_url}/api/v1/edge/enroll"
        headers = {"Authorization": f"Bearer {self.bootstrap_token}"}
        body = {"agent_id": self.identity.agent_id, "csr": csr_pem}

        try:
            status, resp = self._post(url, body, headers)
        except Exception as e:  # network / transport failure
            raise EnrollmentError(f"enrollment transport failed: {e}") from e

        if status != 200:
            raise EnrollmentError(
                f"enrollment rejected (status={status}): {resp.get('detail', resp)}"
            )

        cert_pem = resp.get("certificate")
        if not cert_pem:
            raise EnrollmentError("enrollment response missing 'certificate'")

        ca_pem = resp.get("ca_certificate")
        self.identity.store_certificate(
            cert_pem.encode("utf-8"),
            ca_pem.encode("utf-8") if ca_pem else None,
        )
        logger.info("agent_enrolled", agent_id=self.identity.agent_id)
