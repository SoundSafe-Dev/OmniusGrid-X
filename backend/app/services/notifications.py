"""Notifications & delivery center.

Turns events (alarms / OEE breaches / anomalies / health-index drops / any
producer) into delivered notifications via subscribable rules and multiple
channels (webhook, Slack, email-stub). This is a delivery subsystem — it does not
analyze or generate content; it delivers what producers already emit — so it
complements the Correlation AI engine rather than duplicating it.

Rule matching and dispatch are pure/injectable and testable without a database.
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import structlog

from app.core.config import settings

logger = structlog.get_logger()

SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2, "critical": 3}


def severity_rank(sev: Any) -> int:
    return SEVERITY_ORDER.get(str(sev).lower(), 0)


class NotificationService:
    """Match events against subscription rules and deliver via channel adapters."""

    def __init__(self, channels: Optional[Dict[str, Callable[[str, dict], tuple]]] = None):
        self.channels: Dict[str, Callable[[str, dict], tuple]] = channels or {
            "webhook": self._deliver_webhook,
            "slack": self._deliver_slack,
            "email": self._deliver_email,
        }

    # ------------------------------------------------------------------ #
    # Pure matching + dispatch (no I/O beyond the injected channel adapters)
    # ------------------------------------------------------------------ #
    @staticmethod
    def matches(rule: Dict[str, Any], event: Dict[str, Any]) -> bool:
        """A rule matches when severity >= min and any domain/asset filters agree."""
        if severity_rank(event.get("severity")) < severity_rank(rule.get("min_severity", "info")):
            return False
        domain = rule.get("domain")
        if domain and domain != event.get("domain"):
            return False
        asset = rule.get("asset_id")
        if asset and asset != event.get("asset_id"):
            return False
        return bool(rule.get("enabled", True))

    def deliver(self, channel: str, target: str, event: Dict[str, Any]) -> tuple:
        fn = self.channels.get(channel)
        if fn is None:
            return False, f"unknown channel '{channel}'"
        try:
            return fn(target, event)
        except Exception as e:
            return False, str(e)

    def dispatch_rules(
        self, event: Dict[str, Any], rules: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Deliver an event to every matching rule; return per-delivery results."""
        results: List[Dict[str, Any]] = []
        for rule in rules:
            if not self.matches(rule, event):
                continue
            ok, detail = self.deliver(rule.get("channel", "webhook"), rule.get("target"), event)
            results.append({
                "subscription_id": rule.get("id") or rule.get("subscription_id"),
                "channel": rule.get("channel"),
                "delivered": ok,
                "detail": detail,
            })
        return results

    # ------------------------------------------------------------------ #
    # Channel adapters
    # ------------------------------------------------------------------ #
    def _deliver_webhook(self, target: str, event: Dict[str, Any]) -> tuple:
        import httpx
        resp = httpx.post(target, json=event, timeout=10.0)
        resp.raise_for_status()
        return True, f"HTTP {resp.status_code}"

    def _deliver_slack(self, target: str, event: Dict[str, Any]) -> tuple:
        import httpx
        text = f"[{str(event.get('severity', 'info')).upper()}] " \
               f"{event.get('title', '')}: {event.get('message', '')}"
        resp = httpx.post(target, json={"text": text}, timeout=10.0)
        resp.raise_for_status()
        return True, "slack delivered"

    def _deliver_email(self, target: str, event: Dict[str, Any]) -> tuple:
        """Deliver via the real SMTP transport (app.services.email_service).

        The transport is async; this adapter is sync (like webhook/slack) and is
        always invoked OFF the event loop (dispatch() runs the whole adapter
        chain in a worker thread), so asyncio.run here is safe and blocking is
        fine. When SMTP is unconfigured (dev/tests) we log-and-skip rather than
        error, preserving the previous no-op behavior.
        """
        from app.services import email_service

        if not settings.SMTP_HOST:
            logger.info("notification_email_skipped_no_smtp",
                        to=target, subject=event.get("title"))
            return True, "email skipped (SMTP not configured)"

        subject = f"[{str(event.get('severity', 'info')).upper()}] " \
                  f"{event.get('title', 'Notification')}"
        body = event.get("message") or event.get("title") or ""

        import asyncio
        asyncio.run(email_service.send_email([target], subject, body))
        return True, f"email delivered to {target}"

    # ------------------------------------------------------------------ #
    # DB-backed dispatch (exercised in CI's backend job)
    # ------------------------------------------------------------------ #
    async def dispatch(self, event: Dict[str, Any], organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
        import asyncio

        org_id = organization_id or event.get("organization_id")
        rules = await self._load_rules(org_id)
        # The channel adapters are sync and blocking (SMTP retries, httpx with
        # 10s timeouts): run them in a worker thread so one slow delivery can't
        # freeze the event loop for every other request in the process.
        results = await asyncio.to_thread(self.dispatch_rules, event, rules)
        await self._record_deliveries(event, org_id, results)
        return results

    async def _load_rules(self, org_id: Optional[str]) -> List[Dict[str, Any]]:
        from sqlalchemy import select
        from app.db.database import AsyncSessionLocal
        from app.db.notification_models import NotificationSubscription
        async with AsyncSessionLocal() as session:
            stmt = select(NotificationSubscription).where(NotificationSubscription.enabled == True)  # noqa: E712
            if org_id is not None:
                stmt = stmt.where(NotificationSubscription.organization_id == org_id)
            rows = (await session.execute(stmt)).scalars().all()
        return [{
            "id": str(r.id), "channel": r.channel, "target": r.target,
            "min_severity": r.min_severity, "domain": r.domain, "asset_id": r.asset_id,
            "enabled": r.enabled,
        } for r in rows]

    async def _record_deliveries(self, event: Dict[str, Any], org_id: Optional[str],
                                 results: List[Dict[str, Any]]) -> None:
        from app.db.database import AsyncSessionLocal
        from app.db.notification_models import NotificationDelivery
        if not results:
            return
        async with AsyncSessionLocal() as session:
            for res in results:
                session.add(NotificationDelivery(
                    organization_id=org_id,
                    subscription_id=res.get("subscription_id"),
                    channel=res.get("channel"),
                    severity=event.get("severity"),
                    title=event.get("title"),
                    message=event.get("message"),
                    delivered=res.get("delivered", False),
                    detail=res.get("detail"),
                ))
            await session.commit()


notification_service = NotificationService()
