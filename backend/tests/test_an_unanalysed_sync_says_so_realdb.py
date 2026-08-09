"""A sync that was never correlated says so, all the way to the screen (FS-562).

`correlate_synced_records` distinguishes *"analysed, nothing anomalous"* from *"no analyzer is
registered for this vendor's field names, so nothing was looked at"*. It has since FS-557: the
outcome carries `routed` and a `reason`, and the log line spells out why reusing another
vendor's transformer would produce "empty normalized records and a confident report of zero
anomalies".

**And the answer died at the end of the request.** It was returned by `POST /sync` and nowhere
else, while the page an operator watches polls `GET /sync-status` — built from a table with
nowhere to put it. So the correlations tab rendered an empty list for both cases, which is a
**verdict computed from emptiness** one layer further back than the class usually appears: not
a failed read shown as no results, but an analysis that never ran shown as an analysis that
found nothing.

WHY THE COLUMN IS NULLABLE AND NOT `DEFAULT false`. Three states. A row written before this
existed recorded no correlation attempt either way, and stamping `false` on it would invent a
skip that may never have happened — the frontend reads null as "not recorded" and renders
nothing, which is the honest thing to render about a sync nobody measured.

THE FOUR BOUNDARIES, each of which silently drops a field, and this pins all four: the service
returns it, the route persists it, the response model declares it (FastAPI OMITS an undeclared
field rather than erroring — FS-591), and the column exists to hold it.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.api.erp_integrations import SyncStatusResponse
from app.db.models import ERPSyncStatus


class TestTheColumnExists:
    """Boundary four. The ORM attribute existing proves nothing about the table — that is
    exactly the drift `test_schema_parity` was written for, and a missing column here
    surfaces as a 500 on the sync route rather than as a missing field."""

    @pytest.mark.parametrize("column", ["correlation_routed", "correlation_reason"])
    def test_the_model_declares_it(self, column: str):
        assert column in ERPSyncStatus.__table__.columns

    @pytest.mark.parametrize("column", ["correlation_routed", "correlation_reason"])
    def test_it_is_nullable(self, column: str):
        assert ERPSyncStatus.__table__.columns[column].nullable, (
            f"{column} is NOT NULL, so a sync that recorded no correlation attempt has to "
            f"claim one. Null is a real third state here — 'not recorded' — and collapsing "
            f"it into False invents a skip that may never have happened."
        )

    @pytest.mark.asyncio
    async def test_the_table_really_has_them(self, tenant_async_url: str):
        """Against the real database, because migration 063 is what put them there and an
        ORM column with no migration behind it is the drift this suite exists to catch."""
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(tenant_async_url)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sa.text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'erp_sync_status' "
                        "AND column_name IN ('correlation_routed', 'correlation_reason')"
                    )
                )
                found = {name: nullable for name, nullable in rows.all()}
        finally:
            await engine.dispose()
        assert set(found) == {"correlation_routed", "correlation_reason"}, (
            f"migration 063 did not reach this database; found {sorted(found)}"
        )
        assert all(value == "YES" for value in found.values())


class TestTheResponseCarriesIt:
    """Boundary three, and the one `dropped` fell through in FS-591. FastAPI deletes an
    undeclared response field silently: the value is set on the server, absent from the
    payload, and nothing anywhere reports a problem."""

    @pytest.mark.parametrize("field", ["correlation_routed", "correlation_reason"])
    def test_the_response_model_declares_it(self, field: str):
        assert field in SyncStatusResponse.model_fields, (
            f"SyncStatusResponse omits {field}, so the server sets it and FastAPI drops it "
            f"on the way out — the exact shape that hid the edge agent's `dropped` counter"
        )

    def test_it_serialises_the_three_states(self):
        """`false` must survive as `false`, not be dropped as falsy — it is the whole
        signal. And `None` must stay `None` rather than becoming `false`, or every
        unmeasured sync starts claiming it was skipped."""
        assert SyncStatusResponse(
            id="x", entity_type="Shipment", correlation_routed=False,
            correlation_reason="no correlation route for this erp_type/entity_type",
        ).model_dump()["correlation_routed"] is False
        assert SyncStatusResponse(id="x", entity_type="Invoice").model_dump()[
            "correlation_routed"
        ] is None


class TestTheRouteWritesIt:
    """Boundary two. The service can return the outcome to a caller that throws it away —
    which is precisely what happened for the whole of FS-557..561."""

    def test_the_sync_route_persists_the_outcome(self):
        import inspect

        from app.api import erp_integrations

        source = inspect.getsource(erp_integrations)
        assert "sync_row.correlation_routed = correlation_summary[etype].get(\"routed\")" in source, (
            "the sync route no longer writes the correlation outcome onto the row, so it "
            "returns in the POST body and is gone on reload — while the UI polls "
            "sync-status, which is built from the row"
        )


class TestTheServiceStillDistinguishesTheCases:
    """The premise. If `routed` stopped being reported, everything above would faithfully
    persist and serve a field that no longer means anything."""

    @pytest.mark.asyncio
    async def test_an_unrouted_pair_is_reported_unrouted(self):
        from app.services.erp_sync_correlation import correlate_synced_records

        outcome = await correlate_synced_records(
            None,  # never reached: the route lookup fails first
            organization_id="00000000-0000-0000-0000-000000000001",
            integration_id="00000000-0000-0000-0000-000000000002",
            erp_type="a_vendor_with_no_analyzer",
            entity_type="invoice",
            records=[{"anything": 1}],
        )
        assert outcome["routed"] is False
        assert outcome["reason"], "unrouted with no reason is the state this all exists to end"

    @pytest.mark.asyncio
    async def test_no_records_is_not_reported_as_unrouted(self):
        """A sync that fetched nothing has not been skipped for want of an analyzer, and
        saying so would put a gap warning on the screen for an idle integration."""
        from app.services.erp_sync_correlation import correlate_synced_records

        outcome = await correlate_synced_records(
            None,
            organization_id="00000000-0000-0000-0000-000000000001",
            integration_id="00000000-0000-0000-0000-000000000002",
            erp_type="sap",
            entity_type="invoice",
            records=[],
        )
        assert outcome["reason"] == "no records"
