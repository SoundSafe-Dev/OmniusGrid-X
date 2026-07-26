#!/usr/bin/env python3
"""Provision the local Odoo sandbox for connector validation (Tier 3).

Waits for Odoo to answer, then creates a database WITH DEMO DATA. The demo data is
the point: an empty Odoo would let every fetch test pass by returning nothing,
which is precisely the silent-empty-result failure these tests exist to catch.

Idempotent — if the database already exists it is left alone, so re-running between
test runs is free.

    docker compose -f docker-compose.erp-sandbox.yml up -d
    python backend/scripts/setup_odoo_sandbox.py
    RUN_ODOO_INTEGRATION=1 pytest backend/tests/test_erp_odoo_integration.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

ODOO_URL = os.environ.get("ODOO_URL", "http://localhost:8169")
ODOO_DB = os.environ.get("ODOO_DB", "omniusgrid_test")
ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD", "admin")
# Odoo's master password. Set by the image's default configuration; overridable so
# a hardened sandbox can differ.
MASTER_PASSWORD = os.environ.get("ODOO_MASTER_PASSWORD", "admin")

READY_TIMEOUT = int(os.environ.get("ODOO_READY_TIMEOUT", "180"))
# Creating a database with demo data installs the base modules; on a cold container
# this genuinely takes over a minute.
CREATE_TIMEOUT = int(os.environ.get("ODOO_CREATE_TIMEOUT", "600"))


def rpc(service: str, method: str, args: list, timeout: int) -> dict:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": 1,
        }
    ).encode()
    request = urllib.request.Request(
        f"{ODOO_URL}/jsonrpc", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def wait_for_odoo() -> None:
    deadline = time.time() + READY_TIMEOUT
    last_error = None
    while time.time() < deadline:
        try:
            result = rpc("common", "version", [], timeout=10)
            version = result.get("result", {}).get("server_version", "?")
            print(f"odoo is up: {version}", flush=True)
            return
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(3)
    sys.exit(f"odoo did not become reachable at {ODOO_URL} within {READY_TIMEOUT}s: {last_error}")


def main() -> int:
    wait_for_odoo()

    existing = rpc("db", "list", [], timeout=30).get("result", [])
    if ODOO_DB in existing:
        print(f"database {ODOO_DB!r} already exists — nothing to do")
        return 0

    print(f"creating {ODOO_DB!r} with demo data (this takes a minute)...", flush=True)
    result = rpc(
        "db",
        "create_database",
        # (master_pwd, db_name, demo, lang, admin_password)
        [MASTER_PASSWORD, ODOO_DB, True, "en_US", ODOO_PASSWORD],
        timeout=CREATE_TIMEOUT,
    )

    if "error" in result:
        message = result["error"].get("data", {}).get("message") or result["error"]
        sys.exit(f"database creation failed: {message}")

    print(f"created {ODOO_DB!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
