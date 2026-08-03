"""Activation of a correlation-AI recommendation (migration 061, FS-406).

An analysis session ends with a list of recommended actions. Until now that list was
decoration: the UI drew a green tick beside each line and the only way to act was an
"Auto-integrate" checkbox that fired a background job whose outcome never came back — it
could create nothing and the screen looked identical.

`InsightActivation` is the record that a person acted on one, and it is joined to two things
that carry the proof:

    the Kanban task it created           -> `task_id`
    every external system it must reach  -> `SystemOfRecordPosting` rows (060) keyed by
                                            (event_type='insight_activation', event_id=self.id)

Reusing the floor-event ledger is deliberate. Dispatching to an ERP is the same class of
claim whether a machinist issuing a part or an analysis session started it, so it earns the
same rule: `posted` is impossible without the identifier the far system returned, and
`manual_required` is impossible without the sentence to read out to a person.

CONFIRMATION IS A SNAPSHOT, NOT A FLAG. `validation` stores the per-posting statuses and
references that were true when confirmation was granted, and the database refuses a
`confirmed` row without one. So a reader six months later can check the confirmation rather
than take it on faith — which is the whole difference between this and a boolean.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from app.core.datetime_utils import utcnow
from app.db.models import Base, UUIDColumn, UUIDForeignKey


class ActivationStatus:
    """`issued` means work exists, NOT that anything is done.

    The distinction is the reason this table exists. The old behaviour reported success at
    the moment of asking, which is precisely when the least is known.
    """

    ISSUED = "issued"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

    ALL = (ISSUED, CONFIRMED, REJECTED, CANCELLED)
    #: Still needs somebody to finish or decide.
    OPEN = (ISSUED,)


class ActivationSource:
    """Where the recommendation came from.

    Correlation sessions are the first producer, but a strategic recommendation and a
    correlation alert are the same shape of thing, and giving them a value now keeps the
    fingerprint scheme stable when they are wired in.
    """

    ANALYSIS_SESSION = "analysis_session"
    CORRELATION_ALERT = "correlation_alert"
    STRATEGIC_RECOMMENDATION = "strategic_recommendation"
    MANUAL = "manual"

    ALL = (
        ANALYSIS_SESSION, CORRELATION_ALERT, STRATEGIC_RECOMMENDATION, MANUAL,
    )


class InsightActivation(Base):
    """One recommendation a person chose to act on."""

    __tablename__ = "insight_activations"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", index=True)

    #: Nullable, and ON DELETE SET NULL in the migration: archiving a session must not erase
    #: the audit trail of work that really happened because of it.
    session_id = UUIDForeignKey("analysis_sessions.id", nullable=True, ondelete="SET NULL")
    message_id = UUIDForeignKey("session_messages.id", nullable=True, ondelete="SET NULL")
    source = Column(String(40), nullable=False, default=ActivationSource.ANALYSIS_SESSION)
    #: Position in the message's `actions` array, so the UI can mark the exact line as
    #: activated rather than matching on title text.
    action_index = Column(Integer)
    #: sha256 over (source, session, message, index, title), unique per organisation. This is
    #: what makes Activate idempotent: a double click or a retry after a timeout returns the
    #: existing activation instead of raising a second work order and a second ERP posting.
    action_fingerprint = Column(String(64), nullable=False, index=True)

    title = Column(String(500), nullable=False)
    description = Column(Text)
    #: The correlation domain (e.g. MAINTENANCE, QUALITY_CONTROL). Decides which systems of
    #: record the activation has to reach.
    domain = Column(String(100))
    priority = Column(String(20), nullable=False, default="medium")

    #: The Kanban task. NULL only when task creation failed — a state the API reports rather
    #: than papers over, because an activation with no task is an insight nobody will do.
    task_id = UUIDForeignKey("tasks.id", nullable=True, ondelete="SET NULL")

    status = Column(String(20), nullable=False, default=ActivationStatus.ISSUED, index=True)

    issued_by = UUIDForeignKey("users.id", nullable=True, ondelete="SET NULL")
    issued_at = Column(DateTime(timezone=True), default=utcnow)
    confirmed_by = UUIDForeignKey("users.id", nullable=True, ondelete="SET NULL")
    confirmed_at = Column(DateTime(timezone=True))
    rejected_by = UUIDForeignKey("users.id", nullable=True, ondelete="SET NULL")
    rejected_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)

    #: The evidence confirmation was granted on. See the module docstring.
    validation = Column(JSON)
    meta_data = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def is_open(self) -> bool:
        return self.status in ActivationStatus.OPEN
