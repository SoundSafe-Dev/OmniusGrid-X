"""Migration 045 must repair NULL timestamps with DERIVED values (FS-202).

044 stopped new raw inserts writing NULL. 045 repairs rows already written that
way. The interesting assertion is not "it's no longer NULL" — it's that the
value came from the row's OWN event timestamp rather than being stamped with the
time the migration happened to run. A blind NOW() backfill would pass a
not-null check while silently rewriting history.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database" / "migrations" / "045_backfill_null_timestamps.sql"
)


def _run_045(conn):
    """Re-apply 045 (it is idempotent: every statement is WHERE ... IS NULL)."""
    with conn.cursor() as cur:
        cur.execute(MIGRATION.read_text())


@pytest.fixture
def conn(admin_sync_url):
    c = psycopg2.connect(admin_sync_url)
    c.autocommit = True
    yield c
    c.close()


def test_backfill_uses_the_rows_own_event_time_not_now(conn, seeded_orgs):
    """A trailer with a known check-in must get THAT time, not migration time."""
    trailer_id = uuid4()
    check_in = datetime(2025, 3, 14, 9, 30, tzinfo=timezone.utc)

    with conn.cursor() as cur:
        # Force the pre-044 state for this row: an explicit NULL created_at.
        cur.execute(
            "INSERT INTO yard_trailers (id, organization_id, trailer_number,"
            " check_in_at, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, NULL, NULL)",
            (str(trailer_id), str(seeded_orgs["org_a_id"]), f"T-{uuid4().hex[:6]}", check_in),
        )

    _run_045(conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT created_at, updated_at FROM yard_trailers WHERE id = %s",
            (str(trailer_id),),
        )
        created_at, updated_at = cur.fetchone()

    assert created_at is not None, "045 left created_at NULL"
    # The whole point: derived from check_in_at, not the migration's run time.
    assert created_at == check_in, (
        f"created_at was stamped {created_at} instead of the row's own "
        f"check-in {check_in} — that rewrites history"
    )
    assert updated_at == created_at, "updated_at should follow the repaired created_at"


def test_backfill_falls_back_when_the_row_has_no_event_time(conn, seeded_orgs):
    """carriers carry only FUTURE expiry dates, so there is nothing to derive from.

    The fallback must still produce a usable timestamp — and must not be in the
    future, which is what using an expiry column would have done.
    """
    carrier_id = uuid4()
    future_expiry = datetime.now(timezone.utc) + timedelta(days=365)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO carriers (id, organization_id, carrier_name, insurance_expires_at,"
            " created_at, updated_at) VALUES (%s, %s, %s, %s, NULL, NULL)",
            (str(carrier_id), str(seeded_orgs["org_a_id"]), f"C-{uuid4().hex[:6]}",
             future_expiry),
        )

    _run_045(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT created_at FROM carriers WHERE id = %s", (str(carrier_id),))
        (created_at,) = cur.fetchone()

    assert created_at is not None
    assert created_at <= datetime.now(timezone.utc) + timedelta(minutes=1), (
        f"created_at {created_at} is in the FUTURE — the fallback picked up an "
        "expiry date instead of a creation time"
    )


def test_backfill_is_idempotent_and_does_not_touch_good_rows(conn, seeded_orgs):
    """Re-running must be a no-op; an existing correct timestamp must survive."""
    trailer_id = uuid4()
    known = datetime(2024, 1, 2, 3, 4, tzinfo=timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO yard_trailers (id, organization_id, trailer_number,"
            " check_in_at, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (str(trailer_id), str(seeded_orgs["org_a_id"]), f"T-{uuid4().hex[:6]}",
             datetime(2025, 6, 1, tzinfo=timezone.utc), known, known),
        )

    _run_045(conn)
    _run_045(conn)  # twice: idempotency

    with conn.cursor() as cur:
        cur.execute(
            "SELECT created_at FROM yard_trailers WHERE id = %s", (str(trailer_id),)
        )
        (created_at,) = cur.fetchone()

    assert created_at == known, (
        "045 overwrote a row that already had a good created_at — it must only "
        "touch NULLs"
    )


def test_no_null_timestamps_remain_after_the_chain(conn):
    """After the full migration chain, nothing should be left NULL."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema='public'
              AND column_name IN ('created_at','updated_at')
            """
        )
        targets = cur.fetchall()

        offenders = []
        for table, column in targets:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
            n = cur.fetchone()[0]
            if n:
                offenders.append(f"{table}.{column} ({n} rows)")

    assert not offenders, (
        "NULL timestamps remain after migration 045 — these rows are invisible "
        "to time-ordered queries: " + ", ".join(offenders)
    )
