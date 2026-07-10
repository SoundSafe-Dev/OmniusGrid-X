#!/usr/bin/env python3
"""Deployment-free end-to-end smoke test.

Boots the real FastAPI app in-process against a throwaway SQLite database (no
Docker, no Postgres/Redpanda) and drives the actual HTTP endpoints through every
domain built on this branch:

    health/envelope -> ERP (create/test/mappings/sync/webhook) -> sensor assets
    (taxonomy/telemetry/aggregation/sensor-feeds) -> edge (enroll/heartbeat/fleet)
    -> yard (checkin/assign/detention/checkout) -> transportation (carrier/driver/
    vehicle/shipment lifecycle/aggregates/geofencing/maintenance) -> AI correlation
    (session + platform data sources + correlate)

Auth uses the built-in dev-token bypass. Vendor connectivity is NOT required:
the ERP test/sync flows assert the plumbing records honest failures against the
fake ERP host. Run:  python scripts/smoke_e2e.py   (or `make smoke`)
"""

import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

# --- environment BEFORE importing the app (settings are read at import) -------
_TMP = tempfile.mkdtemp(prefix="omnius-smoke-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/smoke.db"
os.environ["EDGE_BOOTSTRAP_TOKEN"] = "smoke-bootstrap"
os.environ["EDGE_CA_CERT_PATH"] = f"{_TMP}/edge-ca.crt"
os.environ["EDGE_CA_KEY_PATH"] = f"{_TMP}/edge-ca.key"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

AUTH = {"Authorization": "Bearer dev-token"}
DEV_ORG = "00000000-0000-0000-0000-000000000001"

_results = []


def check(name: str, ok: bool, detail: str = ""):
    _results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  — {detail}" if detail and not ok else ""))


def seed_db(fn):
    """Run an async ORM seeding function against the same SQLite file."""
    from app.db.database import AsyncSessionLocal

    async def runner():
        async with AsyncSessionLocal() as session:
            await fn(session)
            await session.commit()

    asyncio.run(runner())


def main() -> int:
    with TestClient(app, raise_server_exceptions=False) as client:
        # ------------------------------------------------ platform basics
        print("\n== Platform basics ==")
        r = client.get("/health", headers=AUTH)
        check("health endpoint", r.status_code == 200, str(r.status_code))

        r = client.get("/api/v1/assets/00000000-0000-0000-0000-00000000dead", headers=AUTH)
        body = r.json()
        check("error envelope on 404", r.status_code == 404 and "error" in body and "detail" in body,
              json.dumps(body)[:120])
        check("X-Request-ID echoed", bool(r.headers.get("X-Request-ID")))

        # Bootstrap the dev user/org via any authed endpoint.
        client.get("/api/v1/erp/integrations", headers=AUTH)

        # ------------------------------------------------ ERP
        print("\n== ERP ==")
        r = client.post("/api/v1/erp/integrations", headers=AUTH, json={
            "integration_name": "Smoke NetSuite",
            "erp_type": "netsuite",
            "auth_type": "token",
            "base_url": "http://127.0.0.1:9",   # unroutable on purpose
            "auth_config": {"token": "t"},
            "webhook_secret": "smoke-hmac",
        })
        check("ERP create", r.status_code == 200, r.text[:200])
        erp_id = r.json().get("id")

        r = client.get("/api/v1/erp/integrations", headers=AUTH)
        check("ERP list", r.status_code == 200 and any(i["id"] == erp_id for i in r.json()))

        r = client.post(f"/api/v1/erp/integrations/{erp_id}/test", headers=AUTH)
        check("ERP /test runs real connector (honest error, no 500)",
              r.status_code == 200 and r.json().get("status") in ("success", "error"), r.text[:200])

        r = client.post(f"/api/v1/erp/integrations/{erp_id}/mappings", headers=AUTH, json={
            "source_entity": "Invoice", "source_field": "tranId",
            "target_entity": "operation", "target_field": "job_id",
            "data_type": "string", "is_required": True,
        })
        check("ERP field mapping create", r.status_code == 200, r.text[:200])

        r = client.post(f"/api/v1/erp/integrations/{erp_id}/sync", headers=AUTH)
        check("ERP sync triggers from mappings", r.status_code == 200
              and "Invoice" in r.json().get("entity_types", []), r.text[:200])

        r = client.get(f"/api/v1/erp/integrations/{erp_id}/sync-status", headers=AUTH)
        statuses = r.json() if r.status_code == 200 else []
        check("ERP sync-status recorded (failed against fake host = plumbing works)",
              any(s["entity_type"] == "Invoice" for s in statuses), r.text[:200])

        # ERP hub surfaces: seed a synced entity, then read entities via the API.
        async def seed_erp_entity(session):
            from app.db.models import ERPEntity
            session.add(ERPEntity(
                organization_id=DEV_ORG, integration_id=erp_id,
                entity_type="PurchaseOrder", entity_id="PO-SMOKE-1",
                entity_data={"vendor": "ACME", "amount": 99.5, "lines": [{"x": 1}]},
                source_system="netsuite",
            ))

        seed_erp_entity_id = erp_id  # noqa: F841
        seed_db(seed_erp_entity)
        r = client.get(f"/api/v1/erp/integrations/{erp_id}/entities", headers=AUTH)
        ents = r.json() if r.status_code == 200 else []
        check("ERP hub entities list", any(e["entity_id"] == "PO-SMOKE-1" for e in ents), r.text[:200])

        event = {"event_type": "invoice.created", "event_id": "evt-1", "entity_type": "Invoice", "amount": 12}
        sig = hmac.new(b"smoke-hmac", json.dumps(event, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        r = client.post("/api/v1/erp/webhooks/netsuite", json=event, headers={"X-Webhook-Signature": sig})
        check("ERP webhook accepted (HMAC verified)", r.status_code == 200
              and r.json().get("status") == "accepted", r.text[:200])
        r = client.post("/api/v1/erp/webhooks/netsuite", json=event, headers={"X-Webhook-Signature": sig})
        check("ERP webhook dedupes replays", r.json().get("status") == "duplicate", r.text[:200])
        r = client.post("/api/v1/erp/webhooks/netsuite", json=event, headers={"X-Webhook-Signature": "bad"})
        check("ERP webhook rejects bad signature", r.status_code == 401, r.text[:200])

        r = client.get(f"/api/v1/erp/integrations/{erp_id}/events", headers=AUTH)
        evs = r.json() if r.status_code == 200 else []
        check("ERP hub events feed shows the webhook", any(e["event_id"] == "evt-1" for e in evs), r.text[:200])

        # ------------------------------------------------ Sensor assets
        print("\n== Sensor assets ==")
        type_id = {"v": None}

        async def seed_type(session):
            from app.db.models import AssetType
            at = AssetType(name="smoke_audio", category="acoustic_monitoring", sensor_class="audio")
            session.add(at)
            await session.flush()
            type_id["v"] = str(at.id)

        seed_db(seed_type)

        r = client.post("/api/v1/assets/", headers=AUTH, json={
            "name": "Smoke Acoustic Monitor", "organization_id": DEV_ORG,
            "asset_type_id": type_id["v"], "sensor_class": "audio",
            "media_config": {"sample_rate": 16000},
        })
        check("asset create with sensor taxonomy", r.status_code == 200, r.text[:300])
        asset_id = r.json().get("id")

        async def seed_telemetry(session):
            from app.db.models import Telemetry
            base = datetime.utcnow()
            for i, v in enumerate([0.21, 0.24, 0.55]):
                session.add(Telemetry(
                    time=base - timedelta(seconds=30 * i), asset_id=str(asset_id),
                    metric_name="audio_rms", value=v, unit="",
                ))

        seed_db(seed_telemetry)

        r = client.get(f"/api/v1/assets/{asset_id}/sensor-feeds", headers=AUTH)
        feeds = r.json() if r.status_code == 200 else {}
        check("sensor-feeds discovery (class + metrics)",
              feeds.get("sensor_class") == "audio" and "audio_rms" in feeds.get("metrics", []),
              r.text[:200])

        r = client.get(f"/api/v1/telemetry/{asset_id}/history", headers=AUTH,
                       params={"aggregation": "1min", "metric_name": "audio_rms"})
        rows = r.json() if r.status_code == 200 else []
        check("telemetry aggregation (was a `pass` stub)",
              isinstance(rows, list) and rows and rows[0].get("aggregation") == "1min"
              and "count" in rows[0], r.text[:200])

        # ------------------------------------------------ Edge security + fleet
        print("\n== Edge enroll / heartbeat / fleet ==")
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        key = ec.generate_private_key(ec.SECP256R1())
        csr = (x509.CertificateSigningRequestBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "smoke-agent-1")]))
               .sign(key, hashes.SHA256()))
        r = client.post("/api/v1/edge/enroll",
                        json={"agent_id": "smoke-agent-1",
                              "csr": csr.public_bytes(serialization.Encoding.PEM).decode()},
                        headers={"Authorization": "Bearer smoke-bootstrap"})
        check("edge enrollment issues certificate", r.status_code == 200
              and "BEGIN CERTIFICATE" in r.json().get("certificate", ""), r.text[:200])
        cert_pem = r.json().get("certificate", "")

        hb_headers = {"X-Client-Cert": cert_pem.replace("\n", "\\n")}
        r = client.post("/api/v1/edge/heartbeat", json={"buffer_pending": 3, "active_collectors": 2,
                                                        "total_collectors": 2},
                        headers=hb_headers)
        check("edge heartbeat (cert-authenticated) + server_time",
              r.status_code == 200 and r.json().get("server_time"), r.text[:200])

        r = client.get("/api/v1/edge/fleet", headers=AUTH)
        fleet = r.json() if r.status_code == 200 else []
        check("edge fleet lists the live agent",
              any(a["agent_id"] == "smoke-agent-1" and a["liveness"] == "online" for a in fleet),
              r.text[:200])

        # ------------------------------------------------ Yard
        print("\n== Yard ==")
        r = client.post("/api/v1/yard/dock/doors", headers=AUTH,
                        json={"organization_id": DEV_ORG, "door_number": "D1", "door_type": "receiving"})
        check("dock door create", r.status_code == 200, r.text[:300])
        door_id = (r.json() or {}).get("id")

        r = client.post("/api/v1/yard/trailers/checkin", headers=AUTH,
                        json={"organization_id": DEV_ORG, "trailer_number": "TRL-SMOKE-1",
                              "trailer_type": "dry_van"})
        check("trailer check-in", r.status_code == 200, r.text[:300])
        trailer_id = (r.json() or {}).get("id")

        if door_id and trailer_id:
            r = client.post(f"/api/v1/yard/dock/doors/{door_id}/assign/{trailer_id}", headers=AUTH)
            check("assign trailer to door", r.status_code == 200, r.text[:300])

        async def backdate(session):
            from sqlalchemy import update
            from app.db.models import YardTrailer
            await session.execute(update(YardTrailer).where(YardTrailer.id == str(trailer_id))
                                  .values(check_in_at=datetime.utcnow() - timedelta(hours=4)))

        if trailer_id:
            seed_db(backdate)
        r = client.get("/api/v1/yard/detention-alerts", headers=AUTH)
        alerts = r.json() if r.status_code == 200 else []
        check("live detention alert accrues charges",
              any(a["trailer_number"] == "TRL-SMOKE-1" and a["status"] == "detention"
                  and a["current_charge"] > 0 for a in alerts), r.text[:300])

        if trailer_id:
            r = client.post(f"/api/v1/yard/trailers/{trailer_id}/checkout", headers=AUTH)
            check("trailer check-out", r.status_code == 200, r.text[:300])

        # ------------------------------------------------ Transportation
        print("\n== Transportation ==")
        r = client.post("/api/v1/transportation/carriers", headers=AUTH,
                        json={"organization_id": DEV_ORG, "carrier_name": "Smoke Freight",
                              "ctpat_certified": True})
        check("carrier create", r.status_code == 200, r.text[:300])
        carrier_id = (r.json() or {}).get("id")

        r = client.post("/api/v1/transportation/drivers", headers=AUTH,
                        json={"organization_id": DEV_ORG, "carrier_id": carrier_id,
                              "first_name": "Sam", "last_name": "Smoke"})
        check("driver create", r.status_code == 200, r.text[:300])
        driver_id = (r.json() or {}).get("id")

        r = client.post("/api/v1/transportation/vehicles", headers=AUTH,
                        json={"organization_id": DEV_ORG, "carrier_id": carrier_id,
                              "vehicle_number": "TRK-SMOKE-9"})
        check("vehicle create (new D20 endpoint)", r.status_code == 200, r.text[:300])
        r = client.get("/api/v1/transportation/vehicles", headers=AUTH)
        check("vehicle list", r.status_code == 200
              and any(v["vehicleNumber"] == "TRK-SMOKE-9" for v in r.json()), r.text[:200])

        r = client.post("/api/v1/transportation/shipments", headers=AUTH,
                        json={"organization_id": DEV_ORG, "carrier_id": carrier_id,
                              "shipment_number": "SHP-SMOKE-1", "origin": {"city": "Chicago"},
                              "destination": {"city": "Dallas"},
                              "scheduled_delivery": (datetime.utcnow() + timedelta(days=1)).isoformat()})
        check("shipment create", r.status_code == 200, r.text[:300])
        shipment_id = (r.json() or {}).get("id")

        if shipment_id:
            # Dispatch requires a driver AND a trailer (query params).
            r = client.post("/api/v1/yard/trailers/checkin", headers=AUTH,
                            json={"organization_id": DEV_ORG, "trailer_number": "TRL-SMOKE-2",
                                  "trailer_type": "dry_van"})
            dispatch_trailer = (r.json() or {}).get("id")
            r = client.post(f"/api/v1/transportation/shipments/{shipment_id}/dispatch",
                            headers=AUTH,
                            params={"driver_id": driver_id, "trailer_id": dispatch_trailer})
            check("shipment dispatch", r.status_code == 200, r.text[:300])

            r = client.post(f"/api/v1/transportation/shipments/{shipment_id}/status",
                            headers=AUTH, params={"status": "delivered"})
            check("shipment delivered", r.status_code == 200, r.text[:300])

        r = client.get("/api/v1/logistics/delivery-efficiency", headers=AUTH)
        check("delivery-efficiency aggregate", r.status_code == 200
              and r.json().get("totalDelivered", 0) >= 1, r.text[:200])

        r = client.get("/api/v1/logistics/compliance/summary", headers=AUTH)
        check("compliance summary", r.status_code == 200
              and r.json().get("totalCarriers", 0) >= 1, r.text[:200])

        r = client.post("/api/v1/geofencing/zones", headers=AUTH,
                        json={"name": "Smoke Plant Perimeter",
                              "center": {"lat": 41.8, "lng": -87.6}, "radiusMeters": 500})
        check("geofence zone create", r.status_code == 200, r.text[:300])
        r = client.get("/api/v1/geofencing/zones", headers=AUTH)
        check("geofence zone list", r.status_code == 200 and len(r.json()) >= 1)

        r = client.post("/api/v1/maintenance/schedules", headers=AUTH,
                        json={"vehicleId": "TRK-SMOKE-9", "maintenanceType": "oil_change",
                              "dueDate": (datetime.utcnow() - timedelta(days=1)).isoformat()})
        check("maintenance schedule create", r.status_code == 200, r.text[:300])
        r = client.get("/api/v1/maintenance/statistics", headers=AUTH)
        check("maintenance statistics (overdue derived)", r.status_code == 200
              and r.json().get("overdueCount", 0) >= 1, r.text[:200])

        # ------------------------------------------------ AI correlation wiring
        print("\n== AI correlation (platform data sources) ==")
        r = client.get("/api/v1/nlp/platform-sources", headers=AUTH)
        types = {s["source_type"] for s in r.json()} if r.status_code == 200 else set()
        check("platform source types registered (incl. erp)",
              {"asset_telemetry", "yard", "transportation", "erp"} <= types, r.text[:200])

        r = client.post("/api/v1/nlp/sessions", headers=AUTH, json={"title": "Smoke session"})
        if r.status_code == 404:
            r = client.post("/api/v1/nlp/sessions/", headers=AUTH, json={"title": "Smoke session"})
        check("analysis session create", r.status_code == 200, r.text[:300])
        session_id = (r.json() or {}).get("id")

        if session_id:
            r = client.post(f"/api/v1/nlp/sessions/{session_id}/platform-data", headers=AUTH,
                            json={"source_type": "asset_telemetry", "params": {"asset_id": asset_id}})
            check("attach sensor telemetry to session", r.status_code == 200
                  and r.json().get("row_count", 0) >= 1, r.text[:300])

            r = client.post(f"/api/v1/nlp/sessions/{session_id}/platform-data", headers=AUTH,
                            json={"source_type": "transportation", "params": {}})
            check("attach shipments to session", r.status_code == 200
                  and r.json().get("row_count", 0) >= 1, r.text[:300])

            r = client.post(f"/api/v1/nlp/sessions/{session_id}/platform-data", headers=AUTH,
                            json={"source_type": "erp", "params": {"entity_type": "PurchaseOrder"}})
            check("attach ERP entities to session", r.status_code == 200
                  and r.json().get("row_count", 0) >= 1, r.text[:300])

            r = client.post(f"/api/v1/nlp/sessions/{session_id}/correlate", headers=AUTH, json={})
            check("correlate session over platform data", r.status_code == 200
                  and "analysis" in r.json(), r.text[:300])

    failed = [(n, d) for n, ok, d in _results if not ok]
    print(f"\n{'='*60}\nSMOKE: {len(_results) - len(failed)}/{len(_results)} passed")
    for n, d in failed:
        print(f"  FAILED: {n}  {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
