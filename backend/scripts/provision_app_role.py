#!/usr/bin/env python3
"""Create the non-superuser role the application would have in production (FS-307).

WHY A GATE THAT PASSES CAN MEAN NOTHING. The schemathesis contract job connected as the
postgres service container's `POSTGRES_USER`, and in the official image that role is a
**superuser**. A superuser bypasses `FORCE ROW LEVEL SECURITY` — every policy in the schema is
simply not applied to its sessions. So the gate exercised ~375 operations against a database
where tenant isolation was switched off, and its conformance number could not have moved if
every RLS policy in the schema had been dropped.

That is worse than an untested contract. A red gate is a task; a green gate that cannot fail
in a whole dimension is a *belief*, and this one was cited in the burn-down as evidence.

`backend/tests/conftest.py` has done the right thing since the RLS work: create a role that is
`NOSUPERUSER NOBYPASSRLS` and does **not own the tables**, because ownership is the other way
to bypass a FORCE policy. This script is that logic, lifted so CI and the fixture cannot
disagree — a second copy of a security-relevant grant list is a second thing to forget.

WHAT IT DELIBERATELY DOES NOT DO. It grants no DDL. Migrations run as the owner before this is
called, exactly as they do in production, where the application role has never needed to
create a table. If the contract suite starts failing operations after this lands, that is the
gate finding something rather than the script being wrong: the app is reaching for a privilege
it would not have in production.
"""

from __future__ import annotations

import argparse
import sys

#: Everything the application role is given. Nothing here is DDL, and nothing makes it an
#: owner — either would silently restore the bypass this script exists to remove.
GRANTS = (
    "GRANT USAGE ON SCHEMA public TO {role};",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role};",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role};",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role};",
)

CREATE = (
    "DO $$ BEGIN "
    "  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
    "    CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS; "
    "  END IF; "
    "END $$;"
)


def provision(sync_url: str, role: str, password: str) -> None:
    """Create ``role`` if absent and grant it the application's privileges."""
    import psycopg2

    conn = psycopg2.connect(sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE.format(role=role, password=password))
            for grant in GRANTS:
                cur.execute(grant.format(role=role))
            # Assert rather than assume. A role that is somehow a superuser, or has
            # BYPASSRLS, makes every isolation result downstream meaningless — and it would
            # do so silently, which is the whole failure being fixed here.
            cur.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", (role,)
            )
            row = cur.fetchone()
            if row is None:
                raise SystemExit(f"{role} was not created")
            is_super, bypasses = row
            if is_super or bypasses:
                raise SystemExit(
                    f"{role} has rolsuper={is_super} rolbypassrls={bypasses}; RLS would not "
                    f"apply to it and any isolation result from this run would be a fiction"
                )
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="sync postgres URL of an owner/superuser")
    parser.add_argument("--role", default="omniusgrid_contract")
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    provision(args.url, args.role, args.password)
    print(f"provisioned {args.role}: NOSUPERUSER NOBYPASSRLS, no table ownership, no DDL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
