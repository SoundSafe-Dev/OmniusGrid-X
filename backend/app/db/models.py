"""Database models"""

import uuid
from app.core.datetime_utils import utcnow
from typing import Optional, List
from sqlalchemy import Column, String, DateTime, Time, Boolean, Numeric, Float, JSON, ForeignKey, ForeignKeyConstraint, Text, BigInteger, Integer, ARRAY, Date, UUID, UniqueConstraint, CheckConstraint, Index, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

Base = declarative_base()


class UUIDString(TypeDecorator):
    """Dialect-aware UUID column: native ``uuid`` on Postgres, VARCHAR(36)
    elsewhere — reads and binds are ``str`` everywhere.

    History (FS-55): this used to be plain VARCHAR(36) on every dialect while
    ~13 newer tables hand-wrote native ``UUID(as_uuid=True)`` FK columns
    pointing at the VARCHAR PKs — cross-type FKs that Postgres rejects. The
    SQL migrations (001 etc.) always used native UUID, so the ORM now matches
    prod instead of fighting it.

    - binds: uuid.UUID or str accepted (FastAPI UUID params pass straight in;
      SQLite would otherwise raise "type 'UUID' is not supported").
    - reads: coerced to canonical dashed str on every dialect, so JSON
      serialization / dict keys keep their long-standing str assumption.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PGUUID
            return dialect.type_descriptor(PGUUID(as_uuid=False))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else None

    def process_result_value(self, value, dialect):
        # asyncpg's uuid codec can hand back uuid.UUID; normalize to str.
        return str(value) if value is not None else None


def StringListColumn(nullable: bool = False, default=None):
    """Use JSON for SQLite local dev; PostgreSQL ARRAY in production."""
    if settings.DATABASE_URL.startswith("sqlite"):
        kwargs = {"nullable": nullable}
        if default is not None:
            kwargs["default"] = default
        return Column(JSON, **kwargs)
    kwargs = {"nullable": nullable}
    if default is not None:
        kwargs["default"] = default
    return Column(ARRAY(String), **kwargs)

# Dialect-aware UUID column type (UUIDString: native uuid on PG, str reads).
def UUIDColumn():
    return Column(UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4()))

def UUIDForeignKey(foreign_key, nullable=False, ondelete=None, index=False,
                   use_alter=False):
    """A uuid FK column.

    `use_alter` breaks a MUTUAL reference. Two pairs here are genuinely circular — a trailer
    knows its dock door and a door knows its current trailer; a trailer knows its shipment
    and a shipment knows its trailer — and SQLAlchemy cannot topologically sort a cycle. It
    warns "Foreign key constraints involving these tables will not be considered", DISCARDS
    those constraints from the ordering, and says the warning "may raise an error in a future
    release". Discarding them also drags the cycle members' other edges out of the sort, which
    is why `dock_doors` sorted AHEAD of `organizations` — a table it references.

    Marking one side of each pair `use_alter` emits that constraint as a separate ALTER after
    both tables exist, which is the standard remedy and changes nothing about the resulting
    schema. The real schema comes from the migration chain regardless; this only affects
    metadata ordering and `create_all`, which the test suite uses everywhere.
    """
    return Column(
        UUIDString(),
        ForeignKey(foreign_key, ondelete=ondelete, use_alter=use_alter,
                   name=None if not use_alter else f"fk_{foreign_key.replace('.', '_')}_alter"),
        nullable=nullable,
        index=index,
    )


class Organization(Base):
    __tablename__ = "organizations"

    id = UUIDColumn()
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)
    settings = Column(JSON, default={})

    assets = relationship("Asset", back_populates="organization")


class AssetType(Base):
    __tablename__ = "asset_types"

    id = UUIDColumn()
    name = Column(String(100), nullable=False)
    category = Column(String(100), nullable=False)
    # Sensor taxonomy (migration 024): machinery | audio | video | environmental | generic.
    # Drives type-aware rendering (gauges vs waveform vs camera feed) and lets
    # downstream analytics filter by sensor modality.
    sensor_class = Column(String(50), default="generic")
    packml_config = Column(JSON, default={})
    telemetry_schema = Column(JSON, default={})
    action_space = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    
    assets = relationship("Asset", back_populates="asset_type")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_assets_id_org"),
        CheckConstraint(
            "("
            "agent_version_valid AND "
            "agent_version_major IS NOT NULL AND agent_version_major >= 0 AND "
            "agent_version_minor IS NOT NULL AND agent_version_minor >= 0 AND "
            "agent_version_patch IS NOT NULL AND agent_version_patch >= 0"
            ") OR ("
            "NOT agent_version_valid AND "
            "agent_version_major IS NULL AND "
            "agent_version_minor IS NULL AND "
            "agent_version_patch IS NULL AND "
            "agent_version_prerelease IS NULL"
            ")",
            name="ck_assets_agent_semver_components",
        ),
        ForeignKeyConstraint(
            ["workcell_id", "organization_id"],
            ["workcells.id", "workcells.organization_id"],
            ondelete="RESTRICT",
            name="fk_assets_workcell_org",
        ),
        Index(
            "idx_assets_org_agent_reported",
            "organization_id",
            "agent_id",
            "agent_reported_at",
            postgresql_where=text("agent_id IS NOT NULL"),
        ),
    )

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    workcell_id = UUIDForeignKey("workcells.id", nullable=False)  # NOT NULL since migration 013
    #: The third edge. `organization` and `asset_type` were declared and this was not,
    #: so an asset could still be flushed before its workcell (FS-408/410).
    workcell = relationship("Workcell", lazy="raise")
    asset_type_id = UUIDForeignKey("asset_types.id")
    name = Column(String(255), nullable=False)
    serial_number = Column(String(255))
    vendor = Column(String(100))
    model = Column(String(100))
    current_packml_state = Column(String(50), default="Idle")
    connection_config = Column(JSON, default={})
    # Sensor taxonomy (migration 024): per-asset override of the type's class,
    # plus media config for audio/video assets (e.g. {"stream_url": ..., "sample_rate": ...}).
    sensor_class = Column(String(50), nullable=True)
    media_config = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    # Operator override read by TacticalEngine._is_maintenance_mode to suppress control
    # commands. Added in migration 053 — the endpoint and the reader both predated the
    # column, so the write 500'd and the read failed safe, silently blocking everything.
    maintenance_mode = Column(Boolean, nullable=False, server_default=text("false"))
    last_seen = Column(DateTime(timezone=True))
    agent_id = Column(String(255))
    agent_version = Column(String(100))
    agent_config_hash = Column(String(64))
    agent_build_id = Column(String(255))
    agent_last_heartbeat = Column(DateTime(timezone=True))
    agent_reported_at = Column(DateTime(timezone=True))
    agent_version_valid = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    agent_version_major = Column(Integer)
    agent_version_minor = Column(Integer)
    agent_version_patch = Column(Integer)
    agent_version_prerelease = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)

    organization = relationship("Organization", back_populates="assets")
    asset_type = relationship("AssetType", back_populates="assets")


class PackMLState(Base):
    __tablename__ = "packml_states"
    
    id = UUIDColumn()
    asset_id = UUIDForeignKey("assets.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    asset = relationship("Asset", foreign_keys="PackMLState.asset_id", lazy="raise")
    state = Column(String(50), nullable=False)
    previous_state = Column(String(50))
    state_entered_at = Column(DateTime(timezone=True), nullable=False)
    state_exited_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Numeric)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Telemetry(Base):
    __tablename__ = "telemetry"

    time = Column(DateTime(timezone=True), primary_key=True)
    asset_id = Column(UUIDString(), ForeignKey("assets.id"), primary_key=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    asset = relationship("Asset", foreign_keys="Telemetry.asset_id", lazy="raise")
    metric_name = Column(String(100), primary_key=True)
    value = Column(Numeric, nullable=False)
    unit = Column(String(50))
    packml_state = Column(String(50))
    meta_data = Column("metadata", JSON, default={})
    sequence_num = Column(BigInteger)


class HistorianRetentionPolicy(Base):
    """Tenant and metric-specific historian retention and ingestion settings."""

    __tablename__ = "historian_retention_policies"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "metric_name",
            name="uq_historian_retention_org_metric",
        ),
        CheckConstraint(
            # trim() (not btrim) — identical semantics on Postgres AND SQLite, so
            # dev/offline-demo create_all works; migration 034 keeps btrim on PG.
            "length(trim(metric_name)) > 0",
            name="ck_historian_retention_metric",
        ),
        CheckConstraint(
            "hot_retention_days BETWEEN 1 AND 1825 "
            "AND warm_retention_days BETWEEN hot_retention_days AND 1825 "
            "AND cold_retention_days BETWEEN warm_retention_days AND 3650",
            name="ck_historian_retention_days",
        ),
        CheckConstraint(
            "ingestion_priority BETWEEN 1 AND 5",
            name="ck_historian_retention_priority",
        ),
        CheckConstraint(
            "ingestion_sample_rate > 0 AND ingestion_sample_rate <= 1",
            name="ck_historian_retention_sample_rate",
        ),
        CheckConstraint(
            "max_ingest_age_seconds BETWEEN 1 AND 86400",
            name="ck_historian_retention_max_age",
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_name = Column(String(100), nullable=False, default="*", server_default="*")
    hot_retention_days = Column(Integer, nullable=False, default=30, server_default="30")
    warm_retention_days = Column(Integer, nullable=False, default=365, server_default="365")
    cold_retention_days = Column(Integer, nullable=False, default=1825, server_default="1825")
    ingestion_priority = Column(Integer, nullable=False, default=3, server_default="3")
    ingestion_sample_rate = Column(Numeric(5, 4), nullable=False, default=1.0, server_default="1.0")
    max_ingest_age_seconds = Column(Integer, nullable=False, default=30, server_default="30")
    archival_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="HistorianRetentionPolicy.organization_id", lazy="raise")
    user = relationship("User", foreign_keys="HistorianRetentionPolicy.created_by", lazy="raise")
    created_at = Column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class Alarm(Base):
    __tablename__ = "alarms"

    id = UUIDColumn()
    asset_id = UUIDForeignKey("assets.id")
    # Added by migration 046 (FS-217). This table previously had NO tenant column,
    # so RLS could not protect it and tenancy depended entirely on every query
    # joining `assets` — five of six endpoints did not. Now RLS-enforced.
    organization_id = UUIDForeignKey("organizations.id")
    #: Ordering only (FS-408/410); see IntegrationConfiguration. Without it the unit of
    #: work can flush this row before the parent it references — a foreign key
    #: violation on Postgres that SQLite accepts silently.
    asset = relationship("Asset", lazy="raise")
    organization = relationship("Organization", lazy="raise")
    alarm_code = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    is_acknowledged = Column(Boolean, default=False)
    # UUID in migration 001; String(36) here bound text against a uuid column.
    # Not caught by the id-parity guard because the name has no _id suffix.
    acknowledged_by = Column(UUIDString())
    acknowledged_at = Column(DateTime(timezone=True))
    acknowledged_comment = Column(Text)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    cleared_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, default={})


class AlarmRule(Base):
    """An operator-defined threshold rule evaluated against incoming telemetry.

    Before this existed, alarm severity was whatever the edge agent sent and only
    the edge decided when an alarm existed at all — nothing on the server
    evaluated telemetry, so "alert when temperature > 80 for 5 minutes" was
    unexpressible. See app/services/alarm_rules.py for evaluation.

    Targeting is most-specific-wins across asset_id / asset_type_id /
    workcell_id; all three NULL means every asset in the organization.
    """

    __tablename__ = "alarm_rules"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", ondelete="CASCADE")

    name = Column(String(255), nullable=False)
    description = Column(Text)

    metric_name = Column(String(255), nullable=False)
    # One of gt/gte/lt/lte/eq/ne, enforced by a CHECK constraint in migration 047
    # so a typo cannot create a rule that silently never matches.
    comparator = Column(String(4), nullable=False)
    threshold = Column(Float, nullable=False)

    # 0 = fire on the first breaching sample. Anything higher requires the breach
    # to persist, which is why evaluation keeps per-(rule, asset) state.
    duration_seconds = Column(Integer, nullable=False, default=0)
    # Clear band in the metric's own units: the value must come back past the
    # threshold by this much before the breach counts as over, so a reading
    # sitting on the threshold does not flap on sensor noise.
    hysteresis = Column(Float, nullable=False, default=0.0)

    severity = Column(String(20), nullable=False)
    alarm_code = Column(String(100), nullable=False)
    message_template = Column(Text)

    asset_id = UUIDForeignKey("assets.id", nullable=True, ondelete="CASCADE")
    asset_type_id = UUIDForeignKey("asset_types.id", nullable=True, ondelete="CASCADE")
    workcell_id = UUIDForeignKey("workcells.id", nullable=True, ondelete="CASCADE")

    is_enabled = Column(Boolean, nullable=False, default=True)

    created_by = UUIDForeignKey("users.id", nullable=True, ondelete="SET NULL")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="AlarmRule.organization_id", lazy="raise")
    asset = relationship("Asset", foreign_keys="AlarmRule.asset_id", lazy="raise")
    asset_type = relationship("AssetType", foreign_keys="AlarmRule.asset_type_id", lazy="raise")
    workcell = relationship("Workcell", foreign_keys="AlarmRule.workcell_id", lazy="raise")
    user = relationship("User", foreign_keys="AlarmRule.created_by", lazy="raise")
    created_at = Column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )


class Operation(Base):
    __tablename__ = "operations"
    
    id = UUIDColumn()
    asset_id = UUIDForeignKey("assets.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    asset = relationship("Asset", foreign_keys="Operation.asset_id", lazy="raise")
    operation_name = Column(String(255), nullable=False)
    job_id = Column(String(255))
    status = Column(String(50), nullable=False)
    packml_state_durations = Column(JSON, default={})
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    # INTEGER (seconds) in migration 001 — Numeric here made reads return
    # Decimal for a column the schema stores as int4.
    planned_duration = Column(Integer)
    actual_duration = Column(Integer)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Workcell(Base):
    __tablename__ = "workcells"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_workcells_id_org"),
        ForeignKeyConstraint(
            ["site_id", "organization_id"],
            ["sites.id", "sites.organization_id"],
            name="fk_workcells_site_org",
        ),
    )
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    site_id = Column(UUIDString(), nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="Workcell.organization_id", lazy="raise")
    name = Column(String(255), nullable=False)
    description = Column(Text)
    location = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class Site(Base):
    """Tenant-owned physical site containing zero or more workcells."""

    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("organization_id", "key", name="uq_sites_org_key"),
        UniqueConstraint("organization_id", "name", name="uq_sites_org_name"),
        UniqueConstraint("id", "organization_id", name="uq_sites_id_org"),
        CheckConstraint("length(trim(key)) > 0", name="ck_sites_key_nonempty"),
        CheckConstraint("length(trim(name)) > 0", name="ck_sites_name_nonempty"),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    key = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class MaintenanceWindow(Base):
    """Tenant-owned recurring local-time dispatch window."""

    __tablename__ = "maintenance_windows"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_maintenance_windows_org_name",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_maintenance_windows_id_org",
        ),
        ForeignKeyConstraint(
            ["site_id", "organization_id"],
            ["sites.id", "sites.organization_id"],
            name="fk_maintenance_windows_site_org",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_maintenance_windows_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(timezone)) > 0",
            name="ck_maintenance_windows_timezone_nonempty",
        ),
        CheckConstraint(
            "jsonb_typeof(weekdays) = 'array' "
            "AND jsonb_array_length(weekdays) BETWEEN 1 AND 7 "
            "AND weekdays <@ '[0, 1, 2, 3, 4, 5, 6]'::jsonb",
            name="ck_maintenance_windows_weekdays",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "local_start_time <> local_end_time",
            name="ck_maintenance_windows_nonzero_duration",
        ),
        Index(
            "idx_maintenance_windows_org_site_enabled",
            "organization_id",
            "site_id",
            "enabled",
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    site_id = Column(UUIDString(), nullable=True)
    name = Column(String(255), nullable=False)
    timezone = Column(String(100), nullable=False)
    weekdays = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    local_start_time = Column(Time, nullable=False)
    local_end_time = Column(Time, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class AssetAgentCollector(Base):
    """Latest collector facts reported for one asset by its edge agent."""

    __tablename__ = "asset_agent_collectors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_id", "organization_id"],
            ["assets.id", "assets.organization_id"],
            ondelete="CASCADE",
            name="fk_asset_agent_collectors_asset_org",
        ),
        CheckConstraint(
            "length(trim(collector_type)) > 0",
            name="ck_asset_agent_collectors_type",
        ),
    )

    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = Column(UUIDString(), primary_key=True)
    collector_type = Column(String(100), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    running = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    heartbeat_at = Column(DateTime(timezone=True), nullable=False)


class FleetTag(Base):
    """Tenant-owned reusable asset label."""

    __tablename__ = "fleet_tags"
    __table_args__ = (
        UniqueConstraint("organization_id", "key", name="uq_fleet_tags_org_key"),
        UniqueConstraint("organization_id", "name", name="uq_fleet_tags_org_name"),
        UniqueConstraint("id", "organization_id", name="uq_fleet_tags_id_org"),
        CheckConstraint("length(trim(key)) > 0", name="ck_fleet_tags_key_nonempty"),
        CheckConstraint("length(trim(name)) > 0", name="ck_fleet_tags_name_nonempty"),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    key = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    color = Column(String(32))
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class AssetFleetTag(Base):
    """Many-to-many tenant-safe asset/tag assignment."""

    __tablename__ = "asset_fleet_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_id", "organization_id"],
            ["assets.id", "assets.organization_id"],
            ondelete="CASCADE",
            name="fk_asset_fleet_tags_asset_org",
        ),
        ForeignKeyConstraint(
            ["tag_id", "organization_id"],
            ["fleet_tags.id", "fleet_tags.organization_id"],
            ondelete="CASCADE",
            name="fk_asset_fleet_tags_tag_org",
        ),
    )

    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = Column(UUIDString(), primary_key=True)
    tag_id = Column(UUIDString(), primary_key=True)
    assigned_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class FleetGroup(Base):
    """Tenant-owned explicit fleet group."""

    __tablename__ = "fleet_groups"
    __table_args__ = (
        UniqueConstraint("organization_id", "key", name="uq_fleet_groups_org_key"),
        UniqueConstraint("organization_id", "name", name="uq_fleet_groups_org_name"),
        UniqueConstraint("id", "organization_id", name="uq_fleet_groups_id_org"),
        CheckConstraint("length(trim(key)) > 0", name="ck_fleet_groups_key_nonempty"),
        CheckConstraint("length(trim(name)) > 0", name="ck_fleet_groups_name_nonempty"),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    key = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class AssetFleetGroup(Base):
    """Many-to-many tenant-safe asset/group membership."""

    __tablename__ = "asset_fleet_groups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_id", "organization_id"],
            ["assets.id", "assets.organization_id"],
            ondelete="CASCADE",
            name="fk_asset_fleet_groups_asset_org",
        ),
        ForeignKeyConstraint(
            ["group_id", "organization_id"],
            ["fleet_groups.id", "fleet_groups.organization_id"],
            ondelete="CASCADE",
            name="fk_asset_fleet_groups_group_org",
        ),
    )

    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = Column(UUIDString(), primary_key=True)
    group_id = Column(UUIDString(), primary_key=True)
    assigned_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class FleetCohort(Base):
    """Saved validated dynamic targeting query."""

    __tablename__ = "fleet_cohorts"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_fleet_cohorts_org_name"),
        UniqueConstraint("id", "organization_id", name="uq_fleet_cohorts_id_org"),
        CheckConstraint("length(trim(name)) > 0", name="ck_fleet_cohorts_name_nonempty"),
        CheckConstraint("query_version = 1", name="ck_fleet_cohorts_query_version"),
        CheckConstraint(
            "jsonb_typeof(query) = 'object'",
            name="ck_fleet_cohorts_query_object",
        ).ddl_if(dialect="postgresql"),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text)
    query_version = Column(Integer, nullable=False, default=1, server_default="1")
    query = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


# ==================== YMS Models ====================

class YardTrailer(Base):
    """Trailer inventory in the yard"""
    __tablename__ = "yard_trailers"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    trailer_number = Column(String(50), nullable=False)
    carrier_id = UUIDForeignKey("carriers.id", nullable=True)
    trailer_type = Column(String(50))  # dry_van, reefer, flatbed, etc.
    status = Column(String(50), default="checked_in")  # checked_in, docked, yard, checked_out
    yard_location = Column(String(100))  # grid position or zone
    seal_number = Column(String(50))
    seal_status = Column(String(20), default="intact")  # intact, broken, missing
    weight_lbs = Column(Numeric)
    # migration 042 — fleet UI columns
    license_plate = Column(String(32))
    detention_cost = Column(Float)
    detention_risk = Column(String(20))  # low, medium, high
    check_in_at = Column(DateTime(timezone=True), default=utcnow)
    check_out_at = Column(DateTime(timezone=True))
    dock_door_id = UUIDForeignKey("dock_doors.id", nullable=True)
    driver_id = UUIDForeignKey("drivers.id", nullable=True)
    #: Cycle-breaker: shipments.trailer_id points back here. See UUIDForeignKey.
    shipment_id = UUIDForeignKey("shipments.id", nullable=True, use_alter=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="YardTrailer.organization_id", lazy="raise")
    carrier = relationship("Carrier", foreign_keys="YardTrailer.carrier_id", lazy="raise")
    driver = relationship("Driver", foreign_keys="YardTrailer.driver_id", lazy="raise")
    temperature_setpoint = Column(Numeric)  # for reefers
    temperature_actual = Column(Numeric)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class DockDoor(Base):
    """Dock door scheduling and status"""
    __tablename__ = "dock_doors"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    door_number = Column(String(50), nullable=False)
    door_type = Column(String(50))  # inbound, outbound, cross_dock
    status = Column(String(50), default="available")  # available, occupied, maintenance
    equipment_capabilities = Column(JSON, default={})  # forklift, pallet_jack, etc.
    #: Cycle-breaker: yard_trailers.dock_door_id points back here. See UUIDForeignKey.
    current_trailer_id = UUIDForeignKey("yard_trailers.id", nullable=True, use_alter=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="DockDoor.organization_id", lazy="raise")
    last_occupied_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class YardMove(Base):
    """Jockey/yard truck movements"""
    __tablename__ = "yard_moves"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    trailer_id = UUIDForeignKey("yard_trailers.id", nullable=True)
    from_location = Column(String(100), nullable=False)
    to_location = Column(String(100), nullable=False)
    move_type = Column(String(50))  # check_in, dock, yard_relocate, check_out
    jockey_driver_id = UUIDForeignKey("drivers.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="YardMove.organization_id", lazy="raise")
    yard_trailer = relationship("YardTrailer", foreign_keys="YardMove.trailer_id", lazy="raise")
    driver = relationship("Driver", foreign_keys="YardMove.jockey_driver_id", lazy="raise")
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Numeric)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)


class DriverWaitTime(Base):
    """Track driver detention/wait times"""
    __tablename__ = "driver_wait_times"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    driver_id = UUIDForeignKey("drivers.id", nullable=True)
    trailer_id = UUIDForeignKey("yard_trailers.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="DriverWaitTime.organization_id", lazy="raise")
    driver = relationship("Driver", foreign_keys="DriverWaitTime.driver_id", lazy="raise")
    yard_trailer = relationship("YardTrailer", foreign_keys="DriverWaitTime.trailer_id", lazy="raise")
    check_in_at = Column(DateTime(timezone=True), nullable=False)
    docked_at = Column(DateTime(timezone=True))
    unloaded_at = Column(DateTime(timezone=True))
    check_out_at = Column(DateTime(timezone=True))
    total_wait_minutes = Column(Numeric)
    detention_minutes = Column(Numeric)  # billable detention time
    demurrage_minutes = Column(Numeric)  # billable demurrage time
    detention_rate = Column(Numeric)  # hourly rate
    demurrage_rate = Column(Numeric)
    detention_charge = Column(Numeric)  # calculated charge
    demurrage_charge = Column(Numeric)
    is_billed = Column(Boolean, default=False)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class YardCheckPoint(Base):
    """Gate and checkpoint tracking"""
    __tablename__ = "yard_checkpoints"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    trailer_id = UUIDForeignKey("yard_trailers.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="YardCheckPoint.organization_id", lazy="raise")
    yard_trailer = relationship("YardTrailer", foreign_keys="YardCheckPoint.trailer_id", lazy="raise")
    checkpoint_type = Column(String(50), nullable=False)  # gate_in, guard_shack, weigh_station, gate_out
    checkpoint_name = Column(String(100))
    passed_at = Column(DateTime(timezone=True), default=utcnow)
    weight_lbs = Column(Numeric)
    inspection_status = Column(String(50))  # passed, failed, pending
    inspector_id = Column(String(36))
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ==================== TMS Models ====================

class Carrier(Base):
    """Carrier profiles and compliance"""
    __tablename__ = "carriers"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="Carrier.organization_id", lazy="raise")
    carrier_name = Column(String(255), nullable=False)
    dot_number = Column(String(50))
    mc_number = Column(String(50))
    ctpat_certified = Column(Boolean, default=False)
    ctpat_expires_at = Column(DateTime(timezone=True))
    insurance_on_file = Column(Boolean, default=False)
    insurance_expires_at = Column(DateTime(timezone=True))
    safety_rating = Column(String(20))  # satisfactory, conditional, unsatisfactory
    csa_score = Column(Numeric)
    contract_rate = Column(JSON, default={})  # negotiated rates
    # migration 042 — fleet UI columns
    compliance_score = Column(Float)  # 0-100
    on_time_performance = Column(Float)  # 0-1
    operating_authority = Column(String(50))  # common, contract
    scac = Column(String(8))  # Standard Carrier Alpha Code (4 letters)
    is_active = Column(Boolean, default=True)
    contact_info = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class Driver(Base):
    """Driver profiles and HOS compliance"""
    __tablename__ = "drivers"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    carrier_id = UUIDForeignKey("carriers.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="Driver.organization_id", lazy="raise")
    carrier = relationship("Carrier", foreign_keys="Driver.carrier_id", lazy="raise")
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    license_number = Column(String(100))
    license_state = Column(String(50))
    cdl_class = Column(String(20))  # A, B, C
    hazmat_endorsed = Column(Boolean, default=False)
    medical_cert_expires = Column(DateTime(timezone=True))
    dq_file_complete = Column(Boolean, default=False)  # Driver Qualification file
    current_hos_status = Column(String(50))  # on_duty, driving, off_duty, sleeper
    hos_drive_hours_today = Column(Numeric, default=0)
    hos_on_duty_hours_today = Column(Numeric, default=0)
    hos_cycle_hours = Column(Numeric, default=0)
    # migration 042 — fleet UI columns
    endorsements = Column(JSON, default=list)  # e.g. ["hazmat", "tanker"]
    license_expiry = Column(DateTime(timezone=True))
    hos_drive_hours_remaining = Column(Float)  # 11 - hos_drive_hours_today
    hos_duty_hours_remaining = Column(Float)  # 14 - hos_on_duty_hours_today
    eld_device_id = Column(String(100))
    phone = Column(String(50))
    email = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class Shipment(Base):
    """Shipment lifecycle tracking"""
    __tablename__ = "shipments"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    #: Ordering only (FS-408/410). Deliberately NOT declaring `trailer`: that FK is one
    #: side of the shipments <-> yard_trailers cycle broken with use_alter, and a mapper
    #: relationship would reintroduce the cycle one layer up.
    organization = relationship("Organization", lazy="raise")
    carrier_id = UUIDForeignKey("carriers.id", nullable=True)
    driver_id = UUIDForeignKey("drivers.id", nullable=True)
    trailer_id = UUIDForeignKey("yard_trailers.id", nullable=True)
    shipment_number = Column(String(100), nullable=False)
    pro_number = Column(String(100))  # Progressive Rotating Order
    bol_number = Column(String(100))  # Bill of Lading
    shipment_type = Column(String(50))  # inbound, outbound, transfer
    status = Column(String(50), default="planned")  # planned, dispatched, in_transit, delivered, cancelled
    origin = Column(JSON, default={})
    destination = Column(JSON, default={})
    scheduled_pickup = Column(DateTime(timezone=True))
    actual_pickup = Column(DateTime(timezone=True))
    scheduled_delivery = Column(DateTime(timezone=True))
    actual_delivery = Column(DateTime(timezone=True))
    priority = Column(String(20), default="normal")  # low, normal, high, critical
    total_weight_lbs = Column(Numeric)
    total_pieces = Column(Integer)
    # migration 042 — fleet UI columns
    po_number = Column(String(100))
    freight_charge = Column(Float)
    pallet_count = Column(Integer)
    hazmat = Column(Boolean, default=False)
    temperature_required = Column(Boolean, default=False)
    temperature_min = Column(Numeric)
    temperature_max = Column(Numeric)
    route_id = UUIDForeignKey("routes.id", nullable=True)
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class Route(Base):
    """Optimized routes for shipments"""
    __tablename__ = "routes"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="Route.organization_id", lazy="raise")
    route_name = Column(String(255))
    origin = Column(JSON, default={}, nullable=False)
    destination = Column(JSON, default={}, nullable=False)
    waypoints = Column(JSON, default=[])
    total_distance_miles = Column(Numeric)
    estimated_duration_hours = Column(Numeric)
    fuel_cost_estimate = Column(Numeric)
    toll_cost_estimate = Column(Numeric)
    optimization_criteria = Column(String(50))  # fastest, cheapest, balanced
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class LoadPlan(Base):
    """Product-to-trailer load planning"""
    __tablename__ = "load_plans"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    shipment_id = UUIDForeignKey("shipments.id", nullable=True)
    trailer_id = UUIDForeignKey("yard_trailers.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="LoadPlan.organization_id", lazy="raise")
    shipment = relationship("Shipment", foreign_keys="LoadPlan.shipment_id", lazy="raise")
    yard_trailer = relationship("YardTrailer", foreign_keys="LoadPlan.trailer_id", lazy="raise")
    planned_by = Column(String(36))
    planned_at = Column(DateTime(timezone=True), default=utcnow)
    load_sequence = Column(JSON, default=[])  # order of loading
    weight_distribution = Column(JSON, default={})  # axle weights
    space_utilization_percent = Column(Numeric)
    temperature_zones = Column(JSON, default=[])  # multi-temp loads
    special_instructions = Column(Text)
    is_executed = Column(Boolean, default=False)
    executed_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class FreightCharge(Base):
    """Freight billing and charges"""
    __tablename__ = "freight_charges"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    shipment_id = UUIDForeignKey("shipments.id", nullable=True)
    carrier_id = UUIDForeignKey("carriers.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="FreightCharge.organization_id", lazy="raise")
    shipment = relationship("Shipment", foreign_keys="FreightCharge.shipment_id", lazy="raise")
    carrier = relationship("Carrier", foreign_keys="FreightCharge.carrier_id", lazy="raise")
    charge_type = Column(String(50), nullable=False)  # linehaul, fuel, detention, demurrage, accessorial
    charge_description = Column(String(255))
    rate_basis = Column(String(50))  # per_mile, per_pound, flat, hourly
    quantity = Column(Numeric)
    rate = Column(Numeric)
    amount = Column(Numeric, nullable=False)
    currency = Column(String(10), default="USD")
    is_billed = Column(Boolean, default=False)
    billed_at = Column(DateTime(timezone=True))
    invoice_number = Column(String(100))
    approved_by = Column(String(36))
    approved_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


# ==================== Correlation Models ====================

class DockAppointment(Base):
    """Link dock schedules to production"""
    __tablename__ = "dock_appointments"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    dock_door_id = UUIDForeignKey("dock_doors.id", nullable=True)
    trailer_id = UUIDForeignKey("yard_trailers.id", nullable=True)
    shipment_id = UUIDForeignKey("shipments.id", nullable=True)
    operation_id = UUIDForeignKey("operations.id", nullable=True)  # linked production job
    appointment_type = Column(String(50))  # pickup, delivery, transfer
    scheduled_start = Column(DateTime(timezone=True), nullable=False)
    scheduled_end = Column(DateTime(timezone=True), nullable=False)
    actual_start = Column(DateTime(timezone=True))
    actual_end = Column(DateTime(timezone=True))
    status = Column(String(50), default="scheduled")  # scheduled, in_progress, completed, cancelled, no_show
    carrier_id = UUIDForeignKey("carriers.id", nullable=True)
    driver_id = UUIDForeignKey("drivers.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="DockAppointment.organization_id", lazy="raise")
    dock_door = relationship("DockDoor", foreign_keys="DockAppointment.dock_door_id", lazy="raise")
    yard_trailer = relationship("YardTrailer", foreign_keys="DockAppointment.trailer_id", lazy="raise")
    shipment = relationship("Shipment", foreign_keys="DockAppointment.shipment_id", lazy="raise")
    operation = relationship("Operation", foreign_keys="DockAppointment.operation_id", lazy="raise")
    carrier = relationship("Carrier", foreign_keys="DockAppointment.carrier_id", lazy="raise")
    driver = relationship("Driver", foreign_keys="DockAppointment.driver_id", lazy="raise")
    priority = Column(String(20), default="normal")
    compliance_required = Column(Boolean, default=False)  # FDA, etc.
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class TruckAssetCorrelation(Base):
    """Correlate truck arrivals with manufacturing asset readiness"""
    __tablename__ = "truck_asset_correlations"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    shipment_id = UUIDForeignKey("shipments.id", nullable=True)
    trailer_id = UUIDForeignKey("yard_trailers.id", nullable=True)
    asset_id = UUIDForeignKey("assets.id")
    operation_id = UUIDForeignKey("operations.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="TruckAssetCorrelation.organization_id", lazy="raise")
    shipment = relationship("Shipment", foreign_keys="TruckAssetCorrelation.shipment_id", lazy="raise")
    yard_trailer = relationship("YardTrailer", foreign_keys="TruckAssetCorrelation.trailer_id", lazy="raise")
    asset = relationship("Asset", foreign_keys="TruckAssetCorrelation.asset_id", lazy="raise")
    operation = relationship("Operation", foreign_keys="TruckAssetCorrelation.operation_id", lazy="raise")
    truck_arrived_at = Column(DateTime(timezone=True))
    asset_ready_at = Column(DateTime(timezone=True))
    asset_completion_forecast = Column(DateTime(timezone=True))
    readiness_gap_minutes = Column(Numeric)  # positive = truck waiting, negative = asset waiting
    load_start_at = Column(DateTime(timezone=True))
    load_complete_at = Column(DateTime(timezone=True))
    detention_incurred = Column(Boolean, default=False)
    detention_charge = Column(Numeric)
    efficiency_score = Column(Numeric)  # 0-100 based on synchronization
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)


class LoadQualityLog(Base):
    """Track shipping defects and correlate to manufacturing"""
    __tablename__ = "load_quality_logs"
    
    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    shipment_id = UUIDForeignKey("shipments.id", nullable=True)
    trailer_id = UUIDForeignKey("yard_trailers.id", nullable=True)
    asset_id = UUIDForeignKey("assets.id")  # source asset
    operation_id = UUIDForeignKey("operations.id", nullable=True)
    defect_type = Column(String(100))  # wrong_product, damaged, short, over, temp_excursion
    severity = Column(String(20))  # minor, major, critical
    quantity_affected = Column(Numeric)
    root_cause_asset = UUIDForeignKey("assets.id")
    root_cause_operation = UUIDForeignKey("operations.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="LoadQualityLog.organization_id", lazy="raise")
    shipment = relationship("Shipment", foreign_keys="LoadQualityLog.shipment_id", lazy="raise")
    yard_trailer = relationship("YardTrailer", foreign_keys="LoadQualityLog.trailer_id", lazy="raise")
    asset = relationship("Asset", foreign_keys="LoadQualityLog.asset_id", lazy="raise")
    operation = relationship("Operation", foreign_keys="LoadQualityLog.operation_id", lazy="raise")
    manufacturing_correlation_score = Column(Numeric)  # confidence of manufacturing root cause
    carrier_liable = Column(Boolean, default=False)
    claim_filed = Column(Boolean, default=False)
    claim_amount = Column(Numeric)
    resolved_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class User(Base):
    """User authentication and authorization"""
    __tablename__ = "users"

    id = UUIDColumn()
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    organization_id = UUIDForeignKey("organizations.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="User.organization_id", lazy="raise")
    # Vocabulary + ordering: app/core/roles.py. Migration 048 adds a CHECK
    # constraint and a server default — an unconstrained role column let a
    # typo store fine and then match no require_* dependency, so the account
    # silently had no permissions instead of failing at the point of the typo.
    role = Column(
        String(50), nullable=False, default="operator", server_default="operator"
    )
    department = Column(String(100))
    priorities = Column(JSON, default=[])
    user_context = Column(JSON, default={})
    user_goals = Column(JSON, default=[])
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class UserInvitation(Base):
    """One-time tenant invitation whose raw bearer token is never persisted."""

    __tablename__ = "user_invitations"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_user_invitations_id_org",
        ),
        CheckConstraint(
            "length(trim(normalized_email)) > 0",
            name="ck_user_invitations_email_nonempty",
        ),
        CheckConstraint(
            "requested_role IN ('admin', 'operator', 'viewer')",
            name="ck_user_invitations_role",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="ck_user_invitations_status",
        ),
        CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'failed')",
            name="ck_user_invitations_delivery_status",
        ),
        CheckConstraint(
            "delivery_attempts >= 0",
            name="ck_user_invitations_delivery_attempts",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_user_invitations_expiry",
        ),
        Index(
            "uq_user_invitations_pending_org_email",
            "organization_id",
            "normalized_email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "idx_user_invitations_org_status_created",
            "organization_id",
            "status",
            text("created_at DESC"),
        ),
        Index(
            "idx_user_invitations_pending_expiry",
            "expires_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_email = Column(String(320), nullable=False)
    requested_role = Column(String(50), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    delivery_status = Column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    delivery_attempts = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    last_delivery_attempt_at = Column(DateTime(timezone=True))
    delivered_at = Column(DateTime(timezone=True))
    delivery_error_code = Column(String(100))
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    accepted_user_id = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    accepted_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class Command(Base):
    """Command execution log for actionable decisions"""
    __tablename__ = "commands"
    __table_args__ = (
        CheckConstraint(
            "timeout_seconds > 0",
            name="ck_commands_timeout_seconds_positive",
        ),
        CheckConstraint(
            "dispatch_attempts >= 0",
            name="ck_commands_dispatch_attempts_nonnegative",
        ),
        Index(
            "idx_commands_dispatch_ready",
            "organization_id",
            "next_dispatch_at",
            "issued_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "idx_commands_ack_deadline",
            "organization_id",
            "deadline_at",
            postgresql_where=text(
                "status = 'executing' AND deadline_at IS NOT NULL"
            ),
        ),
    )

    id = UUIDColumn()
    asset_id = UUIDForeignKey("assets.id")
    command_type = Column(String(50), nullable=False)
    action_id = Column(String(255), nullable=False)
    parameters = Column(JSON, default=dict)
    status = Column(String(50), default="pending")  # pending, executing, completed, failed, cancelled
    priority = Column(String(20), default="normal")  # low, normal, high, critical
    timeout_seconds = Column(Integer, nullable=False, default=60)
    dispatch_attempts = Column(Integer, nullable=False, default=0)
    next_dispatch_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    dispatched_at = Column(DateTime(timezone=True))
    deadline_at = Column(DateTime(timezone=True))
    last_dispatch_error = Column(Text)
    issued_at = Column(DateTime(timezone=True), default=utcnow)
    issued_by = UUIDForeignKey("users.id", nullable=True)
    executed_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    result = Column(JSON, default=dict)
    error_message = Column(Text)
    organization_id = UUIDForeignKey("organizations.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    asset = relationship("Asset", foreign_keys="Command.asset_id", lazy="raise")
    user = relationship("User", foreign_keys="Command.issued_by", lazy="raise")
    organization = relationship("Organization", foreign_keys="Command.organization_id", lazy="raise")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ==================== Kanban Task Management Models ====================

class TaskBoard(Base):
    """Unified kanban board configuration per organization"""
    __tablename__ = "task_boards"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="TaskBoard.organization_id", lazy="raise")
    name = Column(String(255), nullable=False, default="Main Operations Board")
    board_type = Column(String(50), default="unified")  # unified, production, maintenance, quality, safety, logistics
    default_view_config = Column(JSON, default={
        "default_filter": "all",
        "default_group_by": None,
        "show_wip_limits": True,
        "show_completed": False
    })
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class TaskColumn(Base):
    """Kanban columns (swimlanes) - standard 6 columns"""
    __tablename__ = "task_columns"

    id = UUIDColumn()
    board_id = UUIDForeignKey("task_boards.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    task_board = relationship("TaskBoard", foreign_keys="TaskColumn.board_id", lazy="raise")
    name = Column(String(100), nullable=False)
    position = Column(Integer, nullable=False)  # order in board
    wip_limit = Column(Integer, default=5)  # max tasks allowed
    column_type = Column(String(50), nullable=False)  # backlog, triage, in_progress, review, rejected, done
    color = Column(String(7), default="#6366F1")  # hex color
    is_collapsed = Column(Boolean, default=False)
    auto_archive_days = Column(Integer, default=7)  # auto-archive tasks after N days in Done
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class Task(Base):
    """Central work item for actionable decision-making"""
    __tablename__ = "tasks"

    id = UUIDColumn()
    board_id = UUIDForeignKey("task_boards.id")
    column_id = UUIDForeignKey("task_columns.id")
    position = Column(Integer, default=0)  # order within column

    # Basic info
    title = Column(String(500), nullable=False)
    description = Column(Text)
    task_type = Column(String(50), nullable=False)  # production_job, maintenance_pm, maintenance_cm, quality_inspection, safety_check, alarm_response, command_execution, material_request, changeover, custom
    priority = Column(String(20), default="medium")  # low, medium, high, critical, emergency
    status = Column(String(50), default="draft")  # draft, ready, in_progress, blocked, completed, cancelled

    # Assignments
    assigned_to = UUIDForeignKey("users.id", nullable=True)
    assigned_by = UUIDForeignKey("users.id", nullable=True)
    assigned_at = Column(DateTime(timezone=True))

    # Scheduling
    planned_start = Column(DateTime(timezone=True))
    planned_duration = Column(Integer)  # minutes
    due_date = Column(DateTime(timezone=True))
    actual_start = Column(DateTime(timezone=True))
    actual_end = Column(DateTime(timezone=True))

    # Relationships to OmniusGrid entities
    asset_id = UUIDForeignKey("assets.id", nullable=True)
    operation_id = UUIDForeignKey("operations.id", nullable=True)
    # UUIDString, not String(36): migrations 003/004 create both of these as
    # native UUID, so the ORM was declaring text against uuid columns — the
    # pre-032 drift class, where binds and joins fail on real Postgres while
    # SQLite create_all hides it. UUIDString still reads and binds as str, so
    # nothing Python-side changes.
    alarm_id = Column(UUIDString())
    command_id = Column(String(255))  # Command ID (string format), text in the DB too
    work_order_id = Column(UUIDString())
    parent_task_id = UUIDForeignKey("tasks.id", nullable=True)
    rule_id = UUIDForeignKey("task_rules.id", nullable=True)  # Rule that created this task

    # Progress tracking
    progress_percent = Column(Integer, default=0)  # 0-100
    time_logged_minutes = Column(Integer, default=0)
    estimated_effort_minutes = Column(Integer)

    # Metadata
    tags = Column(JSON, default=list)
    custom_fields = Column(JSON, default=dict)
    checklist_items = Column(JSON, default=list)  # [{"text": "...", "completed": true}]
    color_code = Column(String(7))  # hex

    # Approval workflow
    approval_status = Column(String(50), default="pending")  # pending, approved, rejected
    approved_by = UUIDForeignKey("users.id", nullable=True)  # see the audit block below
    approved_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)

    # Completion actions (bidirectional integration)
    completion_actions = Column(JSON, default=dict)  # { "clear_alarm": true, "execute_command": {...} }
    completion_result = Column(JSON, default=dict)  # Log of what actions were taken

    # Audit
    #: nullable=True on all three of these matches the database. Migrations 003/004 create
    #: `created_by`, `approved_by` and `completed_by` as plain `UUID REFERENCES users(id)`
    #: with no NOT NULL, and they cannot be otherwise — a task is created before anyone
    #: completes it. The ORM claimed NOT NULL, which Postgres never enforced (nullable is a
    #: DDL property, not a client-side check), so the claim was invisible in production and
    #: wrong everywhere the schema is built FROM the ORM: `create_all` then emits a stricter
    #: table than the real one and rejects inserts that production accepts.
    created_by = UUIDForeignKey("users.id", nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True))
    completed_by = UUIDForeignKey("users.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    task_board = relationship("TaskBoard", foreign_keys="Task.board_id", lazy="raise")
    task_column = relationship("TaskColumn", foreign_keys="Task.column_id", lazy="raise")
    user = relationship("User", foreign_keys="Task.assigned_to", lazy="raise")
    asset = relationship("Asset", foreign_keys="Task.asset_id", lazy="raise")
    operation = relationship("Operation", foreign_keys="Task.operation_id", lazy="raise")
    task_rule = relationship("TaskRule", foreign_keys="Task.rule_id", lazy="raise")


class TaskComment(Base):
    """Activity feed for tasks"""
    __tablename__ = "task_comments"

    id = UUIDColumn()
    task_id = UUIDForeignKey("tasks.id")
    user_id = UUIDForeignKey("users.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    task = relationship("Task", foreign_keys="TaskComment.task_id", lazy="raise")
    user = relationship("User", foreign_keys="TaskComment.user_id", lazy="raise")
    comment_type = Column(String(50), default="comment")  # comment, system, time_log, status_change, approval_action
    content = Column(Text)
    extra_data = Column(JSON, default=dict)  # { "before_state": "...", "after_state": "..." }
    created_at = Column(DateTime(timezone=True), default=utcnow)


class TaskTimer(Base):
    """Time tracking for tasks"""
    __tablename__ = "task_timers"

    id = UUIDColumn()
    task_id = UUIDForeignKey("tasks.id")
    user_id = UUIDForeignKey("users.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    task = relationship("Task", foreign_keys="TaskTimer.task_id", lazy="raise")
    user = relationship("User", foreign_keys="TaskTimer.user_id", lazy="raise")
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True))
    duration_minutes = Column(Integer, default=0)
    is_running = Column(Boolean, default=True)
    description = Column(Text)  # What was done during this time
    created_at = Column(DateTime(timezone=True), default=utcnow)


class TaskRule(Base):
    """Rules registry for automated task creation"""
    __tablename__ = "task_rules"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    rule_name = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    is_system_rule = Column(Boolean, default=False)  # Premade vs custom

    # Trigger conditions
    trigger_type = Column(String(100), nullable=False)  # alarm_created, alarm_cleared, packml_state_change, oee_threshold, telemetry_threshold, scheduled_time, operation_completed, command_failed, maintenance_due
    trigger_conditions = Column(JSON, default=dict)  # { "severity": "critical", "asset_type": "3d_printer" }

    # Task template
    target_board_id = UUIDForeignKey("task_boards.id")
    target_column_id = UUIDForeignKey("task_columns.id")
    task_template = Column(JSON, default=dict)  # { "title": "...", "description": "...", "priority": "high", "task_type": "alarm_response" }

    # Automation settings
    auto_approve_emergency = Column(Boolean, default=False)
    auto_approve_timeout_minutes = Column(Integer, default=30)
    assignee_rule = Column(String(50), default="asset_owner")  # round_robin, asset_owner, supervisor, specific_user
    specific_assignee_id = UUIDForeignKey("users.id")
    notify_users = Column(JSON, default=list)  # User IDs to notify

    # Completion actions
    completion_actions = Column(JSON, default=dict)

    # Escalation config
    escalation_config = Column(JSON, default=dict)  # { "levels": [{"time_minutes": 15, "level": 1, "channels": ["push", "email"]}] }

    # Audit
    created_by = UUIDForeignKey("users.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="TaskRule.organization_id", lazy="raise")
    task_board = relationship("TaskBoard", foreign_keys="TaskRule.target_board_id", lazy="raise")
    task_column = relationship("TaskColumn", foreign_keys="TaskRule.target_column_id", lazy="raise")
    user = relationship("User", foreign_keys="TaskRule.specific_assignee_id", lazy="raise")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class TaskEscalation(Base):
    """Escalation log for tasks"""
    __tablename__ = "task_escalations"

    id = UUIDColumn()
    task_id = UUIDForeignKey("tasks.id")
    rule_id = UUIDForeignKey("task_rules.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    task = relationship("Task", foreign_keys="TaskEscalation.task_id", lazy="raise")
    task_rule = relationship("TaskRule", foreign_keys="TaskEscalation.rule_id", lazy="raise")
    escalation_level = Column(Integer, nullable=False)  # 1-5
    triggered_at = Column(DateTime(timezone=True), default=utcnow)
    resolved_at = Column(DateTime(timezone=True))
    notified_users = Column(JSON, default=list)  # User IDs notified
    actions_taken = Column(JSON, default=list)  # ["email_sent", "sms_sent", "reassigned"]
    notification_channels = Column(JSON, default=list)  # ["push", "email", "sms"]
    created_at = Column(DateTime(timezone=True), default=utcnow)


class ActionableRegistry(Base):
    """Actionable registries for compliance and operational requirements"""
    __tablename__ = "actionable_registries"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    registry_name = Column(String(255), nullable=False)  # e.g., "OSHA 1910.147", "ISO 9001:2015"
    registry_type = Column(String(50), nullable=False)  # safety, quality, environmental, operational, regulatory
    registry_category = Column(String(100))  # sub-category within type
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    is_compliance = Column(Boolean, default=False)  # true for compliance registries (OSHA, ISO), false for operational
    frequency = Column(String(50))  # daily, weekly, monthly, quarterly, annually, as_needed
    next_due_date = Column(DateTime(timezone=True))
    last_completed_date = Column(DateTime(timezone=True))
    compliance_score = Column(Integer, default=0)  # 0-100
    priority_level = Column(String(20), default="medium")  # low, medium, high, critical
    assigned_owner_id = UUIDForeignKey("users.id")
    assigned_team_id = Column(UUIDString())  # team reference if applicable
    reference_url = Column(String(500))  # link to official documentation
    checklist_requirements = Column(JSON, default=list)  # [{id, requirement, completed, notes}]
    meta_data = Column(JSON, default=dict)
    created_by = UUIDForeignKey("users.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ActionableRegistry.organization_id", lazy="raise")
    user = relationship("User", foreign_keys="ActionableRegistry.assigned_owner_id", lazy="raise")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class ActionableRegistryItem(Base):
    """Individual actionable items within a registry"""
    __tablename__ = "actionable_registry_items"

    id = UUIDColumn()
    registry_id = UUIDForeignKey("actionable_registries.id")
    item_code = Column(String(100), nullable=False)  # e.g., "1910.147(a)(1)"
    item_name = Column(String(255), nullable=False)
    item_description = Column(Text)
    severity_level = Column(String(20), default="medium")  # low, medium, high, critical
    is_active = Column(Boolean, default=True)
    is_required = Column(Boolean, default=True)
    completion_criteria = Column(Text)
    verification_method = Column(String(255))  # inspection, test, documentation, audit
    estimated_effort_minutes = Column(Integer)
    related_task_id = UUIDForeignKey("tasks.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    actionable_registry = relationship("ActionableRegistry", foreign_keys="ActionableRegistryItem.registry_id", lazy="raise")
    task = relationship("Task", foreign_keys="ActionableRegistryItem.related_task_id", lazy="raise")
    last_completed_at = Column(DateTime(timezone=True))
    next_due_at = Column(DateTime(timezone=True))
    completion_frequency = Column(String(50))  # daily, weekly, monthly, quarterly, annually
    compliance_score = Column(Integer, default=0)  # 0-100
    risk_score = Column(Integer, default=0)  # 0-100, calculated based on severity and overdue status
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class DataCorrelation(Base):
    """Data correlation mapping for tasks and actionable items"""
    __tablename__ = "data_correlations"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id")
    correlation_type = Column(String(50), nullable=False)  # task_to_registry, task_to_asset, task_to_alarm, registry_to_asset
    source_type = Column(String(50), nullable=False)  # task, registry_item, asset, alarm, operation
    source_id = Column(UUIDString())
    target_type = Column(String(50), nullable=False)  # task, registry_item, asset, alarm, operation
    target_id = Column(UUIDString())
    correlation_strength = Column(Integer, default=50)  # 0-100, strength of correlation
    correlation_method = Column(String(50), default="manual")  # manual, automated, ai_suggested
    confidence_score = Column(Integer, default=0)  # 0-100, confidence in correlation
    is_active = Column(Boolean, default=True)
    is_bidirectional = Column(Boolean, default=False)
    correlation_meta_data = Column(JSON, default=dict)  # additional context
    created_by = UUIDForeignKey("users.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="DataCorrelation.organization_id", lazy="raise")
    user = relationship("User", foreign_keys="DataCorrelation.created_by", lazy="raise")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


# ==================== NLP Analysis Session Models ====================

class AnalysisSession(Base):
    """Analysis sessions for NLP correlation AI"""
    __tablename__ = "analysis_sessions"

    id = UUIDColumn()
    user_id = UUIDForeignKey("users.id")
    organization_id = UUIDForeignKey("organizations.id")
    #: Ordering only (FS-408/410) — see IntegrationConfiguration for the full reasoning.
    #: Without these the unit of work can flush a session before the user and organisation
    #: it belongs to, which real Postgres rejects and SQLite accepts. `lazy="raise"` so an
    #: accidental traversal is a clear error rather than a MissingGreenlet in async code.
    user = relationship("User", lazy="raise")
    organization = relationship("Organization", lazy="raise")
    title = Column(String(500), nullable=False)
    description = Column(Text)
    status = Column(String(50), default="active")  # active, archived, deleted
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)
    last_accessed_at = Column(DateTime(timezone=True), default=utcnow)
    context_snapshot = Column(JSON, default=dict)  # User context snapshot at session creation
    goals_snapshot = Column(JSON, default=dict)  # User goals snapshot at session creation
    meta_data = Column(JSON, default=dict)


class SessionDataSource(Base):
    """Data sources used in analysis sessions"""
    __tablename__ = "session_data_sources"

    id = UUIDColumn()
    session_id = UUIDForeignKey("analysis_sessions.id")
    #: Ordering only (FS-408/410); see IntegrationConfiguration. Without it the unit
    #: of work can flush a row before the session it belongs to.
    session = relationship("AnalysisSession", lazy="raise")
    source_type = Column(String(50), nullable=False)  # intake, upload, system
    source_id = Column(String(36))  # ID from source table (intake_id, etc.)
    file_name = Column(String(255))
    data_type = Column(String(50))  # spreadsheet, report, image, document
    processed_data = Column(JSON, default=dict)
    added_at = Column(DateTime(timezone=True), default=utcnow)
    meta_data = Column(JSON, default=dict)


class SessionMessage(Base):
    """Chat messages with session context"""
    __tablename__ = "session_messages"

    id = UUIDColumn()
    session_id = UUIDForeignKey("analysis_sessions.id")
    #: Ordering only (FS-408/410); see IntegrationConfiguration. Without it the unit
    #: of work can flush a row before the session it belongs to.
    session = relationship("AnalysisSession", lazy="raise")
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    analysis = Column(JSON, default=dict)  # AI analysis result
    risk_score = Column(Numeric)
    domains = Column(JSON, default=list)  # List of domains analyzed
    actions = Column(JSON, default=list)  # Recommended actions
    timestamp = Column(DateTime(timezone=True), default=utcnow)
    context_used = Column(JSON, default=dict)  # Context snapshot used for this message
    meta_data = Column(JSON, default=dict)


class IntakeItem(Base):
    """Intake Inbox items for NLP correlation AI analysis"""
    __tablename__ = "intake_items"

    id = UUIDColumn()
    user_id = UUIDForeignKey("users.id")
    organization_id = UUIDForeignKey("organizations.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    user = relationship("User", foreign_keys="IntakeItem.user_id", lazy="raise")
    organization = relationship("Organization", foreign_keys="IntakeItem.organization_id", lazy="raise")
    title = Column(String(255), nullable=False)
    description = Column(Text)
    data_type = Column(String(50))  # spreadsheet, report, image, document
    category = Column(String(100), default="general")
    file_name = Column(String(255))
    file_content = Column(Text)  # Base64 encoded or file path
    processed_data = Column(JSON, default={})
    status = Column(String(50), default="pending")  # pending, analyzing, analyzed, error
    analysis_result = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)
    analyzed_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON, default=dict)


# ==================== GeoTab Integration Models ====================

class GeoTabTrip(Base):
    """GeoTab trip data for fleet tracking"""
    __tablename__ = "geotab_trips"
    # Latest-trip-per-device is the hot lookup (location webhook + fleet map).
    __table_args__ = (
        Index("ix_geotab_trips_device_start", "device_id", "start_time"),
    )

    id = UUIDColumn()
    device_id = Column(String(100), nullable=False, index=True)
    driver_id = UUIDForeignKey("drivers.id", nullable=True)
    vehicle_id = Column(String(100))  # VIN or internal vehicle ID
    organization_id = UUIDForeignKey("organizations.id", nullable=True)
    #: Ordering only (FS-408/410); see IntegrationConfiguration.
    organization = relationship("Organization", lazy="raise")
    
    # Trip timing
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    
    # Location data
    start_location = Column(JSON)  # {latitude, longitude, address}
    end_location = Column(JSON)  # {latitude, longitude, address}
    distance_miles = Column(Numeric(10, 2), nullable=True)
    
    # Trip details
    start_odometer = Column(Numeric(10, 2))
    end_odometer = Column(Numeric(10, 2))
    idle_time_seconds = Column(Integer, default=0)
    
    # Status
    status = Column(String(50), default="active")  # active, completed, cancelled
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class GeoTabDiagnostic(Base):
    """GeoTab vehicle diagnostic trouble codes"""
    __tablename__ = "geotab_diagnostics"

    id = UUIDColumn()
    device_id = Column(String(100), nullable=False, index=True)
    vehicle_id = Column(String(100))
    organization_id = UUIDForeignKey("organizations.id", nullable=True)
    #: Ordering only (FS-408/410); see IntegrationConfiguration. Without it the unit of
    #: work can flush this row before the parent it references — a foreign key
    #: violation on Postgres that SQLite accepts silently.
    organization = relationship("Organization", lazy="raise")
    
    # Diagnostic data
    dtc_code = Column(String(20), nullable=False)  # e.g., "P0115"
    severity = Column(String(20), default="medium")  # low, medium, high, critical
    description = Column(Text)
    
    # Status
    status = Column(String(50), default="active")  # active, cleared, resolved
    first_seen_at = Column(DateTime(timezone=True), default=utcnow)
    last_seen_at = Column(DateTime(timezone=True), default=utcnow)
    cleared_at = Column(DateTime(timezone=True), nullable=True)
    
    # Additional vehicle health data
    battery_voltage = Column(Numeric(5, 2))
    fuel_level = Column(Numeric(5, 2))
    odometer = Column(BigInteger)
    engine_hours = Column(Numeric(10, 2))
    
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class GeoTabException(Base):
    """GeoTab exception events (speeding, harsh braking, HOS violations)"""
    __tablename__ = "geotab_exceptions"

    id = UUIDColumn()
    device_id = Column(String(100), nullable=False, index=True)
    driver_id = UUIDForeignKey("drivers.id", nullable=True)
    organization_id = UUIDForeignKey("organizations.id", nullable=True)
    #: Ordering only (FS-408/410); see IntegrationConfiguration.
    organization = relationship("Organization", lazy="raise")
    
    # Exception details
    exception_type = Column(String(50), nullable=False)  # harsh_braking, speeding, hos_violation, idle_time, seat_belt
    severity = Column(String(20), default="medium")  # low, medium, high, critical
    
    # Event data
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    location = Column(JSON)  # {latitude, longitude, address}
    
    # Exception-specific data
    details = Column(JSON)  # {value, threshold, duration, etc.}
    
    # Processing status
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = UUIDForeignKey("users.id", nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Security audit log for tracking sensitive operations with tamper-evident hash chaining"""
    __tablename__ = "audit_logs"

    id = UUIDColumn()
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    user_id = UUIDForeignKey("users.id", nullable=True)
    organization_id = UUIDForeignKey("organizations.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    user = relationship("User", foreign_keys="AuditLog.user_id", lazy="raise")
    organization = relationship("Organization", foreign_keys="AuditLog.organization_id", lazy="raise")
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(UUID(as_uuid=True), nullable=True)  # Polymorphic UUID resource
    details = Column(JSON, default={}, nullable=False)
    # Migrations 001/009 create this as INET. Declared as VARCHAR here, every
    # insert bound $n::VARCHAR and Postgres rejected it with
    # 'column "ip_address" is of type inet but expression is of type character
    # varying' — and audit_trail swallows the failure as `audit_log_failed`, so
    # the audit trail has been silently empty on real deployments while every
    # write appeared to succeed. VARCHAR(45) is kept for SQLite, which has no
    # inet type.
    ip_address = Column(String(45).with_variant(INET, "postgresql"), nullable=True)
    user_agent = Column(Text, nullable=True)
    hash_chain = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class ExportTemplate(Base):
    """Reusable, tenant-owned export configuration."""
    __tablename__ = "export_templates"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_export_templates_org_name"),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text)
    export_type = Column(String(50), nullable=False)
    export_format = Column(String(10), nullable=False)
    columns = Column(
        JSON().with_variant(JSONB, "postgresql"),
        default=list,
        server_default="[]",
        nullable=False,
    )
    filters = Column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
        server_default="{}",
        nullable=False,
    )
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ExportTemplate.organization_id", lazy="raise")
    user = relationship("User", foreign_keys="ExportTemplate.created_by", lazy="raise")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class ScheduledExport(Base):
    """Persisted schedule definition for durable report delivery."""
    __tablename__ = "scheduled_exports"
    __table_args__ = (
        CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly')",
            name="ck_scheduled_exports_frequency",
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id = Column(
        UUIDString(),
        ForeignKey("export_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    frequency = Column(String(20), nullable=False)
    timezone = Column(String(100), nullable=False, default="UTC")
    next_run_at = Column(DateTime(timezone=True), nullable=False)
    recipients = Column(
        JSON().with_variant(JSONB, "postgresql"),
        default=list,
        server_default="[]",
        nullable=False,
    )
    is_active = Column(Boolean, nullable=False, default=False)
    last_run_at = Column(DateTime(timezone=True))
    last_status = Column(String(50), default="never_run")
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ScheduledExport.organization_id", lazy="raise")
    export_template = relationship("ExportTemplate", foreign_keys="ScheduledExport.template_id", lazy="raise")
    user = relationship("User", foreign_keys="ScheduledExport.created_by", lazy="raise")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class ExportDeliveryJob(Base):
    """Transactional outbox record consumed by the Redpanda export worker."""
    __tablename__ = "export_delivery_jobs"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "scheduled_for",
            name="uq_export_delivery_jobs_schedule_run",
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    schedule_id = Column(
        UUIDString(),
        ForeignKey("scheduled_exports.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id = Column(
        UUIDString(),
        ForeignKey("export_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ExportDeliveryJob.organization_id", lazy="raise")
    scheduled_export = relationship("ScheduledExport", foreign_keys="ExportDeliveryJob.schedule_id", lazy="raise")
    export_template = relationship("ExportTemplate", foreign_keys="ExportDeliveryJob.template_id", lazy="raise")
    user = relationship("User", foreign_keys="ExportDeliveryJob.requested_by", lazy="raise")
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(30), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    file_path = Column(Text)
    filename = Column(String(255))
    error = Column(Text)
    published_at = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class APIKey(Base):
    """API keys for external integrations"""
    __tablename__ = "api_keys"

    id = UUIDColumn()
    key_hash = Column(String(64), nullable=False, unique=True)
    key_prefix = Column(String(8), nullable=False)
    name = Column(String(255), nullable=False)
    organization_id = UUIDForeignKey("organizations.id", nullable=True)
    scopes = StringListColumn(nullable=False, default=lambda: ["read"])
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    created_by = UUIDForeignKey("users.id", nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by = UUIDForeignKey("users.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="APIKey.organization_id", lazy="raise")
    user = relationship("User", foreign_keys="APIKey.created_by", lazy="raise")
    meta_data = Column(JSON, default={})


class UserSession(Base):
    """User session management"""
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("uq_user_sessions_jti", "jti", unique=True),
    )

    id = UUIDColumn()
    user_id = UUIDForeignKey("users.id", nullable=False)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    user = relationship("User", foreign_keys="UserSession.user_id", lazy="raise")
    token_hash = Column(String(64), nullable=False, unique=True)
    jti = Column(UUID(as_uuid=True), nullable=False)
    token_type = Column(String(20), nullable=False, default="refresh")
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    last_activity_at = Column(DateTime(timezone=True), default=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(String(100), nullable=True)
    replaced_by_jti = Column(UUID(as_uuid=True), nullable=True)
    meta_data = Column("metadata", JSON().with_variant(JSONB, "postgresql"), default=dict)


class RevokedToken(Base):
    """Durable local-JWT denylist shared by every backend replica."""

    __tablename__ = "revoked_tokens"
    __table_args__ = (
        Index("idx_revoked_tokens_expires_at", "expires_at"),
        Index("idx_revoked_tokens_user_id", "user_id"),
    )

    id = UUIDColumn()
    jti = Column(UUID(as_uuid=True), nullable=False, unique=True)
    user_id = UUIDForeignKey("users.id", nullable=False)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    user = relationship("User", foreign_keys="RevokedToken.user_id", lazy="raise")
    user_session = relationship("UserSession", foreign_keys="RevokedToken.session_id", lazy="raise")
    token_type = Column(String(20), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reason = Column(String(100), nullable=True)
    meta_data = Column("metadata", JSON().with_variant(JSONB, "postgresql"), default=dict)


class ConsentRecord(Base):
    """GDPR consent records"""
    __tablename__ = "consent_records"

    id = UUIDColumn()
    user_id = UUIDForeignKey("users.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    user = relationship("User", foreign_keys="ConsentRecord.user_id", lazy="raise")
    consent_type = Column(String(50), nullable=False)
    consent_given = Column(Boolean, nullable=False)
    consent_date = Column(DateTime(timezone=True), default=utcnow)
    consent_method = Column(String(50), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    withdrawn_at = Column(DateTime(timezone=True), nullable=True)
    meta_data = Column(JSON, default={})


class DataProcessingRecord(Base):
    """GDPR data processing records"""
    __tablename__ = "data_processing_records"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="DataProcessingRecord.organization_id", lazy="raise")
    processing_activity = Column(String(255), nullable=False)
    data_categories = StringListColumn(nullable=False)
    purposes = StringListColumn(nullable=False)
    recipients = StringListColumn(nullable=True)
    retention_period = Column(String(100), nullable=True)
    security_measures = StringListColumn(nullable=True)
    legal_basis = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SecurityAsset(Base):
    """ISO 27001 security assets"""
    __tablename__ = "security_assets"

    id = UUIDColumn()
    asset_type = Column(String(50), nullable=False)
    asset_name = Column(String(255), nullable=False)
    asset_id = Column(String(255), nullable=True)
    owner_id = UUIDForeignKey("users.id", nullable=True)
    organization_id = UUIDForeignKey("organizations.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    user = relationship("User", foreign_keys="SecurityAsset.owner_id", lazy="raise")
    organization = relationship("Organization", foreign_keys="SecurityAsset.organization_id", lazy="raise")
    classification = Column(String(50), nullable=True)
    location = Column(String(255), nullable=True)
    status = Column(String(50), default="active")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    meta_data = Column(JSON, default={})


class VendorRiskAssessment(Base):
    """SOC 2 vendor risk assessments"""
    __tablename__ = "vendor_risk_assessments"

    id = UUIDColumn()
    vendor_name = Column(String(255), nullable=False)
    vendor_type = Column(String(50), nullable=True)
    risk_level = Column(String(50), nullable=True)
    assessment_date = Column(Date, nullable=True)
    next_review_date = Column(Date, nullable=True)
    assessor_id = UUIDForeignKey("users.id", nullable=True)
    organization_id = UUIDForeignKey("organizations.id")

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    user = relationship("User", foreign_keys="VendorRiskAssessment.assessor_id", lazy="raise")
    organization = relationship("Organization", foreign_keys="VendorRiskAssessment.organization_id", lazy="raise")
    findings = StringListColumn(nullable=True)
    controls = StringListColumn(nullable=True)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ScheduledComplianceReport(Base):
    """Persisted schedule for automated compliance report generation."""
    __tablename__ = "scheduled_compliance_reports"
    __table_args__ = (
        CheckConstraint(
            "framework IN ('all', 'gdpr', 'soc2', 'iso27001')",
            name="ck_scheduled_compliance_reports_framework",
        ),
        CheckConstraint(
            "format IN ('json', 'pdf')",
            name="ck_scheduled_compliance_reports_format",
        ),
        CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly', 'quarterly', 'annually')",
            name="ck_scheduled_compliance_reports_frequency",
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    framework = Column(String(20), nullable=False)
    format = Column(String(10), nullable=False)
    frequency = Column(String(20), nullable=False)
    timezone = Column(String(100), nullable=False, default="UTC", server_default="UTC")
    next_run_at = Column(DateTime(timezone=True), nullable=False)
    recipients = Column(
        JSON().with_variant(JSONB, "postgresql"),
        default=list,
        server_default="[]",
        nullable=False,
    )
    is_active = Column(Boolean, nullable=False, default=False, server_default="false")
    last_run_at = Column(DateTime(timezone=True))
    last_status = Column(
        String(50), nullable=False, default="never_run", server_default="never_run"
    )
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ScheduledComplianceReport.organization_id", lazy="raise")
    user = relationship("User", foreign_keys="ScheduledComplianceReport.created_by", lazy="raise")
    created_at = Column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class ComplianceReportJob(Base):
    """Durable outbox for async compliance report generation and delivery."""
    __tablename__ = "compliance_report_jobs"
    __table_args__ = (
        CheckConstraint(
            "framework IN ('all', 'gdpr', 'soc2', 'iso27001')",
            name="ck_compliance_report_jobs_framework",
        ),
        CheckConstraint(
            "format IN ('json', 'pdf')",
            name="ck_compliance_report_jobs_format",
        ),
        CheckConstraint(
            "report_status IN "
            "('queued', 'publishing', 'published', 'running', 'completed', 'failed')",
            name="ck_compliance_report_jobs_report_status",
        ),
        CheckConstraint(
            "delivery_status IN ('pending', 'sending', 'sent', 'failed', 'skipped')",
            name="ck_compliance_report_jobs_delivery_status",
        ),
        UniqueConstraint(
            "schedule_id",
            "scheduled_for",
            name="uq_compliance_report_jobs_schedule_run",
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    schedule_id = Column(
        UUIDString(),
        ForeignKey("scheduled_compliance_reports.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ComplianceReportJob.organization_id", lazy="raise")
    user = relationship("User", foreign_keys="ComplianceReportJob.requested_by", lazy="raise")
    scheduled_compliance_report = relationship("ScheduledComplianceReport", foreign_keys="ComplianceReportJob.schedule_id", lazy="raise")
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    framework = Column(String(20), nullable=False)
    format = Column(String(10), nullable=False)
    recipients = Column(
        JSON().with_variant(JSONB, "postgresql"),
        default=list,
        server_default="[]",
        nullable=False,
    )
    report_status = Column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    delivery_status = Column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    publication_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    generation_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    email_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    error_report = Column(Text)
    error_delivery = Column(Text)
    file_path = Column(Text)
    filename = Column(String(255))
    media_type = Column(String(100))
    file_size = Column(BigInteger)
    file_sha256 = Column(String(64))
    created_at = Column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )
    published_at = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    email_sent_at = Column(DateTime(timezone=True))


class AgentRelease(Base):
    """Signed config, model, or executable edge-agent release artifact."""
    __tablename__ = "agent_releases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'yanked')",
            name="ck_agent_releases_status",
        ),
        CheckConstraint(
            "artifact_type IN ('config', 'model', 'agent')",
            name="ck_agent_releases_artifact_type",
        ),
        CheckConstraint(
            "("
            "artifact_type <> 'agent' OR ("
            "artifact_format IS NOT NULL AND "
            "artifact_format = 'wheel' AND "
            "artifact_filename IS NOT NULL AND "
            "artifact_size_bytes IS NOT NULL AND "
            "artifact_size_bytes > 0 AND "
            "package_name IS NOT NULL AND "
            "package_name = 'opsgrid-agent'"
            ")"
            ")",
            name="ck_agent_releases_agent_artifact",
        ),
        UniqueConstraint(
            "organization_id", "artifact_type", "version", "channel",
            name="uq_agent_releases_org_type_version_channel",
        ),
        UniqueConstraint("id", "organization_id", name="uq_agent_releases_id_org"),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(String(100), nullable=False)
    channel = Column(String(50), nullable=False, default="stable", server_default="stable")
    image_tag = Column(String(255), nullable=True)
    artifact_type = Column(String(20), nullable=False, default="config", server_default="config")
    model_name = Column(String(100), nullable=True)
    artifact_format = Column(String(20), nullable=True)
    artifact_filename = Column(String(255), nullable=True)
    artifact_size_bytes = Column(BigInteger, nullable=True)
    package_name = Column(String(100), nullable=True)
    minimum_bootstrap_version = Column(String(100), nullable=True)
    bundle_storage_key = Column(Text, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False)
    signature_ed25519 = Column(Text, nullable=False)
    signing_key_id = Column(String(255), nullable=False)
    release_notes = Column(Text)
    status = Column(String(30), nullable=False, default="draft", server_default="draft")
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    rollouts = relationship("AgentRollout", back_populates="release")


class FleetTargetPreview(Base):
    """Short-lived exact resolution used to materialize a rollout."""

    __tablename__ = "fleet_target_previews"
    __table_args__ = (
        CheckConstraint("asset_count >= 0 AND agent_count >= 0", name="ck_fleet_target_previews_counts"),
        CheckConstraint(
            "jsonb_typeof(selector) = 'object'",
            name="ck_fleet_target_previews_selector_object",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "jsonb_typeof(ordered_asset_ids) = 'array'",
            name="ck_fleet_target_previews_assets_array",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "jsonb_typeof(resolved_agents) = 'array'",
            name="ck_fleet_target_previews_agents_array",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "jsonb_typeof(excluded_assets) = 'array'",
            name="ck_fleet_target_previews_excluded_array",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "jsonb_typeof(warnings) = 'array'",
            name="ck_fleet_target_previews_warnings_array",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "membership_hash ~ '^[0-9a-f]{64}$'",
            name="ck_fleet_target_previews_hash",
        ).ddl_if(dialect="postgresql"),
        UniqueConstraint("id", "organization_id", name="uq_fleet_target_previews_id_org"),
        ForeignKeyConstraint(
            ["release_id", "organization_id"],
            ["agent_releases.id", "agent_releases.organization_id"],
            ondelete="CASCADE",
            name="fk_fleet_target_previews_release_org",
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id = Column(UUIDString(), nullable=False)
    selector = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    ordered_asset_ids = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    resolved_agents = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    excluded_assets = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        server_default="[]",
    )
    warnings = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        server_default="[]",
    )
    membership_hash = Column(String(64), nullable=False)
    asset_count = Column(Integer, nullable=False)
    agent_count = Column(Integer, nullable=False)
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class AgentRollout(Base):
    """Tenant-scoped OTA rollout definition."""
    __tablename__ = "agent_rollouts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'paused', 'running', 'completed', 'cancelled', 'rolled_back', 'failed')",
            name="ck_agent_rollouts_status",
        ),
        ForeignKeyConstraint(
            ["target_preview_id", "organization_id"],
            ["fleet_target_previews.id", "fleet_target_previews.organization_id"],
            ondelete="RESTRICT",
            name="fk_agent_rollouts_preview_org",
        ),
        Index(
            "uq_agent_rollouts_target_preview",
            "target_preview_id",
            unique=True,
            postgresql_where=text("target_preview_id IS NOT NULL"),
        ),
        CheckConstraint(
            "pause_reason IS NULL "
            "OR pause_reason IN ('manual', 'maintenance_window')",
            name="ck_agent_rollouts_pause_reason",
        ),
        Index(
            "idx_agent_rollouts_schedule_due",
            "organization_id",
            "status",
            "next_eligible_at",
            "scheduled_start_at",
            postgresql_where=text(
                "status IN ('pending', 'running', 'paused')"
            ),
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id = Column(
        UUIDString(),
        ForeignKey("agent_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    target_selector = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    strategy = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    status = Column(String(30), nullable=False, default="pending", server_default="pending")
    target_preview_id = Column(UUIDString(), nullable=True)
    target_membership_hash = Column(String(64))
    scheduled_start_at = Column(DateTime(timezone=True))
    enforce_maintenance_windows = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    pause_reason = Column(String(40))
    next_eligible_at = Column(DateTime(timezone=True))
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    release = relationship("AgentRelease", back_populates="rollouts")
    targets = relationship(
        "AgentRolloutTarget",
        back_populates="rollout",
        cascade="all, delete-orphan",
    )
    events = relationship(
        "AgentRolloutEvent",
        back_populates="rollout",
        cascade="all, delete-orphan",
    )


class AgentRolloutTarget(Base):
    """Per-asset OTA rollout state."""
    __tablename__ = "agent_rollout_targets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'updating', 'success', 'failed', 'rolled_back', 'cancelled', 'skipped')",
            name="ck_agent_rollout_targets_status",
        ),
        UniqueConstraint(
            "rollout_id", "asset_id",
            name="uq_agent_rollout_targets_rollout_asset",
        ),
        ForeignKeyConstraint(
            ["route_asset_id", "organization_id"],
            ["assets.id", "assets.organization_id"],
            ondelete="RESTRICT",
            name="fk_agent_rollout_targets_route_asset_org",
        ),
        ForeignKeyConstraint(
            ["site_id", "organization_id"],
            ["sites.id", "sites.organization_id"],
            ondelete="RESTRICT",
            name="fk_agent_rollout_targets_site_org",
        ),
        Index(
            "idx_agent_rollout_targets_site",
            "rollout_id",
            "site_id",
            "wave_index",
        ),
    )

    id = UUIDColumn()
    rollout_id = Column(
        UUIDString(),
        ForeignKey("agent_rollouts.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = Column(
        UUIDString(),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id = Column(String(255))
    route_asset_id = Column(UUIDString(), nullable=True)
    site_id = Column(UUIDString(), nullable=True)
    wave_index = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(30), nullable=False, default="pending", server_default="pending")
    current_version = Column(String(100))
    attempted_version = Column(String(100))
    running_version = Column(String(100))
    local_rollback = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    command_id = Column(String(255))
    rollback_command_id = Column(String(255))
    failure_reason = Column(Text)
    dispatched_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    last_event_at = Column(DateTime(timezone=True))

    rollout = relationship("AgentRollout", back_populates="targets")


class AgentRolloutEvent(Base):
    """Append-only rollout event stream."""
    __tablename__ = "agent_rollout_events"

    id = UUIDColumn()
    rollout_id = Column(
        UUIDString(),
        ForeignKey("agent_rollouts.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String(100), nullable=False)
    asset_id = Column(
        UUIDString(),
        ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    detail = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    rollout = relationship("AgentRollout", back_populates="events")


class IntegrationConfiguration(Base):
    """External integration configurations"""
    __tablename__ = "integration_configurations"

    id = UUIDColumn()
    integration_type = Column(String(50), nullable=False)
    integration_name = Column(String(255), nullable=False)
    organization_id = UUIDForeignKey("organizations.id", nullable=True)
    #: Ordering only (FS-408/410). Without it the unit of work has no edge from this mapper
    #: to Organization and can flush an integration BEFORE the org it belongs to — the exact
    #: failure that killed seed_demo_data.py on a fresh database, and the first thing that
    #: broke when foreign keys were switched on for this file's tests. `lazy="raise"` so an
    #: accidental traversal is a clear error rather than a MissingGreenlet in async code.
    organization = relationship("Organization", lazy="raise")
    configuration = Column(JSON, nullable=False)
    authentication = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    health_check_url = Column(String(500), nullable=True)
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    health_status = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_by = UUIDForeignKey("users.id", nullable=True)
    meta_data = Column(JSON, default={})
    
    # ERP-specific fields
    erp_type = Column(String(50), nullable=True)
    erp_version = Column(String(50), nullable=True)
    sync_schedule = Column(String(100), nullable=True)
    sync_frequency_minutes = Column(Integer, default=60)
    last_successful_sync = Column(DateTime(timezone=True), nullable=True)


class DataResidencyTag(Base):
    """Data residency tags for compliance"""
    __tablename__ = "data_residency_tags"

    id = UUIDColumn()
    #: FS-433. This table had no owner: every tenant's tags in one pool, behind three
    #: endpoints open to any authenticated user and three behind a PER-ORG admin. Migration
    #: 062 adds the column, backfills it from `tagged_by`'s organisation, and puts the table
    #: under FORCE ROW LEVEL SECURITY like every other tenant table.
    organization_id = UUIDForeignKey("organizations.id", nullable=False)
    table_name = Column(String(100), nullable=False)
    record_id = Column(String(36), nullable=False)
    region = Column(String(50), nullable=False, default="USA")
    tagged_at = Column(DateTime(timezone=True), default=utcnow)
    tagged_by = UUIDForeignKey("users.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    user = relationship("User", foreign_keys="DataResidencyTag.tagged_by", lazy="raise")
    organization = relationship(
        "Organization", foreign_keys="DataResidencyTag.organization_id", lazy="raise"
    )
    meta_data = Column(JSON, default={})

    __table_args__ = (
        # One tag per (org, table, record). Without the organisation in the key, two
        # tenants tagging the same record id collided and one silently became the other's.
        UniqueConstraint(
            "organization_id", "table_name", "record_id",
            name="uq_data_residency_tags_org_table_record",
        ),
    )


# ==================== ERP Integration Models ====================

class ERPIntegrationEvent(Base):
    """ERP integration events for tracking webhook and sync events"""
    __tablename__ = "erp_integration_events"
    # Matches migration 020's `uq_erp_events`. Declaring it here makes create_all
    # (SQLite tests) enforce it too, and it is the real idempotency guarantee for
    # webhook delivery — the receiver relies on the conflict rather than a racy
    # check-then-insert.
    __table_args__ = (
        UniqueConstraint("source_system", "event_id", name="uq_erp_events"),
    )

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", nullable=False)
    #: Ordering only (FS-408/410); see IntegrationConfiguration.
    organization = relationship("Organization", lazy="raise")
    integration_id = UUIDForeignKey("integration_configurations.id", nullable=False)
    event_type = Column(String(100), nullable=False)
    event_id = Column(String(255), nullable=False)
    source_system = Column(String(50), nullable=False)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(String(255), nullable=True)
    event_data = Column(JSON, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    processing_status = Column(String(50), default="pending")
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class ERPDataMapping(Base):
    """Field mappings for ERP data transformation"""
    __tablename__ = "erp_data_mappings"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", nullable=False)
    integration_id = UUIDForeignKey("integration_configurations.id", nullable=False)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ERPDataMapping.organization_id", lazy="raise")
    integration_configuration = relationship("IntegrationConfiguration", foreign_keys="ERPDataMapping.integration_id", lazy="raise")
    source_entity = Column(String(100), nullable=False)
    source_field = Column(String(100), nullable=False)
    target_entity = Column(String(100), nullable=False)
    target_field = Column(String(100), nullable=False)
    transformation_rule = Column(Text, nullable=True)
    data_type = Column(String(50), nullable=True)
    is_required = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ERPSyncStatus(Base):
    """Sync status tracking for ERP integrations"""
    __tablename__ = "erp_sync_status"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", nullable=False)
    integration_id = UUIDForeignKey("integration_configurations.id", nullable=False)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ERPSyncStatus.organization_id", lazy="raise")
    integration_configuration = relationship("IntegrationConfiguration", foreign_keys="ERPSyncStatus.integration_id", lazy="raise")
    entity_type = Column(String(100), nullable=False)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_sync_status = Column(String(50), nullable=True)
    records_synced = Column(Integer, default=0)
    records_failed = Column(Integer, default=0)
    sync_duration_seconds = Column(Numeric, nullable=True)
    next_sync_at = Column(DateTime(timezone=True), nullable=True)
    delta_token = Column(Text, nullable=True)

    #: Whether correlation had a route for this vendor/entity on the last sync (FS-562).
    #: NULL is a real third state: a row written before this column existed recorded no
    #: attempt either way, and defaulting it to False would invent a skip that may never
    #: have happened. The UI reads null as "not recorded".
    correlation_routed = Column(Boolean, nullable=True)
    #: Why correlation produced nothing, when it produced nothing.
    correlation_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ERPEntity(Base):
    """Normalized ERP entity data"""
    __tablename__ = "erp_entities"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", nullable=False)
    integration_id = UUIDForeignKey("integration_configurations.id", nullable=False)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ERPEntity.organization_id", lazy="raise")
    integration_configuration = relationship("IntegrationConfiguration", foreign_keys="ERPEntity.integration_id", lazy="raise")
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(String(255), nullable=False)
    entity_data = Column(JSON, nullable=False)
    source_system = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)
    valid_from = Column(DateTime(timezone=True), default=utcnow)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ERPCorrelation(Base):
    """Correlations between ERP events and sensor data"""
    __tablename__ = "erp_correlations"

    id = UUIDColumn()
    organization_id = UUIDForeignKey("organizations.id", nullable=False)
    correlation_type = Column(String(100), nullable=False)
    erp_event_id = UUIDForeignKey("erp_integration_events.id", nullable=True)

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ERPCorrelation.organization_id", lazy="raise")
    e_r_p_integration_event = relationship("ERPIntegrationEvent", foreign_keys="ERPCorrelation.erp_event_id", lazy="raise")
    sensor_event_id = Column(UUIDString(), nullable=True)
    correlation_score = Column(Numeric, nullable=True)
    correlation_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)



class ErrorEvent(Base):
    """Aggregated unhandled-exception fingerprint (Error Triage).

    One row per unique (exception type + route template + crash location). Only
    metadata and scrubbed samples are stored — never request bodies, headers, or
    user identity. Mirrors database/migrations/018_error_events.sql.
    """
    __tablename__ = "error_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name="ck_error_events_status",
        ),
    )

    fingerprint = Column(String(16), primary_key=True)
    exception_type = Column(String(255), nullable=False)
    route = Column(String(512), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False, default=500, server_default="500")
    message_sample = Column(String(500))
    traceback_sample = Column(Text)
    total_count = Column(BigInteger, nullable=False, default=0, server_default="0")
    regression_count = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(20), nullable=False, default="open", server_default="open")
    status_changed_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status_changed_at = Column(DateTime(timezone=True))
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)
    organization_id = Column(UUIDString(), nullable=True)

    buckets = relationship(
        "ErrorEventBucket",
        back_populates="error_event",
        cascade="all, delete-orphan",
    )


class ErrorEventBucket(Base):
    """Hourly occurrence rollup for an error fingerprint (Error Triage trends)."""
    __tablename__ = "error_event_buckets"

    fingerprint = Column(
        String(16),
        ForeignKey("error_events.fingerprint", ondelete="CASCADE"),
        primary_key=True,
    )
    bucket_hour = Column(DateTime(timezone=True), primary_key=True)
    count = Column(BigInteger, nullable=False, default=0, server_default="0")

    error_event = relationship("ErrorEvent", back_populates="buckets")


class ModelRegistryEntry(Base):
    """Tenant-scoped cloud-trained model artifact metadata (MLOps registry).

    Serves the ``{version, download_url, sha256_hash}`` contract that the edge
    MLOps client (``services/mlops_pipeline.py``) already polls. ``name`` keys
    the model family (``anomaly``, ``oee_forecast``, ``tactical-engine``);
    ``feature_contract`` pins the ordered input feature names + normalization so
    a served ``.pt`` matches what the edge feeds at inference.
    """
    __tablename__ = "model_registry"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'yanked')",
            name="ck_model_registry_status",
        ),
        UniqueConstraint(
            "organization_id", "name", "version",
            name="uq_model_registry_org_name_version",
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    version = Column(String(100), nullable=False)
    framework = Column(String(50), nullable=False, default="torchscript", server_default="torchscript")
    artifact_storage_key = Column(Text, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False)
    feature_contract = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    metrics = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    training_run_id = Column(UUIDString(), nullable=True)
    release_notes = Column(Text)
    status = Column(String(30), nullable=False, default="draft", server_default="draft")
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ModelRegistryEntry.organization_id", lazy="raise")
    user = relationship("User", foreign_keys="ModelRegistryEntry.created_by", lazy="raise")
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class ModelTrainingRun(Base):
    """Provenance + metrics for a cloud training run that produces a registry model."""
    __tablename__ = "model_training_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_model_training_runs_status",
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_name = Column(String(100), nullable=False)
    status = Column(String(30), nullable=False, default="pending", server_default="pending")
    params = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    metrics = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    dataset_window_start = Column(DateTime(timezone=True))
    dataset_window_end = Column(DateTime(timezone=True))
    sample_count = Column(Integer)
    produced_model_id = Column(
        UUIDString(),
        ForeignKey("model_registry.id", ondelete="SET NULL"),
        nullable=True,
    )
    error = Column(Text)
    created_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Ordering only (FS-417). SQLAlchemy builds insert ordering from relationships,
    #: not from ForeignKey columns, so without these a flush can emit this row before
    #: the parent it references — refused by Postgres, accepted silently by SQLite.
    #: `lazy="raise"` because nothing should traverse them: they exist to order
    #: inserts, and an accidental lazy load in async code is a MissingGreenlet.
    organization = relationship("Organization", foreign_keys="ModelTrainingRun.organization_id", lazy="raise")
    model_registry_entry = relationship("ModelRegistryEntry", foreign_keys="ModelTrainingRun.produced_model_id", lazy="raise")
    user = relationship("User", foreign_keys="ModelTrainingRun.created_by", lazy="raise")
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
