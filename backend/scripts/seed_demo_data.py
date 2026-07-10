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
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get("DATABASE_URL"):
    default_db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dev.db")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{default_db}"

NOW = datetime.utcnow()
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

CARRIER_A = "55555555-0000-4000-8000-000000000001"  # Great Lakes Freight
CARRIER_B = "55555555-0000-4000-8000-000000000002"  # Prairie Express
DRIVER_1 = "66666666-0000-4000-8000-000000000001"
DRIVER_2 = "66666666-0000-4000-8000-000000000002"
DRIVER_3 = "66666666-0000-4000-8000-000000000003"

SESSION_ID = "77777777-0000-4000-8000-000000000001"

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
    from app.db.database import AsyncSessionLocal, init_db
    from app.db.models import (
        Alarm, AnalysisSession, Asset, AssetType, Carrier, DockAppointment,
        DockDoor, Driver, DriverWaitTime, ERPCorrelation, ERPDataMapping,
        ERPEntity, ERPIntegrationEvent, ERPSyncStatus, IntegrationConfiguration,
        Organization, SessionDataSource, Shipment, Telemetry, User, Workcell,
        YardTrailer,
    )
    from app.db.logistics_models import (
        GeofenceAlert, GeofenceZone, MaintenanceSchedule, RepairOrder, Vehicle,
    )

    await init_db()
    print(f"Seeding demo data into {os.environ['DATABASE_URL']}")

    async with AsyncSessionLocal() as db:
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
        db.add(Alarm(asset_id=A_VIB, alarm_code="VIB_HIGH", severity="high",
                     message="Spindle vibration exceeded ISO zone C (7.1 mm/s)",
                     occurred_at=days_ago(ALARM_D), cleared_at=days_ago(FIXED_D),
                     is_active=False, is_acknowledged=True, acknowledged_by=USER,
                     acknowledged_at=days_ago(1.9)))
        db.add(Alarm(asset_id=A_AUDIO, alarm_code="ACOUSTIC_ANOMALY", severity="medium",
                     message="High-frequency band energy trending up (bearing-wear signature)",
                     occurred_at=days_ago(3.5), is_active=False, is_acknowledged=True,
                     acknowledged_by=USER, acknowledged_at=days_ago(3.4)))

        # ---- SIMULATED FULLY-SYNCED ERP INTEGRATION ---------------------------
        db.add(IntegrationConfiguration(
            id=ERP_INT, organization_id=ORG, integration_type="erp",
            integration_name="SAP S/4HANA — Plant CHI-01",
            configuration={"erp_type": "sap", "auth_type": "oauth2",
                           "base_url": "https://sap.demo.omniusgrid.local",
                           "auth_config": {"client_id": "omnius-demo"},
                           "rate_limit": {"requests_per_minute": 60, "burst_limit": 10},
                           "timeout": 30, "webhook_secret": "demo-secret",
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
        db.add(ERPCorrelation(organization_id=ORG, correlation_type="work_order_vibration",
                              erp_event_id=wo_event.id, sensor_event_id=f"{A_VIB}:vibration_rms",
                              correlation_score=0.87,
                              correlation_metadata={"window_days": 7, "asset": "CNC Mill #1"}))
        db.add(ERPCorrelation(organization_id=ORG, correlation_type="po_dock_arrival",
                              sensor_event_id=f"{A_CAMERA}:motion_score", correlation_score=0.74,
                              correlation_metadata={"po_number": "PO-10018", "door": "D3"}))

        # ---- yard (correlated to POs + camera) ---------------------------------
        for i, door_id in enumerate(DOOR_IDS, start=1):
            db.add(DockDoor(id=door_id, organization_id=ORG, door_number=f"D{i}",
                            door_type="receiving" if i <= 5 else "shipping",
                            status="occupied" if i == 3 else "available",
                            current_trailer_id=TRAILER_DOCKED if i == 3 else None))
        db.add(Carrier(id=CARRIER_A, organization_id=ORG, carrier_name="Great Lakes Freight",
                       dot_number="DOT-448821", mc_number="MC-99120", ctpat_certified=True,
                       insurance_on_file=True, insurance_expires_at=NOW + timedelta(days=21),
                       safety_rating="satisfactory", csa_score=41.5, is_active=True))
        db.add(Carrier(id=CARRIER_B, organization_id=ORG, carrier_name="Prairie Express",
                       dot_number="DOT-102934", mc_number="MC-55431", ctpat_certified=False,
                       insurance_on_file=True, insurance_expires_at=NOW + timedelta(days=180),
                       safety_rating="conditional", csa_score=68.0, is_active=True))

        db.add(YardTrailer(id=TRAILER_DWELL, organization_id=ORG, trailer_number="TRL-4482",
                           carrier_id=CARRIER_A, trailer_type="dry_van", status="yard",
                           yard_location="Zone A-04", seal_number="SL-88121",
                           check_in_at=NOW - timedelta(hours=6),  # 4h past free time -> detention
                           meta_data={"po_number": "PO-10018", "contents": "6061 aluminum billet"}))
        db.add(YardTrailer(id=TRAILER_DOCKED, organization_id=ORG, trailer_number="TRL-7731",
                           carrier_id=CARRIER_A, trailer_type="reefer", status="docked",
                           dock_door_id=DOOR_IDS[2], seal_number="SL-88907",
                           check_in_at=NOW - timedelta(hours=1.2),
                           meta_data={"po_number": "PO-10021", "contents": "Spindle bearing kit"}))
        db.add(YardTrailer(id=TRAILER_YARD, organization_id=ORG, trailer_number="TRL-9017",
                           carrier_id=CARRIER_B, trailer_type="dry_van", status="yard",
                           yard_location="Zone B-02", check_in_at=NOW - timedelta(hours=0.8),
                           meta_data={"po_number": "PO-10019", "contents": "ABS pellets"}))
        for tid, num, d_in, d_out in [(TRAILER_OUT1, "TRL-3306", 3.4, 3.1),
                                      (TRAILER_OUT2, "TRL-5540", 1.6, 1.35)]:
            db.add(YardTrailer(id=tid, organization_id=ORG, trailer_number=num,
                               carrier_id=CARRIER_B, trailer_type="dry_van", status="checked_out",
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
        db.add(Driver(id=DRIVER_1, organization_id=ORG, carrier_id=CARRIER_A, first_name="Maria",
                      last_name="Santos", license_number="IL-D449-2210", license_state="IL",
                      cdl_class="A", hos_drive_hours_today=10.6, hos_on_duty_hours_today=12.9,
                      hos_cycle_hours=61.0, current_hos_status="driving", is_active=True))
        db.add(Driver(id=DRIVER_2, organization_id=ORG, carrier_id=CARRIER_A, first_name="Dwayne",
                      last_name="Carter", license_number="IL-D101-8837", license_state="IL",
                      cdl_class="A", hos_drive_hours_today=3.2, hos_on_duty_hours_today=5.0,
                      hos_cycle_hours=28.5, current_hos_status="on_duty", is_active=True))
        db.add(Driver(id=DRIVER_3, organization_id=ORG, carrier_id=CARRIER_B, first_name="Priya",
                      last_name="Natarajan", license_number="WI-D778-1204", license_state="WI",
                      cdl_class="A", hos_drive_hours_today=0.0, hos_on_duty_hours_today=1.5,
                      hos_cycle_hours=44.0, current_hos_status="off_duty", is_active=True,
                      medical_cert_expires=NOW + timedelta(days=18)))
        vehicles = [("TRK-081", 0.62, 214880, "gt-device-001", "moving"),
                    ("TRK-114", 0.35, 158211, "gt-device-002", "idle"),
                    ("TRK-207", 0.88, 88109, "gt-device-003", "idle")]
        for num, fuel, odo, gt, status in vehicles:
            db.add(Vehicle(organization_id=ORG, carrier_id=CARRIER_A, vehicle_number=num,
                           make="Freightliner", model="Cascadia", year=2023, status=status,
                           fuel_level_percent=fuel * 100, odometer_miles=odo, geotab_device_id=gt,
                           last_location={"latitude": 41.87 + RNG.uniform(-0.4, 0.4),
                                          "longitude": -87.62 + RNG.uniform(-0.5, 0.5),
                                          "speed": 58 if status == "moving" else 0}))
        ships = [
            ("SHP-2201", "delivered", 3.0, 2.2, 2.4, DRIVER_1),   # on time
            ("SHP-2202", "delivered", 5.0, 4.1, 3.9, DRIVER_2),   # late
            ("SHP-2203", "delivered", 7.2, 6.5, 6.6, DRIVER_2),   # on time
            ("SHP-2204", "in_transit", 0.4, None, -0.6, DRIVER_1),
            ("SHP-2205", "planned", None, None, -2.0, None),
        ]
        for num, status, picked_d, delivered_d, sched_d, drv in ships:
            db.add(Shipment(organization_id=ORG, carrier_id=CARRIER_A, driver_id=drv,
                            shipment_number=num, shipment_type="outbound", status=status,
                            origin={"city": "Chicago", "state": "IL"},
                            destination={"city": "Dallas", "state": "TX"},
                            actual_pickup=days_ago(picked_d) if picked_d else None,
                            scheduled_delivery=days_ago(sched_d) if sched_d is not None else None,
                            actual_delivery=days_ago(delivered_d) if delivered_d else None,
                            priority="normal", total_weight_lbs=32000, total_pieces=18))
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
            db.add(SessionDataSource(session_id=SESSION_ID, source_type=source_type,
                                     source_id=str(params.get("asset_id") or params.get("integration_id") or source_type),
                                     file_name=result.file_name, data_type="spreadsheet",
                                     processed_data=result.to_processed_data(),
                                     meta_data={"platform_source": True, "source_type": source_type}))
        await db.commit()

        # ---- summary -----------------------------------------------------------
        from sqlalchemy import func
        counts = {}
        for label, model in [("telemetry", Telemetry), ("erp_entities", ERPEntity),
                             ("erp_events", ERPIntegrationEvent), ("trailers", YardTrailer),
                             ("shipments", Shipment), ("vehicles", Vehicle)]:
            counts[label] = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        print("  seeded:", ", ".join(f"{k}={v}" for k, v in counts.items()))
        print(f"  analysis session ready: 'Demo: Spindle failure investigation' ({SESSION_ID})")

    if verify:
        return await run_verify()
    print("\nDone. Run the API against this data:")
    print(f"  DATABASE_URL='{os.environ['DATABASE_URL']}' uvicorn app.main:app --port 8000")
    print("  (frontend: VITE_USE_MOCK=false npm run dev)")
    return 0


async def run_verify() -> int:
    """Hit the seeded data through the real API (in-process, no deployment)."""
    from fastapi.testclient import TestClient
    from app.main import app

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
        rows = r.json() if r.status_code == 200 else []
        peak = max((x["max"] for x in rows), default=0)
        check("vibration degradation arc visible (peak > 7 mm/s)", peak > 7, f"peak={peak}")

        r = client.get(f"/api/v1/assets/{A_AUDIO}/sensor-feeds", headers=AUTH)
        check("audio sensor feeds discoverable", r.status_code == 200 and
              "audio_band_high" in r.json().get("metrics", []), r.text[:150])

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

    print(f"\nVERIFY: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(verify="--verify" in sys.argv)))
