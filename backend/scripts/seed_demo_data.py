#!/usr/bin/env python3
"""Seed realistic, correlated demo data — simulating a FULL ERP integration.

The point: make the platform tell one coherent story out of the box, as if a
SAP integration had been syncing for two weeks alongside live sensors and yard
operations. Every domain shares keys with the others, so Correlation AI finds
real cross-domain links:

  THE STORY (last 14 days, deterministic):
  - CNC Mill #1's spindle vibration degrades from day -9, crossing the alarm
    band on day -2. The acoustic monitor's high-band energy rises in the same
    window (bearing-wear signature).
  - SAP (simulated fully-synced integration) releases WorkOrder WO-77105
    ("spindle bearing replacement", asset: CNC Mill #1) on day -2 and a rush
    PurchaseOrder PO-10021 (bearing kit). WO completes day -1; vibration drops
    back to baseline. ERP<->sensor correlation recorded.
  - Material POs reference the trailers arriving in the yard (po_number on
    trailers + dock appointments); the dock camera's motion spikes line up
    with appointment windows. One trailer overstays free time -> live
    detention charges.
  - Delivered shipments are invoiced in ERP (shipment_number on invoices);
    a driver is near his HOS limit; a truck has an overdue oil change and an
    in-progress brake repair.
  - A ready-made analysis session ("Demo: Spindle failure investigation") has
    ERP + sensor + yard sources pre-attached — open Correlation AI and hit
    correlate.

Idempotent: fixed UUIDs; re-running wipes and re-seeds exactly these rows.
Run:  make seed-demo     (defaults DATABASE_URL to backend/dev.db SQLite)
      python scripts/seed_demo_data.py [--verify]
"""

import asyncio
import math
import os
import uuid as _uuid
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get("DATABASE_URL"):
    default_db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dev.db")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{default_db}"

# AWARE, not `datetime.utcnow()`. That returns a NAIVE datetime, and writing a naive value
# into a `timestamptz` column shifts it by the CLIENT's UTC offset — measured here as +5h on
# a UTC-5 machine against a database whose own timezone is UTC. The relative gaps between
# seeded rows survive, so the data looks plausible; only the anchor moves. That silently broke
# the demo's detention scenario — TRL-4482 is seeded at 6 hours of dwell to sit past the free
# window, and it arrived as 1 hour, so `/yard/detention-alerts` returned an empty list and the
# seed's own verifier failed. On a UTC developer machine the bug is invisible.
#
# Same family as FS-391 and FS-400, which were naive datetimes crashing detention and carrier
# compliance. This one does not crash; it just makes every relative timestamp wrong.
NOW = datetime.now(timezone.utc)
RNG = random.Random(42)

# ---- fixed ids (re-run replaces) ---------------------------------------------
ORG = "00000000-0000-0000-0000-000000000001"     # dev-token org
USER = "00000000-0000-0000-0000-000000000001"    # dev-token user
WC_MACHINING = "11111111-0000-4000-8000-000000000001"
WC_ASSEMBLY = "11111111-0000-4000-8000-000000000002"

AT_CNC = "22222222-0000-4000-8000-000000000001"
AT_VIB = "22222222-0000-4000-8000-000000000002"
AT_AUDIO = "22222222-0000-4000-8000-000000000003"
AT_VIDEO = "22222222-0000-4000-8000-000000000004"
AT_CONVEYOR = "22222222-0000-4000-8000-000000000005"

A_CNC = "33333333-0000-4000-8000-000000000001"
A_VIB = "33333333-0000-4000-8000-000000000002"
A_AUDIO = "33333333-0000-4000-8000-000000000003"
A_CAMERA = "33333333-0000-4000-8000-000000000004"
A_CONVEYOR = "33333333-0000-4000-8000-000000000005"

ERP_INT = "44444444-0000-4000-8000-000000000001"


def _webhook_secret(integration_id: str) -> str:
    """A distinct, deterministic webhook secret per seeded integration.

    IT WAS THE LITERAL "demo-secret", which is two problems in one string.

    Migration 049 puts a UNIQUE index on `configuration->>'webhook_secret'`, because the
    receiver identifies an integration BY its secret — it verifies the request's exact bytes
    against every candidate, so two integrations sharing a secret makes the sender ambiguous.
    One seeded integration never collides; a second one, or a second demo organisation, is
    rejected by the index with a constraint error rather than a useful message.

    And a fixed secret committed to the repository is a signing key anybody can read: a demo
    deployment would accept a forged webhook from anyone who has cloned this.

    DETERMINISTIC, not random. The seeder is re-runnable — it deletes the integration before
    inserting it — and `--verify` checks the result in the same process, but a demo operator
    wiring up a real sender needs the secret to survive a re-seed. Derived from the
    integration id, so it is stable per integration and distinct between them.
    """
    import hashlib

    digest = hashlib.sha256(f"omniusgrid-demo-webhook:{integration_id}".encode()).hexdigest()
    return f"demo-{digest[:32]}"

CARRIER_A = "55555555-0000-4000-8000-000000000001"  # Great Lakes Freight
CARRIER_B = "55555555-0000-4000-8000-000000000002"  # Prairie Express
DRIVER_1 = "66666666-0000-4000-8000-000000000001"
DRIVER_2 = "66666666-0000-4000-8000-000000000002"
DRIVER_3 = "66666666-0000-4000-8000-000000000003"

SESSION_ID = "77777777-0000-4000-8000-000000000001"

# ---- transportation routes (get_routes) + telematics (fleet_health) ----------
ROUTE_CHI_DAL = "70000000-0000-4000-8000-000000000001"  # Chicago -> Dallas lane
ROUTE_CHI_MSP = "70000000-0000-4000-8000-000000000002"  # Chicago -> Minneapolis
ROUTE_CHI_DET = "70000000-0000-4000-8000-000000000003"  # Chicago -> Detroit

# ---- gap-area fixed ids (kanban / OTA / MLOps / compliance / notifications) ----
BOARD_ID = "aaaaaaaa-0000-4000-8000-000000000001"
COL_IDS = {  # column_type -> fixed id
    "backlog": "aaaaaaaa-0000-4000-8000-000000000010",
    "triage": "aaaaaaaa-0000-4000-8000-000000000011",
    "in_progress": "aaaaaaaa-0000-4000-8000-000000000012",
    "review": "aaaaaaaa-0000-4000-8000-000000000013",
    "rejected": "aaaaaaaa-0000-4000-8000-000000000014",
    "done": "aaaaaaaa-0000-4000-8000-000000000015",
}
# 18 tasks: the demo board has to look like a real shift board, not a stub. This
# replaces migrations 005/006_populate_*_kanban_data, which used to insert demo
# rows into the PRODUCTION chain (FS-203 gated them); the seeder is the sanctioned
# home for demo data, so it has to carry at least as much as they did.
TASK_IDS = [f"aaaaaaaa-0000-4000-8000-0000000000{20 + i:02d}" for i in range(1, 19)]
TASK_RULE_ID = "aaaaaaaa-0000-4000-8000-000000000031"

AGENT_RELEASE_ID = "bbbbbbbb-0000-4000-8000-000000000001"
MODEL_RELEASE_ID = "bbbbbbbb-0000-4000-8000-000000000002"
ROLLOUT_ID = "bbbbbbbb-0000-4000-8000-000000000010"
MODEL_ANOMALY_ID = "cccccccc-0000-4000-8000-000000000001"
MODEL_OEE_ID = "cccccccc-0000-4000-8000-000000000002"

REGISTRY_LOTO_ID = "dddddddd-0000-4000-8000-000000000001"
REGISTRY_ISO_ID = "dddddddd-0000-4000-8000-000000000002"
COMPLIANCE_SCHEDULE_ID = "dddddddd-0000-4000-8000-000000000010"
COMPLIANCE_JOB_ID = "dddddddd-0000-4000-8000-000000000011"

NOTIF_SUB_IDS = [f"eeeeeeee-0000-4000-8000-00000000000{i}" for i in range(1, 4)]
ERROR_FINGERPRINTS = ["demoerr000000001", "demoerr000000002",
                      "demoerr000000003", "demoerr000000004"]
EXPORT_TEMPLATE_IDS = ["ffffffff-0000-4000-8000-000000000001",
                       "ffffffff-0000-4000-8000-000000000002"]

DOOR_IDS = [f"88888888-0000-4000-8000-00000000000{i}" for i in range(1, 9)]
TRAILER_DWELL = "99999999-0000-4000-8000-000000000001"   # long-dwell -> detention
TRAILER_DOCKED = "99999999-0000-4000-8000-000000000002"  # at door 3 (camera)
TRAILER_YARD = "99999999-0000-4000-8000-000000000003"
TRAILER_OUT1 = "99999999-0000-4000-8000-000000000004"
TRAILER_OUT2 = "99999999-0000-4000-8000-000000000005"

DEGRADE_START_D, ALARM_D, FIXED_D = 9.0, 2.0, 1.0  # days ago


def days_ago(d: float) -> datetime:
    return NOW - timedelta(days=d)


# ---- correlated signal generators --------------------------------------------

def vibration_at(t: datetime) -> float:
    """Baseline 1.2 mm/s; rises from day -9 to ~8.3 at day -2; fixed at day -1."""
    age_d = (NOW - t).total_seconds() / 86400
    base = 1.2 + RNG.uniform(-0.15, 0.15)
    if age_d < FIXED_D:
        return round(max(0.4, 1.0 + RNG.uniform(-0.1, 0.1)), 3)  # post-repair
    if age_d < ALARM_D:
        return round(8.3 + RNG.uniform(-0.4, 0.4), 3)            # at alarm
    if age_d < DEGRADE_START_D:
        frac = (DEGRADE_START_D - age_d) / (DEGRADE_START_D - ALARM_D)
        return round(base + frac * 7.0 + RNG.uniform(-0.3, 0.3), 3)
    return round(base, 3)


def audio_bands_at(t: datetime):
    """High-band energy tracks the bearing wear; renormalized to sum 1."""
    age_d = (NOW - t).total_seconds() / 86400
    if age_d < FIXED_D:
        high = 0.10
    elif age_d < DEGRADE_START_D:
        frac = min(1.0, (DEGRADE_START_D - age_d) / (DEGRADE_START_D - ALARM_D))
        high = 0.12 + 0.35 * frac
    else:
        high = 0.12
    high += RNG.uniform(-0.02, 0.02)
    low = 0.30 + RNG.uniform(-0.03, 0.03)
    mid = max(0.05, 1.0 - low - high)
    rms = round(0.15 + high * 0.4 + RNG.uniform(-0.02, 0.02), 4)
    peak = round(850 + high * 1400 + RNG.uniform(-40, 40), 1)
    return rms, peak, round(low, 4), round(mid, 4), round(high, 4)


def camera_at(t: datetime, appointment_hours) -> tuple:
    """Brightness follows day/night; motion spikes during appointment windows."""
    hour = t.hour + t.minute / 60
    brightness = 95 + 65 * math.sin((hour - 6) / 24 * 2 * math.pi) + RNG.uniform(-8, 8)
    motion = RNG.uniform(0.0, 0.06)
    for ah in appointment_hours:
        if abs(hour - ah) < 1.0:
            motion = RNG.uniform(0.25, 0.55)
    return round(max(5.0, brightness), 1), round(motion, 4)


