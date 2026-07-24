#!/usr/bin/env python3
"""Kafka/Redpanda ingestion load generator.

Ingestion is NOT an HTTP path — edge agents produce telemetry to Redpanda and the
ingestion worker (consumer group ``opsgrid-ingestion-workers``) drains it into
TimescaleDB. So a k6 HTTP test can't exercise it. This floods the ingestion
topics directly, which is what actually drives:

  * the KEDA ScaledObject on the ingestion worker (it scales on consumer-group
    LAG — see infrastructure/k8s/autoscaling/) — watch the worker scale 2 -> 12;
  * the TimescaleDB write path under sustained insert pressure.

Messages match the worker's contract exactly:
  topic:  telemetry.{org_id}.{asset_id}     (both must be UUIDs)
  value:  {"timestamp": <iso8601>, "payload": {"telemetry": {<metric>: <value>}}}

For LAG/scaling validation, random asset UUIDs are fine — the messages are
consumed either way and drive lag. For DB-WRITE validation, pass real seeded
org/asset IDs (--org-id / --asset-ids) so rows actually land instead of being
dead-lettered on a missing FK.

Usage:
  python ingestion_load.py --rate 2000 --duration 120 \
      --broker localhost:9092 --org-id <uuid> --assets 50

  # Burst harder than the workers can drain to force scale-up, then watch:
  #   kubectl -n omniusgrid get hpa keda-hpa-ingestion-worker -w
  #   (or the Grafana "Platform / Infra" dashboard: worker replicas current-vs-max)

Requires: aiokafka (already a backend dependency).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
import uuid
from datetime import datetime, timezone

try:
    from aiokafka import AIOKafkaProducer
except ImportError:  # pragma: no cover
    raise SystemExit("aiokafka not installed — run inside the backend venv (pip install aiokafka)")

METRICS = [
    "temperature_c", "vibration_mm_s", "pressure_kpa", "speed_rpm",
    "current_a", "voltage_v", "oee_pct", "throughput_units_min",
]


def build_message() -> dict:
    """One realistic telemetry sample: a spread of numeric metrics."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "telemetry": {m: round(random.uniform(0, 100), 3) for m in METRICS}
        },
    }


async def run(args: argparse.Namespace) -> None:
    org_id = args.org_id or str(uuid.uuid4())
    if args.asset_ids:
        assets = [a.strip() for a in args.asset_ids.split(",") if a.strip()]
    else:
        assets = [str(uuid.uuid4()) for _ in range(args.assets)]

    producer = AIOKafkaProducer(
        bootstrap_servers=args.broker,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        linger_ms=5,
        acks=1,
    )
    await producer.start()
    print(
        f"producing ~{args.rate} msg/s for {args.duration}s to {args.broker} "
        f"| org={org_id} | {len(assets)} assets"
    )

    sent = 0
    errors = 0
    interval = 1.0 / args.rate if args.rate > 0 else 0
    start = time.monotonic()
    deadline = start + args.duration
    next_report = start + 5
    # Fire-and-forget within a bounded window so we approximate the target rate
    # without blocking on every ack (which would cap throughput at the RTT).
    try:
        while time.monotonic() < deadline:
            asset = random.choice(assets)
            topic = f"telemetry.{org_id}.{asset}"
            try:
                # send() returns a future; we don't await the ack per-message.
                await producer.send(topic, build_message())
                sent += 1
            except Exception:  # noqa: BLE001
                errors += 1
            if interval:
                await asyncio.sleep(interval)
            now = time.monotonic()
            if now >= next_report:
                elapsed = max(now - start, 1e-6)
                print(f"  sent={sent} errors={errors} rate~{sent / elapsed:.0f}/s")
                next_report = now + 5
    finally:
        await producer.flush()
        await producer.stop()
    print(f"done: sent={sent} errors={errors}")


def main() -> None:
    p = argparse.ArgumentParser(description="Redpanda ingestion load generator")
    p.add_argument("--broker", default="localhost:9092", help="Kafka/Redpanda bootstrap servers")
    p.add_argument("--rate", type=int, default=1000, help="target messages/second")
    p.add_argument("--duration", type=int, default=60, help="seconds to run")
    p.add_argument("--org-id", default=None, help="tenant org UUID (random if omitted)")
    p.add_argument("--asset-ids", default=None, help="comma-separated real asset UUIDs (for DB-write validation)")
    p.add_argument("--assets", type=int, default=25, help="number of random asset UUIDs when --asset-ids is not given")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
