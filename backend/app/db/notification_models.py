"""Notification subsystem models (subscriptions + delivery log).

Kept in a separate module (reusing the shared Base) to avoid touching the large
shared models.py.
"""

from datetime import datetime

from sqlalchemy import Column, String, Boolean, Text, DateTime

from app.db.models import Base, UUIDColumn


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"

    id = UUIDColumn()
    organization_id = Column(String(36), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    channel = Column(String(20), nullable=False)          # webhook | slack | email
    target = Column(String(1024), nullable=False)         # URL or email address
    min_severity = Column(String(20), default="warning")  # info|warning|error|critical
    domain = Column(String(100))                          # optional filter
    asset_id = Column(String(36))                         # optional filter
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id = UUIDColumn()
    organization_id = Column(String(36), index=True)
    subscription_id = Column(String(36), index=True)
    channel = Column(String(20))
    severity = Column(String(20))
    title = Column(String(512))
    message = Column(Text)
    delivered = Column(Boolean, default=False)
    detail = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
