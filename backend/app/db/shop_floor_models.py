"""Shop-floor events and the ledger of what each one reached (migration 060, FS-405).

Four things happen on a factory floor that every other system needs to know about:

    a part is issued        -> inventory, purchasing, accounting
    time is clocked         -> production, accounting
    a problem is found      -> quality, inventory, production, accounting
    a machine goes down     -> scheduling, production, quality, accounting

None of them existed in this schema. The platform could READ an ERP — inbound sync,
webhooks, correlation over the result — and could not record a single floor event, and
`ERPConnectorBase` has no write method at all. Every tie-in was one-directional.

WHY THE LEDGER IS A SEPARATE TABLE, and why it is the important half. Each of those arrows
is an independent claim: issuing a part can reach inventory, be queued for accounting, and
be waiting on a human for purchasing, all at once. A `synced` boolean would collapse three
outcomes into one bit, and the bit would be a lie — which is the defect class this
repository keeps finding, from an alert that was logged instead of dispatched (and returned
an identifier anyway) to a compliance report stating four figures it never computed.

`SystemOfRecordPosting` therefore carries one row per (event, target system), each with its
own status. The database enforces the part that matters: a posting cannot say `posted`
without an `external_ref` and a `posted_at` — evidence from the far system — and cannot say
`manual_required` without an instruction for the person who has to be told.

MANUAL IS A REAL OUTCOME. Plenty of shops have no purchasing API, and the correct behaviour
is to tell someone. `manual_required` is the analog path made explicit, so "nobody was told"
and "the integration is down" stay distinguishable — different problems, different fixes.
"""

from __future__ import annotations

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text,
)
from sqlalchemy.orm import relationship

from app.core.datetime_utils import utcnow
from app.db.models import Base, UUIDColumn, UUIDForeignKey, UUIDString


# --------------------------------------------------------------------------- target systems
class TargetSystem:
    """The systems of record a floor event can be required to reach.

    Not an Enum column: a deployment may route to a system this list does not name, and a
    CHECK constraint on the target would make that unrecordable. The value is validated
    against this list at the API boundary, where a caller can be told what is accepted.
    """

    INVENTORY = "inventory"
    PURCHASING = "purchasing"
    ACCOUNTING = "accounting"
    PRODUCTION = "production"
    QUALITY = "quality"
    SCHEDULING = "scheduling"
    MAINTENANCE = "maintenance"

    ALL = (INVENTORY, PURCHASING, ACCOUNTING, PRODUCTION, QUALITY, SCHEDULING, MAINTENANCE)


class PostingStatus:
    """`pending` is "not tried yet"; `failed` is "tried and it did not work".

    Keeping those apart is the difference between a queue to drain and an incident to
    investigate, and a single `success: bool` cannot express either.
    """

    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
    MANUAL_REQUIRED = "manual_required"
    NOT_APPLICABLE = "not_applicable"

    ALL = (PENDING, POSTED, FAILED, MANUAL_REQUIRED, NOT_APPLICABLE)
    #: Statuses that still need somebody to do something.
    OUTSTANDING = (PENDING, FAILED, MANUAL_REQUIRED)


class EventType:
    PART_ISSUE = "part_issue"
    LABOR_ENTRY = "labor_entry"
    QUALITY_EVENT = "quality_event"
    DOWNTIME_EVENT = "downtime_event"
    #: A correlation-AI recommendation a person chose to act on (061, FS-406). It shares the
    #: posting ledger with the four floor events on purpose: a dispatch to an ERP is the same
    #: kind of claim whether a machinist or an analysis session started it, so it earns the
    #: same evidence. Its targets come from the insight's domain rather than from ROUTING,
    #: which is why it is absent from that table and passed explicitly to `fan_out`.
    INSIGHT_ACTIVATION = "insight_activation"

    ALL = (PART_ISSUE, LABOR_ENTRY, QUALITY_EVENT, DOWNTIME_EVENT, INSIGHT_ACTIVATION)


