"""Edge-fleet status model (task 17).

One row per enrolled agent, updated on every heartbeat, recording the agent's
last-seen time and self-reported health (buffer depth, dead-letter/drop counts,
active-collector count, certificate expiry). Separate module reusing the shared
Base, to avoid touching the large shared models.py.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.db.models import Base


class EdgeAgentStatus(Base):
    __tablename__ = "edge_agent_status"

    # agent_id (cert CN) is the natural primary key — one status row per agent.
    agent_id = Column(String(64), primary_key=True)
    organization_id = Column(String(36), index=True)
    agent_version = Column(String(32))
    last_seen = Column(DateTime(timezone=True), index=True)

    # Self-reported health from the most recent heartbeat.
    buffer_pending = Column(Integer, default=0)
    dead_lettered = Column(Integer, default=0)
    dropped = Column(Integer, default=0)
    active_collectors = Column(Integer, default=0)
    total_collectors = Column(Integer, default=0)
    cert_expires_in_seconds = Column(Integer)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