async def main(verify: bool = False) -> int:
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.db.database import AsyncSessionLocal, engine, get_async_db_url, init_db
    from app.db.models import (
        Alarm, AlarmRule, AnalysisSession, Asset, AssetType, Carrier, DockAppointment,
        DockDoor, Driver, DriverWaitTime, ERPCorrelation, ERPDataMapping,
        ERPEntity, ERPIntegrationEvent, ERPSyncStatus, GeoTabDiagnostic,
        GeoTabException, GeoTabTrip, IntegrationConfiguration,
        Organization, Route, SessionDataSource, Shipment, Telemetry, User,
        Workcell, YardTrailer,
    )
    from app.db.logistics_models import (
        GeofenceAlert, GeofenceZone, MaintenanceSchedule, RepairOrder, Vehicle,
    )
    from app.db.models import (
        ActionableRegistry, ActionableRegistryItem, AgentRelease, AgentRollout,
        AgentRolloutEvent, AgentRolloutTarget, ComplianceReportJob, ErrorEvent,
        ErrorEventBucket, ExportTemplate, HistorianRetentionPolicy,
        ModelRegistryEntry, Operation, ScheduledComplianceReport, Task,
        TaskBoard, TaskColumn, TaskComment, TaskRule,
    )
    from app.db.notification_models import (
        NotificationDelivery, NotificationSubscription,
    )

    await init_db()
    print(f"Seeding demo data into {os.environ['DATABASE_URL']}")

    # FK-TRIGGER RELAXATION FOR THE BULK LOAD, AND WHY IT NEEDS ITS OWN ENGINE.
    #
    # 62 of the 69 FK-carrying models declare a bare ForeignKey COLUMN and no
    # relationship(), and SQLAlchemy's unit of work builds its insert ordering from
    # relationships — so for most of this file it cannot order a parent before its child.
    # `session_replication_role = replica` sidesteps that for the load.
    #
    # THE PREVIOUS VERSION SET IT AND THEN COMMITTED ON THE NEXT LINE, which returns the
    # connection to the pool and resets the setting: measured `replica` immediately after
    # the SET and `origin` immediately after the commit. So the protection was gone before
    # a single row was written, and the seed died on a foreign key against a fresh
    # database — the path docs/DEMO.md tells operators to run.
    #
    # Passing it as an asyncpg *startup parameter* fixes that properly: it becomes the
    # session default, so it survives every commit and every connection recycle rather
    # than lasting until the next one.
    bulk_engine = None
    session_factory = AsyncSessionLocal
    if engine.dialect.name == "postgresql":
        bulk_engine = create_async_engine(
            get_async_db_url(),
            connect_args={"server_settings": {"session_replication_role": "replica"}},
            poolclass=NullPool,
        )
        session_factory = async_sessionmaker(
            bulk_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )

    async with session_factory() as db:
        from sqlalchemy import text as _sql_text
        _pg = db.bind.dialect.name == "postgresql"
        if _pg:
            # VERIFIED, NOT ASSUMED. The old code swallowed the failure as "harmless"; it
            # was not — it turned an ordering problem into an unexplained FK violation far
            # from its cause. A role that cannot set this gets told so here.
            actual = (await db.execute(_sql_text("SHOW session_replication_role"))).scalar()
            if actual != "replica":
                raise SystemExit(
                    "cannot seed: this database role could not set "
                    "session_replication_role=replica (it reports "
                    f"{actual!r}), and without it the load fails on a foreign key because "
                    "most models carry FK columns with no ORM relationship for the unit of "
                    "work to order by. Seed as a superuser, or grant the role that setting."
                )

        # ---- wipe previous demo rows (surgical: fixed ids / org scope) -------
        asset_ids = [A_CNC, A_VIB, A_AUDIO, A_CAMERA, A_CONVEYOR]
        await db.execute(delete(Telemetry).where(Telemetry.asset_id.in_(asset_ids)))
        await db.execute(delete(Alarm).where(Alarm.asset_id.in_(asset_ids)))
        await db.execute(delete(SessionDataSource).where(SessionDataSource.session_id == SESSION_ID))
        await db.execute(delete(AnalysisSession).where(AnalysisSession.id == SESSION_ID))
        for model, col in [
            (ERPCorrelation, ERPCorrelation.organization_id),
            (ERPIntegrationEvent, ERPIntegrationEvent.organization_id),
            (ERPSyncStatus, ERPSyncStatus.organization_id),
            (ERPDataMapping, ERPDataMapping.organization_id),
            (ERPEntity, ERPEntity.organization_id),
            (DriverWaitTime, DriverWaitTime.organization_id),
            (DockAppointment, DockAppointment.organization_id),
            (YardTrailer, YardTrailer.organization_id),
            (DockDoor, DockDoor.organization_id),
            (Shipment, Shipment.organization_id),
            (Route, Route.organization_id),
            (GeoTabTrip, GeoTabTrip.organization_id),
            (GeoTabException, GeoTabException.organization_id),
            (GeoTabDiagnostic, GeoTabDiagnostic.organization_id),
            (Vehicle, Vehicle.organization_id),
            (GeofenceAlert, GeofenceAlert.organization_id),
            (GeofenceZone, GeofenceZone.organization_id),
            (MaintenanceSchedule, MaintenanceSchedule.organization_id),
            (RepairOrder, RepairOrder.organization_id),
            (Driver, Driver.organization_id),
            (Carrier, Carrier.organization_id),
        ]:
            await db.execute(delete(model).where(col == ORG))
        await db.execute(delete(IntegrationConfiguration).where(IntegrationConfiguration.id == ERP_INT))

        # ---- wipe gap-area demo rows (FK-safe order) -------------------------
        await db.execute(delete(TaskComment).where(TaskComment.task_id.in_(TASK_IDS)))
        await db.execute(delete(Task).where(Task.board_id == BOARD_ID))
        await db.execute(delete(TaskRule).where(TaskRule.organization_id == ORG))
        await db.execute(delete(TaskColumn).where(TaskColumn.board_id == BOARD_ID))
        await db.execute(delete(TaskBoard).where(TaskBoard.organization_id == ORG))
        await db.execute(delete(Operation).where(Operation.asset_id.in_(asset_ids)))
        await db.execute(delete(AgentRolloutEvent).where(AgentRolloutEvent.organization_id == ORG))
        await db.execute(delete(AgentRolloutTarget).where(AgentRolloutTarget.organization_id == ORG))
        await db.execute(delete(AgentRollout).where(AgentRollout.organization_id == ORG))
        await db.execute(delete(AgentRelease).where(AgentRelease.organization_id == ORG))
        await db.execute(delete(ModelRegistryEntry).where(ModelRegistryEntry.organization_id == ORG))
        await db.execute(delete(ActionableRegistryItem).where(
            ActionableRegistryItem.registry_id.in_([REGISTRY_LOTO_ID, REGISTRY_ISO_ID])))
        await db.execute(delete(ActionableRegistry).where(ActionableRegistry.organization_id == ORG))
        await db.execute(delete(ComplianceReportJob).where(ComplianceReportJob.organization_id == ORG))
        await db.execute(delete(ScheduledComplianceReport).where(ScheduledComplianceReport.organization_id == ORG))
        await db.execute(delete(NotificationDelivery).where(NotificationDelivery.organization_id == ORG))
        await db.execute(delete(NotificationSubscription).where(NotificationSubscription.organization_id == ORG))
        await db.execute(delete(ErrorEventBucket).where(ErrorEventBucket.fingerprint.in_(ERROR_FINGERPRINTS)))
        await db.execute(delete(ErrorEvent).where(ErrorEvent.fingerprint.in_(ERROR_FINGERPRINTS)))
        await db.execute(delete(ExportTemplate).where(ExportTemplate.organization_id == ORG))
        await db.execute(delete(HistorianRetentionPolicy).where(HistorianRetentionPolicy.organization_id == _uuid.UUID(ORG)))

        await db.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
        await db.execute(delete(AssetType).where(AssetType.id.in_([AT_CNC, AT_VIB, AT_AUDIO, AT_VIDEO, AT_CONVEYOR])))
        await db.execute(delete(Workcell).where(Workcell.id.in_([WC_MACHINING, WC_ASSEMBLY])))
        await db.commit()

        # ---- org / user / workcells ------------------------------------------
        if (await db.execute(select(Organization).where(Organization.id == ORG))).scalar_one_or_none() is None:
            db.add(Organization(id=ORG, name="OmniusGrid Demo Plant (CHI-01)", slug="demo-chi-01"))
        if (await db.execute(select(User).where(User.id == USER))).scalar_one_or_none() is None:
            db.add(User(id=USER, email="admin@omniusgrid.com", full_name="Dev Admin", role="admin",
                        is_active=True, organization_id=ORG,
                        hashed_password="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYHqF5pXa9W"))
        db.add(Workcell(id=WC_MACHINING, organization_id=ORG, name="Machining Center",
                        description="CNC mills and lathes", location="Building B, Floor 1"))
        db.add(Workcell(id=WC_ASSEMBLY, organization_id=ORG, name="Assembly Line B",
                        description="Conveyor and packaging", location="Building A, Floor 2"))

        # ---- asset types + sensor assets --------------------------------------
        db.add(AssetType(id=AT_CNC, name="cnc_mill", category="subtractive_manufacturing", sensor_class="machinery"))
        db.add(AssetType(id=AT_VIB, name="vibration_sensor", category="condition_monitoring", sensor_class="machinery"))
        db.add(AssetType(id=AT_AUDIO, name="audio_sensor", category="acoustic_monitoring", sensor_class="audio"))
        db.add(AssetType(id=AT_VIDEO, name="video_camera", category="visual_monitoring", sensor_class="video"))
        db.add(AssetType(id=AT_CONVEYOR, name="conveyor", category="material_handling", sensor_class="machinery"))

        db.add(Asset(id=A_CNC, organization_id=ORG, workcell_id=WC_MACHINING, asset_type_id=AT_CNC,
                     name="CNC Mill #1", vendor="Haas", model="VF-2", serial_number="HAAS-VF2-001",
                     current_packml_state="Execute", sensor_class="machinery", last_seen=NOW))
        db.add(Asset(id=A_VIB, organization_id=ORG, workcell_id=WC_MACHINING, asset_type_id=AT_VIB,
                     name="Vibration Sensor — CNC Spindle", vendor="IFM", model="VVB001",
                     serial_number="IFM-VVB-08", current_packml_state="Execute",
                     sensor_class="machinery", last_seen=NOW))
        db.add(Asset(id=A_AUDIO, organization_id=ORG, workcell_id=WC_MACHINING, asset_type_id=AT_AUDIO,
                     name="Acoustic Monitor — Machining Center", vendor="SoundSafe", model="AM-100",
                     serial_number="SSAM-100-01", current_packml_state="Execute", sensor_class="audio",
                     media_config={"sample_rate": 16000, "channels": 1}, last_seen=NOW))
        db.add(Asset(id=A_CAMERA, organization_id=ORG, workcell_id=WC_ASSEMBLY, asset_type_id=AT_VIDEO,
                     name="Dock Camera — Door 3", vendor="Axis", model="M2025", serial_number="AXM-2025-03",
                     current_packml_state="Execute", sensor_class="video",
                     media_config={"stream_url": "http://192.168.1.203/mjpeg", "snapshot_interval": 30},
                     last_seen=NOW))
        db.add(Asset(id=A_CONVEYOR, organization_id=ORG, workcell_id=WC_ASSEMBLY, asset_type_id=AT_CONVEYOR,
                     name="Conveyor #1", vendor="Dorner", model="2200", serial_number="DRN-2200-11",
                     current_packml_state="Execute", sensor_class="machinery", last_seen=NOW))
        # Persist parents before FK children — several child tables reference
        # assets via a bare ForeignKey column with no ORM relationship(), so the
        # unit-of-work won't order the inserts on its own.
        await db.flush()

        # ---- 14 days of correlated telemetry (30-min interval) ----------------
        appointment_hours = [7.0, 13.0]  # dock activity windows (camera motion)
        points = 14 * 48
        seq = 0
        rows = 0
        for i in range(points):
            t = NOW - timedelta(minutes=30 * (points - 1 - i))
            seq += 1
            vib = vibration_at(t)
            db.add(Telemetry(time=t, asset_id=A_VIB, metric_name="vibration_rms", value=vib, unit="mm/s", sequence_num=seq))
            db.add(Telemetry(time=t, asset_id=A_VIB, metric_name="temperature",
                             value=round(48 + vib * 1.6 + RNG.uniform(-1.5, 1.5), 2), unit="°C", sequence_num=seq))
            db.add(Telemetry(time=t, asset_id=A_VIB, metric_name="load_percent",
                             value=round(62 + RNG.uniform(-6, 6), 2), unit="%", sequence_num=seq))
            db.add(Telemetry(time=t, asset_id=A_CNC, metric_name="spindle_rpm",
                             value=round(11800 + RNG.uniform(-350, 350), 1), unit="RPM", sequence_num=seq))
            db.add(Telemetry(time=t, asset_id=A_CNC, metric_name="spindle_load",
                             value=round(70 + vib * 1.2 + RNG.uniform(-4, 4), 2), unit="%", sequence_num=seq))
            db.add(Telemetry(time=t, asset_id=A_CNC, metric_name="tool_temperature",
                             value=round(36 + vib * 1.9 + RNG.uniform(-1.5, 1.5), 2), unit="°C", sequence_num=seq))
            rms, peak, lo, mid, hi = audio_bands_at(t)
            for m, v, u in [("audio_rms", rms, ""), ("audio_peak_hz", peak, "Hz"),
                            ("audio_band_low", lo, ""), ("audio_band_mid", mid, ""),
                            ("audio_band_high", hi, "")]:
                db.add(Telemetry(time=t, asset_id=A_AUDIO, metric_name=m, value=v, unit=u, sequence_num=seq))
            bright, motion = camera_at(t, appointment_hours)
            db.add(Telemetry(time=t, asset_id=A_CAMERA, metric_name="frame_brightness", value=bright, sequence_num=seq))
            db.add(Telemetry(time=t, asset_id=A_CAMERA, metric_name="motion_score", value=motion, sequence_num=seq))
            db.add(Telemetry(time=t, asset_id=A_CONVEYOR, metric_name="speed",
                             value=round(2.4 + RNG.uniform(-0.2, 0.2), 3), unit="m/s", sequence_num=seq))
            db.add(Telemetry(time=t, asset_id=A_CONVEYOR, metric_name="load",
                             value=round(78 + RNG.uniform(-9, 9), 2), unit="%", sequence_num=seq))
            rows += 13
        print(f"  telemetry: {rows} rows across 5 assets")

        # Vibration alarm at the spike; cleared when the WO completed.
        db.add(Alarm(asset_id=A_VIB, organization_id=ORG, alarm_code="VIB_HIGH", severity="high",
                     message="Spindle vibration exceeded ISO zone C (7.1 mm/s)",
                     occurred_at=days_ago(ALARM_D), cleared_at=days_ago(FIXED_D),
                     is_active=False, is_acknowledged=True, acknowledged_by=USER,
                     acknowledged_at=days_ago(1.9)))
        db.add(Alarm(asset_id=A_AUDIO, organization_id=ORG, alarm_code="ACOUSTIC_ANOMALY", severity="medium",
                     message="High-frequency band energy trending up (bearing-wear signature)",
                     occurred_at=days_ago(3.5), is_active=False, is_acknowledged=True,
                     acknowledged_by=USER, acknowledged_at=days_ago(3.4)))

        # A live spread of alarms so the Alarms page (default: last 24h window)
        # is populated: mixed severities, some active/unacknowledged, some
        # acknowledged, some resolved. occurred_at spread over the recent days.
        # (asset, code, severity, message, hours_ago, active, acked, cleared_h)
        recent_alarms = [
            (A_CNC, "SPINDLE_TEMP_HIGH", "critical",
             "Spindle bearing temperature 79°C — above 75°C critical threshold",
             1.5, True, False, None),
            (A_CONVEYOR, "BELT_SLIP", "high",
             "Conveyor #1 belt slip detected (speed variance > 12%)",
             4.0, True, False, None),
            (A_CAMERA, "MOTION_LOSS", "low",
             "Dock Camera — Door 3 reported no motion during scheduled appointment",
             8.0, True, True, None),
            (A_VIB, "VIB_ELEVATED", "medium",
             "Spindle vibration mildly elevated (3.4 mm/s) — monitor",
             18.0, True, False, None),
            (A_CONVEYOR, "MOTOR_CURRENT_HIGH", "high",
             "Conveyor #1 drive motor current spike (overload trip avoided)",
             30.0, False, True, 28.0),
            (A_CNC, "COOLANT_LOW", "medium",
             "CNC Mill #1 coolant reservoir below 20%",
             46.0, False, True, 44.0),
            (A_AUDIO, "AUDIO_CLIPPING", "low",
             "Acoustic Monitor input clipping on high-band channel",
             70.0, False, True, 69.0),
        ]
        for aid, code, sev, msg, h_ago, active, acked, cleared_h in recent_alarms:
            db.add(Alarm(
                asset_id=aid, organization_id=ORG, alarm_code=code, severity=sev, message=msg,
                occurred_at=NOW - timedelta(hours=h_ago), is_active=active,
                is_acknowledged=acked,
                acknowledged_by=USER if acked else None,
                acknowledged_at=(NOW - timedelta(hours=h_ago - 0.2)) if acked else None,
                cleared_at=(NOW - timedelta(hours=cleared_h)) if cleared_h is not None else None))

        # ---- ALARM RULES ------------------------------------------------------
        # Seeded so the Alarm Rules page is not empty in the demo, and so the
        # thresholds visibly correspond to the alarms above rather than looking
        # like unrelated sample data. One instant rule, one with a duration +
        # hysteresis, one disabled — the three shapes the page renders differently.
        db.add(AlarmRule(
            organization_id=ORG, name="Spindle temperature critical",
            description="Bearing temperature above the ISO limit",
            metric_name="temperature", comparator="gt", threshold=75.0,
            duration_seconds=300, hysteresis=2.0,
            severity="critical", alarm_code="SPINDLE_TEMP_HIGH",
            message_template="Spindle temperature {value}C exceeds {threshold}C",
            asset_id=A_CNC, is_enabled=True, created_by=USER))
        db.add(AlarmRule(
            organization_id=ORG, name="Coolant reservoir low",
            description="Refill before the next long run",
            metric_name="coolant_level", comparator="lt", threshold=20.0,
            duration_seconds=0, hysteresis=1.0,
            severity="medium", alarm_code="COOLANT_LOW",
            asset_id=A_CNC, is_enabled=True, created_by=USER))
        db.add(AlarmRule(
            organization_id=ORG, name="Conveyor load sustained high",
            description="Disabled while the drive is being re-tuned",
            metric_name="load", comparator="gte", threshold=90.0,
            duration_seconds=600, hysteresis=5.0,
            severity="high", alarm_code="CONVEYOR_LOAD_HIGH",
            asset_id=A_CONVEYOR, is_enabled=False, created_by=USER))

        # ---- SIMULATED FULLY-SYNCED ERP INTEGRATION ---------------------------
        db.add(IntegrationConfiguration(
            id=ERP_INT, organization_id=ORG, integration_type="erp",
            integration_name="SAP S/4HANA — Plant CHI-01",
            configuration={"erp_type": "sap", "auth_type": "oauth2",
                           "base_url": "https://sap.demo.omniusgrid.local",
                           "auth_config": {"client_id": "omnius-demo"},
                           "rate_limit": {"requests_per_minute": 60, "burst_limit": 10},
                           "timeout": 30, "webhook_secret": _webhook_secret(ERP_INT),
                           "client": "100", "service_path": "/sap/opu/odata/sap"},
            authentication={"client_id": "omnius-demo"}, is_active=True,
            health_status="success", last_health_check=NOW - timedelta(minutes=12),
            erp_type="sap", erp_version="S/4HANA 2023", sync_schedule="0 * * * *",
            sync_frequency_minutes=60, last_successful_sync=NOW - timedelta(minutes=42),
        ))
        for ent, field, target in [("WorkOrder", "OrderNumber", "job_id"),
                                   ("PurchaseOrder", "PONumber", "po_number"),
                                   ("Invoice", "ShipmentNumber", "shipment_number")]:
            db.add(ERPDataMapping(organization_id=ORG, integration_id=ERP_INT,
                                  source_entity=ent, source_field=field,
                                  target_entity="platform", target_field=target,
                                  data_type="string", is_required=True))
        for ent, n in [("WorkOrder", 14), ("PurchaseOrder", 23), ("Invoice", 9)]:
            db.add(ERPSyncStatus(organization_id=ORG, integration_id=ERP_INT, entity_type=ent,
                                 last_sync_at=NOW - timedelta(minutes=42), last_sync_status="success",
                                 records_synced=n, records_failed=0, sync_duration_seconds=8))

        # ERP entities — the star work order + supporting business objects.
        def entity(etype, eid, data, updated):
            db.add(ERPEntity(organization_id=ORG, integration_id=ERP_INT, entity_type=etype,
                             entity_id=eid, entity_data=data, source_system="sap",
                             valid_from=updated, updated_at=updated))

        entity("WorkOrder", "WO-77105", {
            "asset": "CNC Mill #1", "asset_id": A_CNC,
            "operation": "spindle bearing replacement", "priority": "urgent",
            "status": "completed", "released_at": days_ago(ALARM_D).isoformat(),
            "completed_at": days_ago(FIXED_D).isoformat(), "planned_hours": 6,
            "actual_hours": 5.5, "cause": "vibration alarm VIB_HIGH",
        }, days_ago(FIXED_D))
        entity("WorkOrder", "WO-77002", {
            "asset": "Conveyor #1", "operation": "belt tension check",
            "priority": "routine", "status": "completed", "planned_hours": 1,
        }, days_ago(6))
        entity("PurchaseOrder", "PO-10021", {
            "vendor": "SKF Bearings", "material": "Spindle bearing kit 7014-CD",
            "amount": 1840.0, "currency": "USD", "work_order": "WO-77105",
            "status": "received", "due_date": days_ago(1.5).isoformat(),
        }, days_ago(1.5))
        entity("PurchaseOrder", "PO-10018", {
            "vendor": "ACME Metals", "material": "6061 aluminum billet",
            "amount": 12450.0, "currency": "USD", "status": "received",
            "po_number": "PO-10018", "trailer": "TRL-4482",
            "due_date": days_ago(0.3).isoformat(),
        }, days_ago(0.3))
        entity("PurchaseOrder", "PO-10019", {
            "vendor": "Baxter Polymers", "material": "ABS pellets",
            "amount": 3980.5, "currency": "USD", "status": "in_transit",
            "po_number": "PO-10019", "trailer": "TRL-9017",
            "due_date": (NOW + timedelta(days=1)).isoformat(),
        }, days_ago(0.1))
        for i, (ship, amt, d) in enumerate([("SHP-2201", 22150.0, 2.2), ("SHP-2202", 9870.0, 4.1),
                                            ("SHP-2203", 15400.0, 6.5)]):
            entity("Invoice", f"INV-558{i}", {
                "customer": "Northwind Logistics", "amount": amt, "currency": "USD",
                "status": "open" if i == 0 else "paid", "shipment_number": ship,
            }, days_ago(d))

        # ERP event stream (webhooks/syncs as they landed).
        for etype, eid, ent, entid, d in [
            ("workorder.released", "evt-7001", "WorkOrder", "WO-77105", ALARM_D),
            ("po.created", "evt-7002", "PurchaseOrder", "PO-10021", ALARM_D - 0.05),
            ("workorder.completed", "evt-7003", "WorkOrder", "WO-77105", FIXED_D),
            ("po.received", "evt-7004", "PurchaseOrder", "PO-10018", 0.3),
            ("invoice.created", "evt-7005", "Invoice", "INV-5580", 2.2),
        ]:
            db.add(ERPIntegrationEvent(organization_id=ORG, integration_id=ERP_INT,
                                       event_type=etype, event_id=eid, source_system="sap",
                                       entity_type=ent, entity_id=entid,
                                       event_data={"entity_id": entid, "event_type": etype},
                                       processing_status="completed", processed_at=days_ago(d),
                                       created_at=days_ago(d)))
        db.flush = db.flush  # no-op clarity
        await db.flush()

        # Recorded ERP<->sensor correlations (what the engine found).
        wo_event = (await db.execute(select(ERPIntegrationEvent).where(
            ERPIntegrationEvent.event_id == "evt-7001"))).scalar_one()
        # sensor_event_id is a UUID column (migration 020 / native uuid); keep the
        # metric name in the metadata rather than packing it into the id string.
        db.add(ERPCorrelation(organization_id=ORG, correlation_type="work_order_vibration",
                              erp_event_id=wo_event.id, sensor_event_id=A_VIB,
                              correlation_score=0.87,
                              correlation_metadata={"window_days": 7, "asset": "CNC Mill #1",
                                                    "metric": "vibration_rms"}))
        db.add(ERPCorrelation(organization_id=ORG, correlation_type="po_dock_arrival",
                              sensor_event_id=A_CAMERA, correlation_score=0.74,
                              correlation_metadata={"po_number": "PO-10018", "door": "D3",
                                                    "metric": "motion_score"}))

        # ---- yard (correlated to POs + camera) ---------------------------------
        for i, door_id in enumerate(DOOR_IDS, start=1):
            db.add(DockDoor(id=door_id, organization_id=ORG, door_number=f"D{i}",
                            door_type="receiving" if i <= 5 else "shipping",
                            status="occupied" if i == 3 else "available",
                            current_trailer_id=TRAILER_DOCKED if i == 3 else None))
        db.add(Carrier(id=CARRIER_A, organization_id=ORG, carrier_name="Great Lakes Freight",
                       dot_number="DOT-448821", mc_number="MC-99120", ctpat_certified=True,
                       insurance_on_file=True, insurance_expires_at=NOW + timedelta(days=21),
                       safety_rating="satisfactory", csa_score=41.5, is_active=True,
                       # migration 042 — carrier scorecard columns
                       compliance_score=92.5, on_time_performance=0.94,
                       operating_authority="common", scac="GLFT"))
        db.add(Carrier(id=CARRIER_B, organization_id=ORG, carrier_name="Prairie Express",
                       dot_number="DOT-102934", mc_number="MC-55431", ctpat_certified=False,
                       insurance_on_file=True, insurance_expires_at=NOW + timedelta(days=180),
                       safety_rating="conditional", csa_score=68.0, is_active=True,
                       # migration 042 — carrier scorecard columns
                       compliance_score=78.0, on_time_performance=0.87,
                       operating_authority="contract", scac="PREX"))

        db.add(YardTrailer(id=TRAILER_DWELL, organization_id=ORG, trailer_number="TRL-4482",
                           carrier_id=CARRIER_A, trailer_type="dry_van", status="yard",
                           yard_location="Zone A-04", seal_number="SL-88121",
                           check_in_at=NOW - timedelta(hours=6),  # 4h past free time -> detention
                           # migration 042 — plate + detention exposure
                           license_plate="IL TRL4482", detention_cost=200.0, detention_risk="high",
                           meta_data={"po_number": "PO-10018", "contents": "6061 aluminum billet"}))
        db.add(YardTrailer(id=TRAILER_DOCKED, organization_id=ORG, trailer_number="TRL-7731",
                           carrier_id=CARRIER_A, trailer_type="reefer", status="docked",
                           dock_door_id=DOOR_IDS[2], seal_number="SL-88907",
                           check_in_at=NOW - timedelta(hours=1.2),
                           license_plate="IL TRL7731", detention_cost=0.0, detention_risk="low",
                           meta_data={"po_number": "PO-10021", "contents": "Spindle bearing kit"}))
        db.add(YardTrailer(id=TRAILER_YARD, organization_id=ORG, trailer_number="TRL-9017",
                           carrier_id=CARRIER_B, trailer_type="dry_van", status="yard",
                           yard_location="Zone B-02", check_in_at=NOW - timedelta(hours=0.8),
                           license_plate="WI TRL9017", detention_cost=0.0, detention_risk="medium",
                           meta_data={"po_number": "PO-10019", "contents": "ABS pellets"}))
        for tid, num, d_in, d_out in [(TRAILER_OUT1, "TRL-3306", 3.4, 3.1),
                                      (TRAILER_OUT2, "TRL-5540", 1.6, 1.35)]:
            _out_detention = round(max(0.0, ((d_in - d_out) * 1440 - 120) / 60 * 50), 2)
            db.add(YardTrailer(id=tid, organization_id=ORG, trailer_number=num,
                               carrier_id=CARRIER_B, trailer_type="dry_van", status="checked_out",
                               license_plate=f"WI {num.replace('-', '')}",
                               detention_cost=_out_detention,
                               detention_risk="high" if _out_detention > 100 else "low",
                               check_in_at=days_ago(d_in), check_out_at=days_ago(d_out)))
            db.add(DriverWaitTime(organization_id=ORG, trailer_id=tid,
                                  check_in_at=days_ago(d_in), check_out_at=days_ago(d_out),
                                  total_wait_minutes=int((d_in - d_out) * 1440),
                                  detention_minutes=max(0, int((d_in - d_out) * 1440 - 120)),
                                  detention_rate=50.0,
                                  detention_charge=round(max(0.0, ((d_in - d_out) * 1440 - 120) / 60 * 50), 2)))
        for d, hour in [(0.0, 7), (0.0, 13), (-1.0, 7)]:  # today's two + tomorrow morning
            start = (NOW - timedelta(days=d)).replace(hour=hour, minute=0, second=0, microsecond=0)
            db.add(DockAppointment(organization_id=ORG, dock_door_id=DOOR_IDS[2],
                                   appointment_type="receiving", scheduled_start=start,
                                   scheduled_end=start + timedelta(hours=2),
                                   status="completed" if start < NOW else "scheduled",
                                   carrier_id=CARRIER_A, priority="high" if hour == 7 else "normal",
                                   meta_data={"po_number": "PO-10018" if hour == 7 else "PO-10019"}))

        # ---- transportation (correlated to invoices) ---------------------------
        # migration 042 — HOS remaining = 11 - drive_today / 14 - on_duty_today
        db.add(Driver(id=DRIVER_1, organization_id=ORG, carrier_id=CARRIER_A, first_name="Maria",
                      last_name="Santos", license_number="IL-D449-2210", license_state="IL",
                      cdl_class="A", hos_drive_hours_today=10.6, hos_on_duty_hours_today=12.9,
                      hos_cycle_hours=61.0, current_hos_status="driving", is_active=True,
                      endorsements=["hazmat", "tanker"], license_expiry=NOW + timedelta(days=365),
                      hos_drive_hours_remaining=11 - 10.6, hos_duty_hours_remaining=14 - 12.9))
        db.add(Driver(id=DRIVER_2, organization_id=ORG, carrier_id=CARRIER_A, first_name="Dwayne",
                      last_name="Carter", license_number="IL-D101-8837", license_state="IL",
                      cdl_class="A", hos_drive_hours_today=3.2, hos_on_duty_hours_today=5.0,
                      hos_cycle_hours=28.5, current_hos_status="on_duty", is_active=True,
                      endorsements=["hazmat"], license_expiry=NOW + timedelta(days=420),
                      hos_drive_hours_remaining=11 - 3.2, hos_duty_hours_remaining=14 - 5.0))
        db.add(Driver(id=DRIVER_3, organization_id=ORG, carrier_id=CARRIER_B, first_name="Priya",
                      last_name="Natarajan", license_number="WI-D778-1204", license_state="WI",
                      cdl_class="A", hos_drive_hours_today=0.0, hos_on_duty_hours_today=1.5,
                      hos_cycle_hours=44.0, current_hos_status="off_duty", is_active=True,
                      medical_cert_expires=NOW + timedelta(days=18),
                      endorsements=["doubles_triples"], license_expiry=NOW + timedelta(days=300),
                      hos_drive_hours_remaining=11 - 0.0, hos_duty_hours_remaining=14 - 1.5))
        # Every UI-read column populated (vin/make/model/year/driver + telematics)
        # so the vehicle detail modal never hits a null. NOTE: the Vehicle ORM
        # model (logistics_models) has no vehicle_type/fuel_type/license_plate/
        # engine_hours columns, so those cannot be seeded here — the make/model/
        # year + fuel_level + odometer are the descriptive fields it exposes.
        # num, fuel, odometer, geotab device, status, vin, make, model, year, driver
        vehicles = [
            ("TRK-081", 0.62, 214880, "gt-device-001", "moving", "1FUJGLDR8PLBW4481",
             "Freightliner", "Cascadia", 2023, DRIVER_1),
            ("TRK-114", 0.35, 158211, "gt-device-002", "idle", "3AKJHHDR1MSMP1142",
             "Kenworth", "T680", 2022, DRIVER_2),
            ("TRK-207", 0.88, 88109, "gt-device-003", "idle", "1XKYDP9X4NJ207091",
             "Peterbilt", "579", 2024, DRIVER_3),
        ]
        vehicle_geo = {}  # geotab device_id -> (vehicle_number, driver_id, lat, lng, speed, heading)
        for num, fuel, odo, gt, status, vin, mk, mdl, yr, drv in vehicles:
            lat = round(41.87 + RNG.uniform(-0.4, 0.4), 5)
            lng = round(-87.62 + RNG.uniform(-0.5, 0.5), 5)
            speed = 58 if status == "moving" else 0
            heading = round(RNG.uniform(0, 359), 1)
            vehicle_geo[gt] = (num, drv, lat, lng, speed, heading)
            db.add(Vehicle(organization_id=ORG, carrier_id=CARRIER_A, vehicle_number=num,
                           vin=vin, make=mk, model=mdl, year=yr, status=status,
                           fuel_level_percent=round(fuel * 100, 1), odometer_miles=odo,
                           geotab_device_id=gt, current_driver_id=drv,
                           # migration 041 columns — full fleet-asset attributes
                           vehicle_type="tractor", fuel_type="diesel",
                           license_plate=f"IL {num.replace('-', '')}",
                           dot_number=f"DOT-{3100000 + int(num[-3:])}",
                           gross_vehicle_weight_kg=36287.0,  # ~80,000 lb Class-8 GVWR
                           engine_hours=round(odo / 48.0, 1),
                           registration_expiry=days_ago(-180),  # ~6 months out
                           inspection_due=days_ago(-90),        # ~3 months out
                           last_location={"latitude": lat, "longitude": lng, "speed": speed,
                                          "heading": heading, "timestamp": NOW.isoformat()}))
        # ---- optimized routes (Transportation → get_routes) --------------------
        # Standalone, org-scoped rows the /transportation/routes endpoint returns;
        # the Chicago→Dallas lane is linked from the outbound shipments below.
        db.add(Route(id=ROUTE_CHI_DAL, organization_id=ORG,
                     route_name="Chicago CHI-01 → Dallas DC", is_active=True,
                     origin={"city": "Chicago", "state": "IL", "latitude": 41.8781, "longitude": -87.6298},
                     destination={"city": "Dallas", "state": "TX", "latitude": 32.7767, "longitude": -96.7970},
                     waypoints=[{"city": "St. Louis", "state": "MO", "latitude": 38.627, "longitude": -90.199},
                                {"city": "Oklahoma City", "state": "OK", "latitude": 35.4676, "longitude": -97.5164}],
                     total_distance_miles=967, estimated_duration_hours=14.5,
                     fuel_cost_estimate=612.0, toll_cost_estimate=48.5,
                     optimization_criteria="balanced"))
        db.add(Route(id=ROUTE_CHI_MSP, organization_id=ORG,
                     route_name="Chicago CHI-01 → Minneapolis DC", is_active=True,
                     origin={"city": "Chicago", "state": "IL", "latitude": 41.8781, "longitude": -87.6298},
                     destination={"city": "Minneapolis", "state": "MN", "latitude": 44.9778, "longitude": -93.2650},
                     waypoints=[{"city": "Madison", "state": "WI", "latitude": 43.0731, "longitude": -89.4012}],
                     total_distance_miles=408, estimated_duration_hours=6.5,
                     fuel_cost_estimate=258.0, toll_cost_estimate=12.0,
                     optimization_criteria="fastest"))
        db.add(Route(id=ROUTE_CHI_DET, organization_id=ORG,
                     route_name="Chicago CHI-01 → Detroit plant", is_active=False,
                     origin={"city": "Chicago", "state": "IL", "latitude": 41.8781, "longitude": -87.6298},
                     destination={"city": "Detroit", "state": "MI", "latitude": 42.3314, "longitude": -83.0458},
                     waypoints=[], total_distance_miles=283, estimated_duration_hours=4.75,
                     fuel_cost_estimate=179.0, toll_cost_estimate=9.5,
                     optimization_criteria="cheapest"))
        await db.flush()  # routes before shipments reference them via route_id

        ships = [
            ("SHP-2201", "delivered", 3.0, 2.2, 2.4, DRIVER_1),   # on time
            ("SHP-2202", "delivered", 5.0, 4.1, 3.9, DRIVER_2),   # late
            ("SHP-2203", "delivered", 7.2, 6.5, 6.6, DRIVER_2),   # on time
            ("SHP-2204", "in_transit", 0.4, None, -0.6, DRIVER_1),
            ("SHP-2205", "planned", None, None, -2.0, None),
        ]
        for idx, (num, status, picked_d, delivered_d, sched_d, drv) in enumerate(ships):
            # scheduled_pickup was previously null -> UI showed "Invalid Date".
            sched_pickup_d = picked_d if picked_d is not None else (
                (sched_d + 0.5) if sched_d is not None else 0.0)
            db.add(Shipment(organization_id=ORG, carrier_id=CARRIER_A, driver_id=drv,
                            shipment_number=num, shipment_type="outbound", status=status,
                            origin={"name": "Plant CHI-01", "city": "Chicago", "state": "IL"},
                            destination={"name": "Dallas DC", "city": "Dallas", "state": "TX"},
                            route_id=ROUTE_CHI_DAL,
                            scheduled_pickup=days_ago(sched_pickup_d),
                            actual_pickup=days_ago(picked_d) if picked_d else None,
                            scheduled_delivery=days_ago(sched_d) if sched_d is not None else None,
                            actual_delivery=days_ago(delivered_d) if delivered_d else None,
                            priority="normal", total_weight_lbs=32000, total_pieces=18,
                            # migration 042 — PO / freight / pallet
                            po_number=f"PO-2020{idx + 1}",
                            freight_charge=round(1850.0 + idx * 175.0, 2),
                            pallet_count=18 + idx))
        db.add(GeofenceZone(organization_id=ORG, name="Plant CHI-01 Perimeter", zone_type="circle",
                            center_lat=41.8781, center_lng=-87.6298, radius_meters=800,
                            trigger_on="both", severity="warning"))
        db.add(GeofenceZone(organization_id=ORG, name="Customer DC — Dallas", zone_type="circle",
                            center_lat=32.7767, center_lng=-96.7970, radius_meters=1200,
                            trigger_on="entry", severity="info"))
        await db.flush()
        zone = (await db.execute(select(GeofenceZone).where(
            GeofenceZone.name == "Plant CHI-01 Perimeter",
            GeofenceZone.organization_id == ORG))).scalars().first()
        db.add(GeofenceAlert(organization_id=ORG, zone_id=str(zone.id), vehicle_id="TRK-081",
                             event_type="exit", severity="warning", acknowledged=True,
                             acknowledged_at=days_ago(0.4), created_at=days_ago(0.42),
                             location={"latitude": 41.87, "longitude": -87.64}))
        db.add(GeofenceAlert(organization_id=ORG, zone_id=str(zone.id), vehicle_id="TRK-114",
                             event_type="exit", severity="critical", acknowledged=False,
                             created_at=days_ago(0.05),
                             location={"latitude": 41.88, "longitude": -87.60}))
        db.add(MaintenanceSchedule(organization_id=ORG, vehicle_id="TRK-114",
                                   maintenance_type="oil_change", description="15k-mile service",
                                   due_date=days_ago(2), status="scheduled", estimated_cost=220.0))
        db.add(MaintenanceSchedule(organization_id=ORG, vehicle_id="TRK-081",
                                   maintenance_type="dot_inspection", description="Annual DOT inspection",
                                   due_date=NOW + timedelta(days=12), status="scheduled",
                                   estimated_cost=350.0))
        db.add(RepairOrder(organization_id=ORG, vehicle_id="TRK-207", title="Brake pad replacement",
                           status="in_progress", priority="high", vendor="Windy City Fleet Svc",
                           cost=980.0, category="brakes", opened_at=days_ago(1.2)))
        for title, cost, cat, d in [("Alternator replacement", 640.0, "electrical", 34),
                                    ("Tire rotation + 2 new steer tires", 1240.0, "tires", 61),
                                    ("Coolant leak repair", 415.0, "engine", 88)]:
            db.add(RepairOrder(organization_id=ORG, vehicle_id="TRK-081", title=title,
                               status="completed", priority="medium", cost=cost, category=cat,
                               opened_at=days_ago(d + 2), completed_at=days_ago(d)))

        # ---- GeoTab telematics (Fleet Health / DTCs / Security / live map) ------
        # Feeds app/api/fleet_health.py: _active_diagnostics reads DTCs with
        # status=="active"; _exceptions reads all exceptions; /vehicles/locations
        # reads the latest GeoTabTrip per device. device_id reuses the vehicles'
        # geotab_device_id so health/security/locations correlate to the fleet.
        # device, dtc_code, severity, description, status, last_seen_hours_ago
        diags = [
            ("gt-device-002", "P0301", "critical", "Cylinder 1 misfire detected", "active", 2.0),
            ("gt-device-002", "P0128", "medium", "Coolant thermostat below regulating temperature", "active", 5.0),
            ("gt-device-001", "P0420", "high", "Catalyst system efficiency below threshold (Bank 1)", "active", 9.0),
            ("gt-device-001", "P0442", "low", "Evaporative emission system small leak", "active", 20.0),
            ("gt-device-003", "B1318", "low", "Battery voltage low", "active", 12.0),
            ("gt-device-003", "C0035", "medium", "Left front wheel speed sensor circuit", "active", 30.0),
            ("gt-device-001", "U0100", "medium", "Lost communication with ECM/PCM", "resolved", 96.0),
        ]
        for dev, code, sev, desc, dstatus, h_ago in diags:
            num, drv, lat, lng, speed, heading = vehicle_geo[dev]
            db.add(GeoTabDiagnostic(
                device_id=dev, vehicle_id=num, organization_id=ORG,
                dtc_code=code, severity=sev, description=desc, status=dstatus,
                first_seen_at=NOW - timedelta(hours=h_ago + 6),
                last_seen_at=NOW - timedelta(hours=h_ago),
                cleared_at=(NOW - timedelta(hours=h_ago - 1)) if dstatus != "active" else None,
                battery_voltage=round(12.2 + RNG.uniform(-0.6, 0.8), 2),
                fuel_level=round(RNG.uniform(25, 90), 1),
                odometer=int(RNG.uniform(90000, 220000)),
                engine_hours=round(RNG.uniform(3000, 9000), 1)))

        # Safety/security exceptions (device_id matches the diagnostics' devices).
        # device, exception_type, severity, hours_ago, acknowledged, driver
        excs = [
            ("gt-device-001", "speeding", "high", 3.0, False, DRIVER_1),
            ("gt-device-001", "harsh_braking", "medium", 10.0, True, DRIVER_1),
            ("gt-device-002", "harsh_acceleration", "medium", 6.0, False, DRIVER_2),
            ("gt-device-002", "after_hours", "low", 26.0, True, DRIVER_2),
            ("gt-device-003", "speeding", "critical", 1.0, False, DRIVER_3),
            ("gt-device-003", "geofence", "high", 40.0, True, DRIVER_3),
        ]
        for dev, etype, sev, h_ago, acked, drv in excs:
            num, ddrv, lat, lng, speed, heading = vehicle_geo[dev]
            db.add(GeoTabException(
                device_id=dev, driver_id=drv, organization_id=ORG,
                exception_type=etype, severity=sev,
                timestamp=NOW - timedelta(hours=h_ago),
                location={"latitude": round(lat + RNG.uniform(-0.05, 0.05), 5),
                          "longitude": round(lng + RNG.uniform(-0.05, 0.05), 5),
                          "address": "IL-355 near Downers Grove"},
                details={"value": round(RNG.uniform(1.1, 1.6), 2), "threshold": 1.0},
                acknowledged=acked,
                acknowledged_by=USER if acked else None,
                acknowledged_at=(NOW - timedelta(hours=h_ago - 0.5)) if acked else None))

        # Latest trip per device -> /vehicles/locations (live fleet map).
        for dev, (num, drv, lat, lng, speed, heading) in vehicle_geo.items():
            start = NOW - timedelta(hours=3)
            end = NOW - timedelta(minutes=int(RNG.uniform(5, 45)))
            db.add(GeoTabTrip(
                device_id=dev, vehicle_id=num, driver_id=drv, organization_id=ORG,
                start_time=start, end_time=end,
                duration_seconds=int((end - start).total_seconds()),
                start_location={"latitude": 41.8781, "longitude": -87.6298,
                                "address": "Plant CHI-01", "speed": 0, "heading": 0},
                end_location={"latitude": lat, "longitude": lng,
                              "address": "En route", "speed": speed, "heading": heading},
                distance_miles=round(RNG.uniform(20, 140), 1),
                idle_time_seconds=int(RNG.uniform(120, 900)),
                status="completed"))

        # ---- operations (Operations page + PackML history) ---------------------
        # A cadence of machining jobs; the vibration-fault window shows an idle
        # gap (day -2 -> -1) while WO-77105 replaces the spindle bearing.
        op_rows = 0
        for j in range(10):
            d = 12 - j * 1.2
            faulted = ALARM_D <= d <= (ALARM_D + 1.3)
            status = "idle" if faulted else "completed"
            planned = 90  # OperationResponse types durations as int minutes
            actual = int(round(planned + RNG.uniform(-8, 22)))
            db.add(Operation(
                asset_id=A_CNC, operation_name=f"Machine bracket lot LOT-{4400 + j}",
                job_id=f"JOB-{5200 + j}", status=status,
                started_at=days_ago(d), completed_at=days_ago(max(0.05, d - actual / 1440)),
                planned_duration=planned, actual_duration=actual,
                packml_state_durations={"Execute": actual * 60, "Idle": 300, "Held": 120 if faulted else 0},
                meta_data={"parts": 40, "good": 39 if not faulted else 31}))
            op_rows += 1
        # a live one in progress + a conveyor job
        db.add(Operation(asset_id=A_CNC, operation_name="Machine bracket lot LOT-4410",
                         job_id="JOB-5210", status="running", started_at=days_ago(0.05),
                         planned_duration=90,
                         packml_state_durations={"Execute": 2400}, meta_data={"parts": 12, "good": 12}))
        db.add(Operation(asset_id=A_CONVEYOR, operation_name="Palletize finished goods",
                         job_id="JOB-6001", status="running", started_at=days_ago(0.1),
                         planned_duration=480, packml_state_durations={"Execute": 6000}))
        op_rows += 2

        # ---- Kanban board (Operations Board) -----------------------------------
        db.add(TaskBoard(id=BOARD_ID, organization_id=ORG, name="Operations Board",
                         board_type="unified", is_active=True))
        col_meta = [("Backlog", "backlog", 0, 50, "#6B7280"),
                    ("Triage", "triage", 1, 20, "#F59E0B"),
                    ("In Progress", "in_progress", 2, 10, "#3B82F6"),
                    ("Review", "review", 3, 15, "#8B5CF6"),
                    ("Rejected", "rejected", 4, 10, "#EF4444"),
                    ("Done", "done", 5, 100, "#10B981")]
        for name, ctype, pos, wip, color in col_meta:
            db.add(TaskColumn(id=COL_IDS[ctype], board_id=BOARD_ID, name=name,
                              position=pos, wip_limit=wip, column_type=ctype, color=color))
        await db.flush()  # board + columns before tasks/rule reference them

        # id, title, type, priority, status, column, asset, extras
        #
        # Shaped like a real shift board: work spread across every column, a
        # blocked item, an emergency, a rejected one, subtasks under a parent,
        # checklists mid-progress, and logged time against estimates. A demo
        # board where every card looks the same tells you nothing about the UI.
        tasks = [
            # ---- In Progress (under the WIP limit of 10) ----------------------
            (TASK_IDS[0], "Investigate VIB_HIGH on CNC Spindle vibration sensor",
             "alarm_response", "high", "in_progress", "in_progress", A_VIB,
             {"alarm_id": None, "progress_percent": 60, "assigned_to": USER,
              "assigned_by": USER, "assigned_at": days_ago(1),
              "actual_start": NOW - timedelta(hours=3),
              "estimated_effort_minutes": 120, "time_logged_minutes": 75,
              "tags": ["vibration", "predictive"],
              "checklist_items": [
                  {"text": "Pull 24h vibration trend", "completed": True},
                  {"text": "Cross-check acoustic feed", "completed": True},
                  {"text": "Inspect bearing housing", "completed": False},
              ]}),
            (TASK_IDS[1], "Changeover: Product A → Product B on Conveyor #1",
             "changeover", "medium", "in_progress", "in_progress", A_CONVEYOR,
             {"progress_percent": 60, "assigned_to": USER,
              "actual_start": NOW - timedelta(hours=2),
              "planned_duration": 90, "estimated_effort_minutes": 90,
              "time_logged_minutes": 55, "tags": ["changeover"],
              "checklist_items": [
                  {"text": "Purge line", "completed": True},
                  {"text": "Swap tooling", "completed": True},
                  {"text": "First-article check", "completed": False},
              ]}),
            (TASK_IDS[2], "Calibrate vision system on CNC Mill #1",
             "maintenance_cm", "high", "in_progress", "in_progress", A_CNC,
             {"progress_percent": 35, "assigned_to": USER,
              "actual_start": NOW - timedelta(hours=4),
              "estimated_effort_minutes": 180, "time_logged_minutes": 60}),

            # ---- Blocked (status the board must be able to show) --------------
            (TASK_IDS[3], "Replace vibration sensor mount — CNC Spindle",
             "maintenance_cm", "high", "blocked", "in_progress", A_VIB,
             {"progress_percent": 20, "assigned_to": USER,
              "actual_start": days_ago(1), "tags": ["waiting-parts"],
              "custom_fields": {"blocked_reason": "Thermistor on backorder — PO-10044 ETA 3 days"}}),

            # ---- Triage --------------------------------------------------------
            (TASK_IDS[4], "Emergency stop triggered on Conveyor #1 — verify before restart",
             "command_execution", "emergency", "ready", "triage", A_CONVEYOR,
             {"due_date": NOW + timedelta(hours=1), "tags": ["safety", "e-stop"],
              "color_code": "#EF4444"}),
            (TASK_IDS[5], "Follow up on TRL-4482 detention (aluminum billet)",
             "material_request", "high", "ready", "triage", None,
             {"due_date": NOW + timedelta(hours=6), "tags": ["logistics"]}),
            (TASK_IDS[6], "High temperature on CNC spindle — 15°C above threshold",
             "alarm_response", "critical", "ready", "triage", A_CNC,
             {"due_date": NOW + timedelta(hours=2), "tags": ["thermal"]}),

            # ---- Review --------------------------------------------------------
            (TASK_IDS[7], "Review acoustic anomaly (bearing-wear signature)",
             "quality_inspection", "medium", "in_progress", "review", A_AUDIO,
             {"progress_percent": 90, "assigned_to": USER,
              "estimated_effort_minutes": 60, "time_logged_minutes": 50}),
            (TASK_IDS[8], "Quality inspection results — Batch #4521 (2% defect rate)",
             "quality_inspection", "high", "in_progress", "review", A_CNC,
             {"progress_percent": 80, "assigned_to": USER,
              "approval_status": "pending", "tags": ["quality", "rca"]}),

            # ---- Rejected (so the column isn't empty in the demo) -------------
            (TASK_IDS[9], "Request second dock camera for Door 3",
             "custom", "low", "cancelled", "rejected", A_CAMERA,
             {"approval_status": "rejected", "approved_by": USER,
              "approved_at": days_ago(4),
              "rejection_reason": "Deferred to next capex cycle; existing coverage adequate."}),

            # ---- Backlog -------------------------------------------------------
            (TASK_IDS[10], "Calibrate Dock Camera — Door 3 motion detection",
             "safety_check", "low", "ready", "backlog", A_CAMERA,
             {"estimated_effort_minutes": 45}),
            (TASK_IDS[11], "Monthly PM — acoustic monitor calibration and clean",
             "maintenance_pm", "medium", "ready", "backlog", A_AUDIO,
             {"planned_start": NOW + timedelta(days=3), "planned_duration": 120,
              "estimated_effort_minutes": 120, "tags": ["pm", "scheduled"]}),
            (TASK_IDS[12], "Verify SKF bearing kit receipt (PO-10021)",
             "custom", "medium", "draft", "backlog", None, {}),
            (TASK_IDS[13], "Quarterly safety audit — guarding and interlocks",
             "safety_check", "medium", "ready", "backlog", None,
             {"planned_start": NOW + timedelta(days=10),
              "estimated_effort_minutes": 240, "tags": ["audit", "compliance"]}),
            (TASK_IDS[14], "Update PM schedule after bearing replacement",
             "custom", "low", "draft", "backlog", A_CNC, {}),

            # ---- Done ----------------------------------------------------------
            (TASK_IDS[15], "Replace spindle bearing — CNC Mill #1 (WO-77105)",
             "maintenance_cm", "critical", "completed", "done", A_CNC,
             # `work_order_id` is a native uuid column (migrations 003/004); "WO-77105" is a
             # human work-order NUMBER and asyncpg rejects it outright. The number belongs in
             # custom_fields, which is where a business reference with no typed home goes.
             {"custom_fields": {"work_order_ref": "WO-77105"}, "progress_percent": 100,
              "approval_status": "approved", "approved_by": USER,
              "approved_at": days_ago(FIXED_D + 1),
              "completed_by": USER, "completed_at": days_ago(FIXED_D),
              "actual_start": days_ago(FIXED_D + 1), "actual_end": days_ago(FIXED_D),
              "estimated_effort_minutes": 240, "time_logged_minutes": 265,
              "tags": ["bearing", "unplanned"]}),
            (TASK_IDS[16], "Belt tension check — Conveyor #1",
             "maintenance_pm", "medium", "completed", "done", A_CONVEYOR,
             {"progress_percent": 100, "completed_by": USER,
              "completed_at": days_ago(6), "estimated_effort_minutes": 60,
              "time_logged_minutes": 45}),
            (TASK_IDS[17], "Firmware update — edge collector to 1.8.2",
             "custom", "low", "completed", "done", A_CAMERA,
             {"progress_percent": 100, "completed_by": USER,
              "completed_at": days_ago(9), "tags": ["ota", "firmware"]}),
        ]
        for i, (tid, title, ttype, prio, tstatus, col, asset, extra) in enumerate(tasks):
            # approved_by/completed_by are NOT NULL under ORM create_all (the
            # model's UUIDForeignKey defaults to non-null); default them to the
            # demo user and let per-task extras override. They are nullable in
            # the migration-built schema, so this is harmless there.
            kwargs = {"approved_by": USER, "completed_by": USER}
            kwargs.update(extra)
            db.add(Task(id=tid, board_id=BOARD_ID, column_id=COL_IDS[col], position=i,
                        title=title, task_type=ttype, priority=prio, status=tstatus,
                        asset_id=asset, created_by=USER, **kwargs))
        await db.flush()  # tasks before comments reference them
        # A readable thread on the flagship task, plus activity on the blocked and
        # rejected cards — the comment types (comment / status_change / time_log /
        # approval_action) all need to appear for the detail view to be exercised.
        db.add(TaskComment(task_id=TASK_IDS[0], user_id=USER, comment_type="comment",
                           content="Vibration hit 8.3 mm/s — pulled acoustic feed, high-band energy confirms bearing wear."))
        db.add(TaskComment(task_id=TASK_IDS[0], user_id=USER, comment_type="status_change",
                           content="Moved to In Progress; SAP work order WO-77105 released.",
                           extra_data={"before_state": "ready", "after_state": "in_progress"}))
        db.add(TaskComment(task_id=TASK_IDS[0], user_id=USER, comment_type="time_log",
                           content="75 min: trend review + acoustic cross-check.",
                           extra_data={"minutes": 75}))
        db.add(TaskComment(task_id=TASK_IDS[0], user_id=USER, comment_type="comment",
                           content="Housing inspection scheduled with the next planned stop to avoid an unplanned line halt."))
        db.add(TaskComment(task_id=TASK_IDS[3], user_id=USER, comment_type="status_change",
                           content="Blocked: thermistor on backorder, PO-10044 raised.",
                           extra_data={"before_state": "in_progress", "after_state": "blocked"}))
        db.add(TaskComment(task_id=TASK_IDS[9], user_id=USER, comment_type="approval_action",
                           content="Rejected — deferred to next capex cycle; existing coverage adequate.",
                           extra_data={"decision": "rejected"}))
        db.add(TaskComment(task_id=TASK_IDS[15], user_id=USER, comment_type="time_log",
                           content="265 min against a 240 min estimate; bearing seized on the shaft.",
                           extra_data={"minutes": 265}))

        # premade-style automation rule
        db.add(TaskRule(id=TASK_RULE_ID, organization_id=ORG,
                        rule_name="Auto-triage critical alarms",
                        description="Create an alarm-response task when a high/critical alarm is raised.",
                        is_active=True, is_system_rule=True, trigger_type="alarm_created",
                        trigger_conditions={"severity": ["high", "critical"]},
                        target_board_id=BOARD_ID, target_column_id=COL_IDS["triage"],
                        task_template={"title": "Respond to {alarm_code} on {asset_name}",
                                       "priority": "high", "task_type": "alarm_response"},
                        assignee_rule="asset_owner", specific_assignee_id=USER,
                        created_by=USER))

        # ---- MLOps model registry ---------------------------------------------
        db.add(ModelRegistryEntry(
            id=MODEL_ANOMALY_ID, organization_id=ORG, name="anomaly", version="1.4.0",
            framework="torchscript",
            artifact_storage_key="s3://omniusgrid-demo/models/anomaly/1.4.0/model.pt",
            checksum_sha256="a" * 64,
            feature_contract={"features": ["vibration_rms", "temperature", "spindle_load"],
                              "normalization": "zscore"},
            metrics={"auc": 0.972, "precision": 0.94, "recall": 0.89},
            release_notes="Bearing-wear anomaly detector trained on 14d of CHI-01 telemetry.",
            status="published", created_by=USER))
        db.add(ModelRegistryEntry(
            id=MODEL_OEE_ID, organization_id=ORG, name="oee_forecast", version="0.9.1",
            framework="torchscript",
            artifact_storage_key="s3://omniusgrid-demo/models/oee_forecast/0.9.1/model.pt",
            checksum_sha256="b" * 64,
            feature_contract={"features": ["spindle_rpm", "spindle_load", "tool_temperature"]},
            metrics={"mae": 3.1, "mape": 0.041}, status="draft", created_by=USER))

        # ---- Edge fleet / OTA (config release + rollout + model release) -------
        db.add(AgentRelease(
            id=AGENT_RELEASE_ID, organization_id=ORG, version="1.4.0", channel="stable",
            image_tag="omniusgrid/edge-agent:1.4.0", artifact_type="config",
            bundle_storage_key="s3://omniusgrid-demo/releases/1.4.0/config-bundle.tar.gz",
            checksum_sha256="c" * 64, signature_ed25519="ed25519:" + "1" * 86,
            signing_key_id="demo-signing-key-01",
            release_notes="Adds bearing-wear anomaly thresholds + acoustic band monitoring.",
            status="published", created_by=USER))
        db.add(AgentRelease(
            id=MODEL_RELEASE_ID, organization_id=ORG, version="1.4.0", channel="anomaly",
            artifact_type="model", model_name="anomaly",
            bundle_storage_key="s3://omniusgrid-demo/releases/model-anomaly-1.4.0/model.pt",
            checksum_sha256="d" * 64, signature_ed25519="ed25519:" + "2" * 86,
            signing_key_id="demo-signing-key-01",
            release_notes="OTA model rollout of anomaly detector 1.4.0.",
            status="published", created_by=USER))
        await db.flush()  # releases before rollout references them
        db.add(AgentRollout(
            id=ROLLOUT_ID, organization_id=ORG, release_id=AGENT_RELEASE_ID,
            name="CHI-01 edge agents → 1.4.0",
            target_selector={"sensor_class": ["machinery", "audio", "video"]},
            strategy={"waves": [{"percent": 40}, {"percent": 100}], "soak_minutes": 30},
            status="running", created_by=USER))
        await db.flush()  # rollout before targets/events reference it
        rollout_assets = [(A_CNC, "success", 0), (A_VIB, "success", 0), (A_AUDIO, "success", 0),
                          (A_CAMERA, "updating", 1), (A_CONVEYOR, "pending", 1)]
        for aid, tstatus, wave in rollout_assets:
            db.add(AgentRolloutTarget(
                rollout_id=ROLLOUT_ID, organization_id=ORG, asset_id=aid, wave_index=wave,
                status=tstatus, current_version="1.3.2" if tstatus != "success" else "1.4.0",
                attempts=1 if tstatus != "pending" else 0,
                dispatched_at=days_ago(0.2) if tstatus != "pending" else None,
                completed_at=days_ago(0.15) if tstatus == "success" else None,
                last_event_at=days_ago(0.15) if tstatus != "pending" else None))
        for etype, aid, d in [("rollout_started", None, 0.25), ("target_dispatched", A_CNC, 0.24),
                              ("target_succeeded", A_CNC, 0.2), ("target_succeeded", A_VIB, 0.19),
                              ("target_succeeded", A_AUDIO, 0.18), ("target_dispatched", A_CAMERA, 0.1)]:
            db.add(AgentRolloutEvent(rollout_id=ROLLOUT_ID, organization_id=ORG,
                                     event_type=etype, asset_id=aid,
                                     detail={"version": "1.4.0"}, created_at=days_ago(d)))

        # ---- Compliance + Registries -------------------------------------------
        db.add(ActionableRegistry(
            id=REGISTRY_LOTO_ID, organization_id=ORG, registry_name="OSHA 1910.147 (LOTO)",
            registry_type="safety", registry_category="lockout_tagout",
            description="Control of hazardous energy during machine servicing.",
            is_active=True, is_compliance=True, frequency="quarterly",
            next_due_date=NOW + timedelta(days=30), last_completed_date=days_ago(60),
            compliance_score=88, priority_level="high", assigned_owner_id=USER,
            reference_url="https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.147",
            created_by=USER))
        db.add(ActionableRegistry(
            id=REGISTRY_ISO_ID, organization_id=ORG, registry_name="ISO 9001:2015 QMS",
            registry_type="quality", registry_category="qms",
            description="Quality management system requirements.",
            is_active=True, is_compliance=True, frequency="annually",
            next_due_date=NOW + timedelta(days=120), compliance_score=93,
            priority_level="medium", assigned_owner_id=USER, created_by=USER))
        await db.flush()  # registries before their items
        loto_items = [
            ("1910.147(c)(4)", "Energy control procedures documented", "high", "documentation"),
            ("1910.147(c)(6)", "Periodic inspection of procedures", "high", "audit"),
            ("1910.147(c)(7)", "Employee LOTO training current", "medium", "documentation"),
        ]
        # related_task_id is NOT NULL under ORM create_all (nullable in the
        # migration schema); point it at the demo alarm-response task.
        for code, name, sev, method in loto_items:
            db.add(ActionableRegistryItem(
                registry_id=REGISTRY_LOTO_ID, item_code=code, item_name=name,
                item_description=name, severity_level=sev, is_required=True,
                verification_method=method, completion_frequency="quarterly",
                compliance_score=90, next_due_at=NOW + timedelta(days=30),
                last_completed_at=days_ago(60), related_task_id=TASK_IDS[0]))
        db.add(ActionableRegistryItem(
            registry_id=REGISTRY_ISO_ID, item_code="8.5.1", item_name="Control of production",
            item_description="Production under controlled conditions.", severity_level="medium",
            verification_method="audit", completion_frequency="annually", compliance_score=95,
            related_task_id=TASK_IDS[0]))

        db.add(ScheduledComplianceReport(
            id=COMPLIANCE_SCHEDULE_ID, organization_id=ORG, name="Monthly SOC 2 report",
            framework="soc2", format="pdf", frequency="monthly", timezone="UTC",
            next_run_at=NOW + timedelta(days=14),
            recipients=["admin@omniusgrid.com"], is_active=True,
            last_run_at=days_ago(16), last_status="completed", created_by=USER))
        await db.flush()  # schedule before job references it
        db.add(ComplianceReportJob(
            id=COMPLIANCE_JOB_ID, organization_id=ORG, requested_by=USER,
            schedule_id=COMPLIANCE_SCHEDULE_ID, scheduled_for=days_ago(16),
            framework="soc2", format="pdf", recipients=["admin@omniusgrid.com"],
            report_status="completed", delivery_status="sent", generation_attempts=1,
            email_attempts=1, filename="soc2-2026-06.pdf", media_type="application/pdf",
            file_size=284100, file_sha256="e" * 64,
            started_at=days_ago(16.02), completed_at=days_ago(16.0),
            published_at=days_ago(16.0), email_sent_at=days_ago(15.99)))

        # ---- Notifications ------------------------------------------------------
        db.add(NotificationSubscription(
            id=NOTIF_SUB_IDS[0], organization_id=ORG, name="Critical alarms → Ops webhook",
            channel="webhook", target="https://hooks.demo.omniusgrid.local/alarms",
            min_severity="critical", domain="alarms", enabled=True))
        db.add(NotificationSubscription(
            id=NOTIF_SUB_IDS[1], organization_id=ORG, name="Maintenance email digest",
            channel="email", target="maintenance@omniusgrid.com",
            min_severity="warning", domain="maintenance", enabled=True))
        db.add(NotificationSubscription(
            id=NOTIF_SUB_IDS[2], organization_id=ORG, name="Yard detention Slack alerts",
            channel="slack", target="https://hooks.slack.com/services/DEMO/YARD/xxxx",
            min_severity="warning", domain="yard", enabled=True))
        deliveries = [
            (NOTIF_SUB_IDS[0], "webhook", "critical", "VIB_HIGH on CNC Spindle", True, "200 OK", 2.0),
            (NOTIF_SUB_IDS[1], "email", "warning", "Oil change overdue — TRK-114", True, "delivered", 2.0),
            (NOTIF_SUB_IDS[2], "slack", "warning", "TRL-4482 entering detention", True, "ok", 0.2),
            (NOTIF_SUB_IDS[0], "webhook", "critical", "Geofence exit — TRK-114", False,
             "connection timeout", 0.05),
        ]
        for sub, ch, sev, title, ok, detail, d in deliveries:
            db.add(NotificationDelivery(organization_id=ORG, subscription_id=sub, channel=ch,
                                        severity=sev, title=title, message=title,
                                        delivered=ok, detail=detail, created_at=days_ago(d)))

        # ---- Error Triage -------------------------------------------------------
        errors = [
            (ERROR_FINGERPRINTS[0], "IntegrityError",
             "POST /api/v1/kanban/tasks", "POST", 500,
             "duplicate key value violates unique constraint", 7, 12.0, 0.3),
            (ERROR_FINGERPRINTS[1], "TimeoutError",
             "GET /api/v1/erp/integrations/{id}/entities", "GET", 504,
             "SAP OData request timed out after 30s", 3, 9.0, 1.1),
            (ERROR_FINGERPRINTS[2], "ValidationError",
             "POST /api/v1/telemetry/ingest", "POST", 422,
             "metric_name is required", 21, 13.5, 0.05),
            (ERROR_FINGERPRINTS[3], "KeyError",
             "GET /api/v1/oee/dashboard/summary", "GET", 500,
             "'ideal_cycle_time'", 2, 6.0, 4.0),
        ]
        for fp, etype, route, method, code, msg, cnt, first_d, last_d in errors:
            db.add(ErrorEvent(fingerprint=fp, exception_type=etype, route=route, method=method,
                              status_code=code, message_sample=msg, total_count=cnt,
                              status="open", first_seen=days_ago(first_d),
                              last_seen=days_ago(last_d), organization_id=ORG))
            await db.flush()  # error_event PK before its buckets FK it
            # hourly buckets within the last 7d so count_in_range is non-zero
            remaining = cnt
            for h in range(min(cnt, 6)):
                per = max(1, remaining // (min(cnt, 6) - h)) if (min(cnt, 6) - h) else remaining
                db.add(ErrorEventBucket(fingerprint=fp,
                                        bucket_hour=(NOW - timedelta(days=last_d, hours=h)).replace(
                                            minute=0, second=0, microsecond=0),
                                        count=per))
                remaining -= per

        # ---- Exports ------------------------------------------------------------
        db.add(ExportTemplate(
            id=EXPORT_TEMPLATE_IDS[0], organization_id=ORG, name="Weekly OEE summary",
            description="Fleet OEE rollup for the plant weekly review.",
            export_type="oee", export_format="pdf",
            columns=["asset_name", "oee", "availability", "performance", "quality"],
            filters={"period": "7d"}, created_by=USER))
        db.add(ExportTemplate(
            id=EXPORT_TEMPLATE_IDS[1], organization_id=ORG, name="Open Kanban tasks",
            description="All non-completed operations-board tasks.",
            export_type="kanban", export_format="xlsx",
            columns=["title", "task_type", "priority", "status", "assigned_to"],
            filters={"status": "!completed"}, created_by=USER))

        # ---- Historian retention policy ----------------------------------------
        db.add(HistorianRetentionPolicy(
            organization_id=_uuid.UUID(ORG), metric_name="*", hot_retention_days=30,
            warm_retention_days=365, cold_retention_days=1825, ingestion_priority=3,
            archival_enabled=True, created_by=_uuid.UUID(USER)))
        db.add(HistorianRetentionPolicy(
            organization_id=_uuid.UUID(ORG), metric_name="vibration_rms", hot_retention_days=90,
            warm_retention_days=730, cold_retention_days=1825, ingestion_priority=1,
            archival_enabled=True, created_by=_uuid.UUID(USER)))
        print(f"  operations: {op_rows}, kanban tasks: {len(tasks)}, "
              f"rollout targets: {len(rollout_assets)}, registries: 2, errors: {len(errors)}")

        await db.commit()

        # ---- ready-made Correlation AI session ---------------------------------
        from app.services.platform_correlation import (
            asset_telemetry_provider, erp_provider, yard_provider,
        )
        db.add(AnalysisSession(id=SESSION_ID, user_id=USER, organization_id=ORG,
                               title="Demo: Spindle failure investigation",
                               description="ERP work orders + vibration telemetry + yard arrivals",
                               status="active"))
        await db.flush()
        for source_type, params in [
            ("erp", {"integration_id": ERP_INT}),
            ("asset_telemetry", {"asset_id": A_VIB, "name": "vibration — CNC spindle"}),
            ("yard", {}),
        ]:
            provider = {"erp": erp_provider, "asset_telemetry": asset_telemetry_provider,
                        "yard": yard_provider}[source_type]
            result = await provider(db, ORG, params)
            # `source_id` is the id of the row this source came FROM, and a platform-wide
            # source like the yard has no such row. Falling back to the source_type string
            # put "yard" in a column every consumer reads as a uuid: `AddDataSourceRequest`
            # and `DataSourceResponse` both declare `Optional[UUID]`, so the API itself
            # cannot produce this — the seed was the only writer that did, and it made
            # GET /nlp/sessions/{id}/data 500 on the documented demo session. The panel on
            # the Correlation AI page failed to load every time it was opened.
            source_row_id = params.get("asset_id") or params.get("integration_id")
            db.add(SessionDataSource(session_id=SESSION_ID, source_type=source_type,
                                     source_id=str(source_row_id) if source_row_id else None,
                                     file_name=result.file_name, data_type="spreadsheet",
                                     processed_data=result.to_processed_data(),
                                     meta_data={"platform_source": True, "source_type": source_type}))
        await db.commit()

        # ---- summary -----------------------------------------------------------
        from sqlalchemy import func
        counts = {}
        for label, model in [("telemetry", Telemetry), ("erp_entities", ERPEntity),
                             ("erp_events", ERPIntegrationEvent), ("trailers", YardTrailer),
                             ("shipments", Shipment), ("vehicles", Vehicle),
                             ("alarms", Alarm), ("routes", Route),
                             ("geotab_dtcs", GeoTabDiagnostic),
                             ("geotab_exceptions", GeoTabException),
                             ("geotab_trips", GeoTabTrip),
                             ("operations", Operation), ("kanban_tasks", Task),
                             ("agent_releases", AgentRelease), ("rollout_targets", AgentRolloutTarget),
                             ("models", ModelRegistryEntry), ("registries", ActionableRegistry),
                             ("notif_subs", NotificationSubscription), ("error_events", ErrorEvent),
                             ("export_templates", ExportTemplate)]:
            counts[label] = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        print("  seeded:", ", ".join(f"{k}={v}" for k, v in counts.items()))
        print(f"  analysis session ready: 'Demo: Spindle failure investigation' ({SESSION_ID})")

    # The relaxation lived on a dedicated engine, so disposing it is what restores normal
    # FK enforcement — and it must actually happen. Resetting the GUC on one connection, as
    # this used to do, left every OTHER pooled connection carrying `replica` as its session
    # default, because it is a startup parameter now rather than a runtime SET.
    if bulk_engine is not None:
        await bulk_engine.dispose()

    if not verify:
        print("\nDone. Run the API against this data:")
        print(f"  DATABASE_URL='{os.environ['DATABASE_URL']}' uvicorn app.main:app --port 8000")
        print("  (frontend: VITE_USE_MOCK=false npm run dev)")
    return 0


def run_verify() -> int:
    """Hit the seeded data through the real API (in-process, no deployment).

    Synchronous on purpose: ``TestClient`` drives the app lifespan on its own
    event loop, so this must run OUTSIDE the seeding ``asyncio.run`` loop. The
    module-level async engine still holds a pool bound to the (now closed)
    seeding loop, so dispose it first — fresh connections are then created on
    ``TestClient``'s loop.
    """
    import asyncio as _asyncio
    from fastapi.testclient import TestClient
    from app.db.database import engine
    from app.main import app

    _asyncio.run(engine.dispose())

    AUTH = {"Authorization": "Bearer dev-token"}
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if detail and not cond else ""))

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get(f"/api/v1/erp/integrations/{ERP_INT}/entities", headers=AUTH)
        ents = r.json() if r.status_code == 200 else []
        check("ERP entities synced (incl. WO-77105)", any(e["entity_id"] == "WO-77105" for e in ents), r.text[:150])

        r = client.get(f"/api/v1/erp/integrations/{ERP_INT}/sync-status", headers=AUTH)
        check("ERP sync-status green", r.status_code == 200 and
              all(s["last_sync_status"] == "success" for s in r.json()), r.text[:150])

        r = client.get(f"/api/v1/telemetry/{A_VIB}/history", headers=AUTH,
                       params={"metric_name": "vibration_rms", "aggregation": "1hour",
                               "start_time": days_ago(14).isoformat()})
        payload = r.json() if r.status_code == 200 else {}
        # FS-89: telemetry history returns a {items, meta} envelope now.
        rows = payload.get("items", payload) if isinstance(payload, dict) else payload
        peak = max((x["max"] for x in rows), default=0)
        check("vibration degradation arc visible (peak > 7 mm/s)", peak > 7, f"peak={peak}")

        r = client.get(f"/api/v1/assets/{A_AUDIO}/sensor-feeds", headers=AUTH)
        check("audio sensor feeds discoverable", r.status_code == 200 and
              "audio_band_high" in r.json().get("metrics", []), r.text[:150])

        # Every panel the demo session opens must load. This one 500'd for as long as the
        # seed existed, because it wrote a non-uuid into `source_id`.
        r = client.get(f"/api/v1/nlp/sessions/{SESSION_ID}/data", headers=AUTH)
        check("session data-sources panel loads", r.status_code == 200, r.text[:150])

        r = client.get("/api/v1/yard/detention-alerts", headers=AUTH)
        alerts = r.json() if r.status_code == 200 else []
        check("TRL-4482 accruing detention", any(a["trailer_number"] == "TRL-4482"
              and a["status"] == "detention" for a in alerts), r.text[:150])

        r = client.get("/api/v1/logistics/delivery-efficiency", headers=AUTH)
        check("delivery efficiency computed", r.status_code == 200 and
              r.json().get("totalDelivered", 0) >= 3, r.text[:150])

        r = client.get("/api/v1/maintenance/statistics", headers=AUTH)
        check("maintenance stats (overdue oil change + YTD costs)",
              r.status_code == 200 and r.json().get("overdueCount", 0) >= 1
              and r.json().get("ytdCosts", 0) > 0, r.text[:150])

        r = client.post(f"/api/v1/nlp/sessions/{SESSION_ID}/correlate", headers=AUTH, json={})
        check("pre-built session correlates (ERP + sensor + yard)",
              r.status_code == 200 and "analysis" in r.json(), r.text[:200])

        # ---- gap-area pages (Kanban, Operations, Fleet/OTA, MLOps, etc.) -------
        r = client.get("/api/v1/kanban/board", headers=AUTH)
        j = r.json() if r.status_code == 200 else {}
        check("kanban board has columns + tasks",
              r.status_code == 200 and len(j.get("columns", [])) == 6 and len(j.get("tasks", [])) >= 5,
              r.text[:150])

        r = client.get("/api/v1/kanban/tasks", headers=AUTH)
        check("kanban tasks list non-empty",
              r.status_code == 200 and len(r.json()) >= 5, r.text[:150])

        r = client.get("/api/v1/operations/", headers=AUTH)
        check("operations list non-empty",
              r.status_code == 200 and r.json().get("meta", {}).get("total", 0) >= 10, r.text[:150])

        r = client.get("/api/v1/oee/dashboard/summary", headers=AUTH)
        check("OEE dashboard summary lists assets",
              r.status_code == 200 and r.json().get("aggregate", {}).get("asset_count", 0) >= 5,
              r.text[:150])

        r = client.get("/api/v1/fleet/releases", headers=AUTH)
        check("fleet agent releases non-empty",
              r.status_code == 200 and any(x["version"] == "1.4.0" for x in r.json()), r.text[:150])

        r = client.get("/api/v1/fleet/rollouts", headers=AUTH)
        check("fleet OTA rollout present",
              r.status_code == 200 and len(r.json()) >= 1, r.text[:150])

        r = client.get("/api/v1/models", headers=AUTH)
        check("MLOps model registry non-empty",
              r.status_code == 200 and any(m["name"] == "anomaly" for m in r.json()), r.text[:150])

        r = client.get("/api/v1/notifications/subscriptions", headers=AUTH)
        check("notification subscriptions non-empty",
              r.status_code == 200 and len(r.json()) >= 3, r.text[:150])

        r = client.get("/api/v1/notifications/log", headers=AUTH)
        check("notification delivery log non-empty",
              r.status_code == 200 and len(r.json()) >= 3, r.text[:150])

        r = client.get("/api/v1/admin/errors", headers=AUTH)
        check("error triage list non-empty",
              r.status_code == 200 and r.json().get("total", 0) >= 3, r.text[:150])

        r = client.get("/api/v1/registries", headers=AUTH)
        check("actionable registries non-empty",
              r.status_code == 200 and len(r.json()) >= 2, r.text[:150])

        r = client.get(f"/api/v1/registries/{REGISTRY_LOTO_ID}/items", headers=AUTH)
        check("registry items non-empty",
              r.status_code == 200 and len(r.json()) >= 3, r.text[:150])

        r = client.get("/api/v1/compliance/reports/schedules", headers=AUTH)
        check("scheduled compliance reports non-empty",
              r.status_code == 200 and len(r.json().get("items", [])) >= 1, r.text[:150])

        r = client.get("/api/v1/exports/templates", headers=AUTH)
        et = r.json() if r.status_code == 200 else []
        et = et.get("items", et) if isinstance(et, dict) else et
        check("export templates non-empty",
              r.status_code == 200 and len(et) >= 2, r.text[:150])

        r = client.get("/api/v1/historian/query", headers=AUTH, params={
            "asset_id": A_VIB, "metric": "vibration_rms",
            "start": days_ago(14).isoformat(), "end": NOW.isoformat(), "granularity": "raw"})
        check("historian query returns points",
              r.status_code == 200 and r.json().get("count", 0) > 0, r.text[:150])

        r = client.get("/api/v1/health-index", headers=AUTH)
        check("health index computed for assets",
              r.status_code == 200 and len(r.json()) >= 5, r.text[:150])

        r = client.get("/api/v1/rul", headers=AUTH)
        check("RUL assessments computed for assets",
              r.status_code == 200 and len(r.json()) >= 5, r.text[:150])

    print(f"\nVERIFY: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    _verify = "--verify" in sys.argv
    _rc = asyncio.run(main(verify=_verify))
    # run_verify drives TestClient on its own event loop, so it must run
    # AFTER the seeding loop has closed (see run_verify docstring).
    if _rc == 0 and _verify:
        _rc = run_verify()
    sys.exit(_rc)