# ------------------------------------------------------------------------------ part issues
class PartIssue(Base):
    """A part taken from stock and put on a job or a machine."""

    __tablename__ = "part_issues"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", index=True)
    #: Declared purely so the unit of work can ORDER inserts (FS-408). SQLAlchemy builds its
    #: insert ordering from relationships, not from ForeignKey columns, so a model with only
    #: the column can be flushed before its parent — a foreign key violation on Postgres that
    #: SQLite cannot see, because it does not enforce FKs by default. That is what broke
    #: seed_demo_data.py. `lazy="raise"` because nothing should traverse it: it exists for
    #: ordering, and an accidental lazy load in async code is a MissingGreenlet at runtime.
    organization = relationship("Organization", lazy="raise")
    part_number = Column(String(100), nullable=False, index=True)
    description = Column(Text)
    quantity = Column(Numeric, nullable=False)
    unit_of_measure = Column(String(20), nullable=False, default="each")

    #: All optional. A part can go to a machine, to a work order, or to neither
    #: (consumables) — requiring one would make the honest cases unrecordable.
    asset_id = UUIDForeignKey("assets.id", nullable=True, ondelete="SET NULL")
    work_order_ref = Column(String(100), index=True)

    #: NULL means "not priced yet", which is normal — costing usually resolves in the ERP.
    #: Deliberately NOT defaulted to 0: "free" and "not yet known" are different, and a 0 in
    #: an accounting feed is a claim somebody will reconcile against.
    unit_cost = Column(Numeric)
    currency = Column(String(3))

    issued_by = UUIDForeignKey("users.id", nullable=True, ondelete="SET NULL")
    issued_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reason = Column(String(50), nullable=False, default="production")
    notes = Column(Text)
    meta_data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def extended_cost(self):
        """quantity x unit_cost, or None when the cost is not known.

        None rather than 0, for the same reason `unit_cost` is nullable: this figure feeds
        an accounting posting, and a zero there is a statement that the issue cost nothing.
        """
        if self.unit_cost is None or self.quantity is None:
            return None
        return float(self.quantity) * float(self.unit_cost)


# ---------------------------------------------------------------------------- labour entries
class LaborEntry(Base):
    """One clock-in/clock-out span."""

    __tablename__ = "labor_entries"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", index=True)
    #: Declared purely so the unit of work can ORDER inserts (FS-408). SQLAlchemy builds its
    #: insert ordering from relationships, not from ForeignKey columns, so a model with only
    #: the column can be flushed before its parent — a foreign key violation on Postgres that
    #: SQLite cannot see, because it does not enforce FKs by default. That is what broke
    #: seed_demo_data.py. `lazy="raise"` because nothing should traverse it: it exists for
    #: ordering, and an accidental lazy load in async code is a MissingGreenlet at runtime.
    organization = relationship("Organization", lazy="raise")

    user_id = UUIDForeignKey("users.id", nullable=True, ondelete="SET NULL")
    #: A shop floor has staff without platform logins. Without this the time clock would
    #: only work for people who happen to have an account, which is not who runs a machine.
    operator_ref = Column(String(100), index=True)

    asset_id = UUIDForeignKey("assets.id", nullable=True, ondelete="SET NULL")
    work_order_ref = Column(String(100), index=True)

    clock_in_at = Column(DateTime(timezone=True), nullable=False)
    #: NULL while the clock is running. The open entry is the whole point of a time clock.
    clock_out_at = Column(DateTime(timezone=True))
    #: Fixed at clock-out and stored rather than recomputed on read: an accounting posting
    #: must not change retroactively because a timestamp was later corrected.
    duration_minutes = Column(Numeric)

    labor_category = Column(String(50), nullable=False, default="direct")
    notes = Column(Text)
    meta_data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def is_open(self) -> bool:
        return self.clock_out_at is None


