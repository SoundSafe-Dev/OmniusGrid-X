"""Proof-of-possession request signing for the HTTPS uplink (FS-32).

The X-Client-Cert header alone is spoofable: a certificate is PUBLIC material
(it rides every request), so possession of the header proves nothing. These
helpers sign each request with the agent's PRIVATE key; the backend verifies
the signature against the public key inside the CA-verified certificate, so a
replayed/forged header without the key is rejected.

Signed string:  "<timestamp>.<sha256(canonical-json-body)>"
Headers:        X-Agent-Timestamp (ISO-8601 UTC), X-Agent-Signature (b64 ECDSA)
Freshness is enforced server-side (default ±5 min) to bound replay.
"""

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from .identity import AgentIdentity

TIMESTAMP_HEADER = "X-Agent-Timestamp"
SIGNATURE_HEADER = "X-Agent-Signature"


def body_digest(body: Dict) -> str:
    """Canonical sha256 of the JSON body (sorted keys, compact separators)."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sign_request(identity: AgentIdentity, body: Dict) -> Dict[str, str]:
    """Signature headers proving possession of the enrolled private key."""
    timestamp = datetime.now(timezone.utc).isoformat()
    message = f"{timestamp}.{body_digest(body)}".encode("utf-8")
    signature = identity.private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    return {
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: base64.b64encode(signature).decode("ascii"),
    }
