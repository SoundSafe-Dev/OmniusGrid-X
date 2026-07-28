"""`get_historical_oee` must return recorded data instead of raising.

THE DEFECT. Every column reference in the query was a PYTHON STRING, not a mapped
column:

    func.avg("oee_metrics.availability")      # averages a string literal
    "oee_metrics.asset_id" == asset_id        # a str == uuid, so: False
    "oee_metrics.timestamp" >= start_time     # str >= datetime -> TypeError

The third raised before the statement was ever compiled, so the function had **never
returned a row**. `health_index` calls it inside a broad `except` and logged
`health_index_oee_unavailable` for every asset on every request — which is how this was
found, in the log noise of an unrelated test run. `/api/v1/oee/historical/{asset_id}` has
no such handler and returned a 500.

It could not have worked in any case: **no migration creates an `oee_metrics` table.**
The writer, `_store_oee_metrics`, passed the same string to `insert()` and swallowed the
failure in its own broad `except`, so the reader was querying a table nothing had ever
created and nothing had ever written. Both halves of the feature were inert and each one's
failure was caught and logged rather than surfaced — the reason a permanently broken path
survived in a service `main.py` actually starts.

WHAT IT DOES NOW. Aggregates `packml_states`, which is real, populated, and already the
basis of `/api/v1/dashboard/oee/trend`. That means AVAILABILITY only — performance needs a
per-asset ideal cycle time and quality needs part counters, and neither resolves inside one
GROUP BY — so each row carries `availability_only: true` and reports `None` for the two
factors rather than the 1.0 that would quietly inflate an OEE product.

NOT FIXED, DELIBERATELY: no rollup table is introduced. OEE here is derived from data that
is already persisted, so a metrics table would be a cache. Building one needs a migration,
an ORM model, tenant scoping under RLS and a retention policy — not a string.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

RUN_SECONDS = 1800  # half of an hourly bucket -> availability 0.5


@pytest_asyncio.fixture
async def asset_with_states(admin_sync_url, seeded_orgs):
    """One asset with a recorded Execute period inside the window."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    asset_id, type_id = uuid4(), uuid4()
    entered = datetime.now(timezone.utc) - timedelta(minutes=30)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'test')",
            (str(type_id), f"OEE-{type_id.hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, name, "
            "is_active) VALUES (%s, %s, %s, %s, 'OEE History Asset', true)",
            (
                str(asset_id),
                str(seeded_orgs["org_a_id"]),
                str(seeded_orgs["workcell_a_id"]),
                str(type_id),
            ),
        )
        cur.execute(
            "INSERT INTO packml_states (id, asset_id, state, state_entered_at, "
            "duration_seconds) VALUES (%s, %s, 'Execute', %s, %s)",
            (str(uuid4()), str(asset_id), entered, RUN_SECONDS),
        )
    yield asset_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM packml_states WHERE asset_id = %s", (str(asset_id),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(asset_id),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


async def _history(asset_id, hours: int = 4):
    from app.services.oee_calculator import oee_calculator

    end = datetime.now(timezone.utc)
    return await oee_calculator.get_historical_oee(
        str(asset_id), end - timedelta(hours=hours), end, aggregation="hourly"
    )


class TestItReturnsDataInsteadOfRaising:
    async def test_it_does_not_raise(self, app, asset_with_states):
        """THE ASSERTION THIS FILE EXISTS FOR. Before the fix this raised TypeError
        comparing a str to a datetime, every single call."""
        await _history(asset_with_states)

    async def test_it_finds_the_recorded_run_time(self, app, asset_with_states):
        rows = await _history(asset_with_states)
        assert rows, (
            "no buckets returned for an asset with a recorded Execute period; the query "
            "is not reading packml_states"
        )

    async def test_availability_reflects_the_recorded_duration(self, app, asset_with_states):
        """1800 running seconds in a 3600-second bucket is 0.5. A hardcoded constant
        would satisfy 'it returns rows' and mean nothing."""
        rows = await _history(asset_with_states)
        assert any(abs(r["availability"] - 0.5) < 0.01 for r in rows), (
            f"expected a bucket at ~0.5 availability, got "
            f"{[r['availability'] for r in rows]}"
        )


class TestItDoesNotOverstateWhatItMeasured:
    async def test_each_row_declares_it_is_availability_only(self, app, asset_with_states):
        rows = await _history(asset_with_states)
        assert all(r["availability_only"] is True for r in rows)

    async def test_the_unmeasured_factors_are_none_not_one(self, app, asset_with_states):
        """1.0 is the neutral multiplier for the OEE product and the wrong thing to
        report as a measurement — the same distinction the per-asset OEE panel makes."""
        for row in await _history(asset_with_states):
            assert row["performance"] is None
            assert row["quality"] is None
            assert row["oee"] is None


class TestTheWindowIsHonoured:
    async def test_a_window_before_the_data_returns_nothing(self, app, asset_with_states):
        """Guards the opposite failure: a query ignoring its bounds would return the
        same rows for every window and still pass everything above."""
        from app.services.oee_calculator import oee_calculator

        end = datetime.now(timezone.utc) - timedelta(days=30)
        rows = await oee_calculator.get_historical_oee(
            str(asset_with_states), end - timedelta(hours=4), end
        )
        assert rows == []

    async def test_another_assets_states_are_not_counted(
        self, app, asset_with_states, seeded_orgs
    ):
        """`"oee_metrics.asset_id" == asset_id` evaluated to a plain `False` and filtered
        on nothing. The replacement filters on the real column."""
        rows = await _history(uuid4())
        assert rows == []


class TestTheWriterIsGoneRatherThanPretending:
    """`_store_oee_metrics` was removed, not turned into a no-op.

    Leaving it as a named no-op failed `test_helper_names_match_behaviour.py` — a helper
    called `_store_*` must store — and that guard was right. The call site now carries
    the explanation, which is where someone wondering "why isn't this persisted?" will
    actually look.
    """

    def test_the_claiming_helper_no_longer_exists(self):
        from app.services.oee_calculator import OEECalculator

        assert not hasattr(OEECalculator, "_store_oee_metrics"), (
            "the helper is back; if it persists for real that is fine, but a `_store_*` "
            "that stores nothing is the naming-honesty defect class 5 exists for"
        )

    def test_the_calculation_loop_explains_why_nothing_is_stored(self):
        import inspect

        from app.services.oee_calculator import OEECalculator

        source = inspect.getsource(OEECalculator)
        assert "NOT PERSISTED" in source, (
            "the explanation is gone; the next reader finds a loop that computes OEE and "
            "silently drops it, with nothing saying that is deliberate"
        )

    def test_no_migration_creates_the_table_it_used_to_target(self):
        """Pins the reason not persisting is correct. If someone adds the table, this
        fails and asks for a real write."""
        import pathlib

        migrations = pathlib.Path(__file__).resolve().parents[2] / "database" / "migrations"
        sql = "\n".join(p.read_text().lower() for p in migrations.glob("*.sql"))
        assert "create table" in sql, "no migrations were read; this check is vacuous"
        assert "oee_metrics" not in sql, (
            "an oee_metrics table now exists — the calculation loop should persist to it "
            "instead of dropping the result"
        )