# ---------------------------------------------------------------------------- quality events
class QualityEvent(Base):
    """A problem found on the floor: a defect, a scrap, a rework, a hold."""

    __tablename__ = "quality_events"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", index=True)
    #: Declared purely so the unit of work can ORDER inserts (FS-408). SQLAlchemy builds its
    #: insert ordering from relationships, not from ForeignKey columns, so a model with only
    #: the column can be flushed before its parent — a foreign key violation on Postgres that
    #: SQLite cannot see, because it does not enforce FKs by default. That is what broke
    #: seed_demo_data.py. `lazy="raise"` because nothing should traverse it: it exists for
    #: ordering, and an accidental lazy load in async code is a MissingGreenlet at runtime.
    organization = relationship("Organization", lazy="raise")
    asset_id = UUIDForeignKey("assets.id", nullable=True, ondelete="SET NULL")
    work_order_ref = Column(String(100), index=True)
    part_number = Column(String(100), index=True)

    event_type = Column(String(50), nullable=False, default="defect")
    severity = Column(String(20), nullable=False, default="minor")
    description = Column(Text, nullable=False)
    quantity_affected = Column(Numeric)
    disposition = Column(String(50))
    #: Scrap is what makes this an INVENTORY and ACCOUNTING event rather than only a quality
    #: one — the stock is gone and somebody pays for it. Nullable because disposition is
    #: usually decided after the event is raised.
    scrap_quantity = Column(Numeric)

    reported_by = UUIDForeignKey("users.id", nullable=True, ondelete="SET NULL")
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------- downtime events
class DowntimeEvent(Base):
    """A machine not running, planned or otherwise."""

    __tablename__ = "downtime_events"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", index=True)
    #: Declared purely so the unit of work can ORDER inserts (FS-408). SQLAlchemy builds its
    #: insert ordering from relationships, not from ForeignKey columns, so a model with only
    #: the column can be flushed before its parent — a foreign key violation on Postgres that
    #: SQLite cannot see, because it does not enforce FKs by default. That is what broke
    #: seed_demo_data.py. `lazy="raise"` because nothing should traverse it: it exists for
    #: ordering, and an accidental lazy load in async code is a MissingGreenlet at runtime.
    organization = relationship("Organization", lazy="raise")
    asset_id = UUIDForeignKey("assets.id", ondelete="CASCADE")

    #: planned | unplanned | changeover | maintenance
    downtime_type = Column(String(30), nullable=False, default="unplanned")
    reason_code = Column(String(50), index=True)
    description = Column(Text)

    started_at = Column(DateTime(timezone=True), nullable=False)
    #: NULL while the machine is still down — the state an operator most needs to see.
    ended_at = Column(DateTime(timezone=True))
    duration_minutes = Column(Numeric)
    maintenance_ref = Column(String(100))

    reported_by = UUIDForeignKey("users.id", nullable=True, ondelete="SET NULL")
    meta_data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def is_open(self) -> bool:
        return self.ended_at is None


# ----------------------------------------------------------------------------- the ledger
class SystemOfRecordPosting(Base):
    """One row per (floor event, system that must hear about it).

    THE CONSTRAINTS ARE IN THE DATABASE ON PURPOSE (migration 060). `status = 'posted'`
    requires an `external_ref` and a `posted_at`, because the identifier the far system
    returns is the only evidence the posting actually landed — and a service-layer check
    only holds for the writers that exist today.
    """

    __tablename__ = "system_of_record_postings"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", index=True)
    #: Declared purely so the unit of work can ORDER inserts (FS-408). SQLAlchemy builds its
    #: insert ordering from relationships, not from ForeignKey columns, so a model with only
    #: the column can be flushed before its parent — a foreign key violation on Postgres that
    #: SQLite cannot see, because it does not enforce FKs by default. That is what broke
    #: seed_demo_data.py. `lazy="raise"` because nothing should traverse it: it exists for
    #: ordering, and an accidental lazy load in async code is a MissingGreenlet at runtime.
    organization = relationship("Organization", lazy="raise")

    event_type = Column(String(30), nullable=False, index=True)
    #: UUIDString, not String(36). Migration 060 makes this a native `uuid`, and a text
    #: ORM column against a uuid database column breaks binds on Postgres — the drift
    #: `test_schema_parity` exists for, and which it caught here. No FK: it points at
    #: whichever table `event_type` names.
    event_id = Column(UUIDString(), nullable=False, index=True)
    target_system = Column(String(30), nullable=False, index=True)

    status = Column(String(20), nullable=False, default=PostingStatus.PENDING, index=True)
    integration_id = Column(
        UUIDString(), ForeignKey("integration_configurations.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Evidence. Without it, `posted` is an assertion nobody can check.
    external_ref = Column(String(200))

    #: For `manual_required`: exactly what a human has to be told. This is the analog path —
    #: a supervisor reading a line off a screen and telling a stores clerk.
    instruction = Column(Text)
    acknowledged_by = UUIDForeignKey("users.id", nullable=True, ondelete="SET NULL")
    acknowledged_at = Column(DateTime(timezone=True))

    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)
    posted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def is_outstanding(self) -> bool:
        return self.status in PostingStatus.OUTSTANDING
