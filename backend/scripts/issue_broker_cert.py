#!/usr/bin/env python
"""Issue a Redpanda broker TLS certificate from the edge CA (FS-65).

Emits cert + key PEM signed by the same CA every enrolled agent trusts, so
agents flipping to KAFKA_SECURITY_PROTOCOL=SSL validate the broker with the
CA bundle they already hold from enrollment.

Usage (from backend/):
    python scripts/issue_broker_cert.py \\
        --cn redpanda \\
        --dns redpanda --dns redpanda.omniusgrid.svc.cluster.local \\
        --out-dir ../infra/redpanda/tls

Writes broker.crt, broker.key (0600) and ca.crt into --out-dir. Mount them
where docker-compose.prod.yml / the redpanda statefulset expect
(/etc/redpanda/tls). Uses the SAME CA material paths as the API
(EDGE_CA_CERT_PATH/EDGE_CA_KEY_PATH), so run it wherever the CA lives.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Issue a broker TLS cert from the edge CA.")
    ap.add_argument("--cn", default="redpanda", help="certificate common name")
    ap.add_argument(
        "--dns",
        action="append",
        default=None,
        help="SAN DNS name (repeatable). Default: redpanda, localhost",
    )
    ap.add_argument("--ttl-days", type=int, default=365)
    ap.add_argument("--out-dir", default="broker-tls", help="output directory")
    args = ap.parse_args()

    from app.services.edge_ca import edge_ca

    dns_names = args.dns or ["redpanda", "localhost"]
    cert_pem, key_pem = edge_ca.issue_server_cert(args.cn, dns_names, ttl_days=args.ttl_days)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "broker.crt").write_bytes(cert_pem)
    key_path = out / "broker.key"
    key_path.write_bytes(key_pem)
    os.chmod(key_path, 0o600)
    (out / "ca.crt").write_bytes(edge_ca.ca_certificate_pem())

    print(f"wrote {out}/broker.crt, broker.key (0600), ca.crt")
    print(f"SANs: {', '.join(dns_names)}; TTL {args.ttl_days}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
