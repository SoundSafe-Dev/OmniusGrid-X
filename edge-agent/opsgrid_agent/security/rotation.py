"""Certificate rotation + expiry handling (task 4).

Certificates are short-lived by design (least privilege on a compromised agent).
The rotation manager periodically checks the current certificate and re-enrolls
before it expires, so a healthy agent never lets its cert lapse. Renewal reuses
the enrollment flow (the backend re-signs the same CSR), so no new key is minted
unless the key file is missing.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog

from .enrollment import EnrollmentClient, EnrollmentError
from .identity import AgentIdentity

logger = structlog.get_logger()

# Renew once the cert is within this fraction of its remaining life, or under the
# absolute floor — whichever triggers first. Renewing at ~1/3 remaining life
# leaves ample retry runway before hard expiry.
DEFAULT_RENEW_BEFORE_SECONDS = 7 * 24 * 3600  # 7 days


def should_renew(
    not_after: datetime,
    now: Optional[datetime] = None,
    renew_before_seconds: float = DEFAULT_RENEW_BEFORE_SECONDS,
) -> bool:
    """True if the certificate should be renewed now."""
    now = now or datetime.now(timezone.utc)
    return (not_after - now).total_seconds() <= renew_before_seconds


class CertificateRotationManager:
    """Background task that renews the agent certificate before expiry."""

    def __init__(
        self,
        identity: AgentIdentity,
        enrollment: EnrollmentClient,
        renew_before_seconds: float = DEFAULT_RENEW_BEFORE_SECONDS,
        check_interval_seconds: float = 3600.0,
    ):
        self.identity = identity
        self.enrollment = enrollment
        self.renew_before_seconds = renew_before_seconds
        self.check_interval_seconds = check_interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def check_once(self, now: Optional[datetime] = None) -> bool:
        """Renew if needed. Returns True when a renewal was performed."""
        info = self.identity.certificate_info()
        # No cert yet -> initial enrollment is the "renewal".
        needs = info is None or should_renew(
            info.not_after, now, self.renew_before_seconds
        )
        if not needs:
            return False
        try:
            self.enrollment.enroll()
            return True
        except EnrollmentError as e:
            logger.error("certificate_renewal_failed", error=str(e))
            return False

    async def start(self) -> None:
        """Run the periodic rotation loop until :meth:`stop`."""
        self._running = True
        while self._running:
            self.check_once()
            try:
                await asyncio.sleep(self.check_interval_seconds)
            except asyncio.CancelledError:  # pragma: no cover
                break

    async def stop(self) -> None:
        self._running = False
