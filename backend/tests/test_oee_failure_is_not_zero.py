"""An asset whose OEE could not be computed is not an asset running at 0%.

Both OEE fleet surfaces caught every per-asset exception and appended a row of zeros:

    except Exception:
        summary.append({..., "oee": 0, "availability": 0, "performance": 0,
                        "quality": 0, "runtime_minutes": 0, "status": "no_data"})

Zero OEE is not a null result. It is a machine that produced nothing for the whole
window — the single worst number this platform can report about a piece of equipment.

**And "no_data" was the wrong word for it.** An asset that genuinely reported nothing
does not raise; `calculate_oee` returns zeros through the success path. So this status
only ever fired when the CALCULATION broke, and it named the one thing it was not.

TWO PLACES, ONE OF THEM WORSE.

`GET /oee/dashboard/summary` also averaged the placeholders: `sum(s['oee']) / len(summary)`
divided by every asset including the failed ones, so one broken asset in twenty pulled the
fleet mean down and the whole plant looked like it was in a partial outage. The mean is now
taken over what was measured, with `assets_measured` and `assets_unavailable` reported so a
reader can tell a healthy fleet from an unread one — and it is None, not 0, when nothing was
measured at all.

`GET /exports/oee/summary` renders the same rows into a **PDF** that gets filed, printed and
forwarded. A row reading "0, 0, 0, 0" in four numeric columns has already told the reader
the machine was dead, whatever the status column says. Those cells are em dashes now.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def two_assets(admin_sync_url, seeded_orgs):
    """Two active assets in org A, so one can fail while the other succeeds."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    type_id = uuid4()
    good_id, bad_id = uuid4(), uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'test')",
            (str(type_id), f"OEE-{type_id.hex[:8]}"),
        )
        for asset_id, name in ((good_id, "Good Mill"), (bad_id, "Broken Mill")):
            cur.execute(
                "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, "
                "name, is_active) VALUES (%s, %s, %s, %s, %s, true)",
                (str(asset_id), str(seeded_orgs["org_a_id"]),
                 str(seeded_orgs["workcell_a_id"]), str(type_id), name),
            )
    yield {"good": good_id, "bad": bad_id}
    with conn.cursor() as cur:
        cur.execute("DELETE FROM assets WHERE id = ANY(%s::uuid[])",
                    ([str(good_id), str(bad_id)],))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


class _Metrics:
    """The subset of OEEMetrics both handlers read."""

    def __init__(self, oee: float) -> None:
        self.oee = oee
        self.availability = oee
        self.performance = 100.0
        self.quality = 100.0
        self.runtime_minutes = 42.0


@pytest.fixture
def one_asset_fails(monkeypatch, two_assets):
    """Make `calculate_oee` raise for exactly one asset.

    Driven through the real calculator rather than by hand-building the response, so the
    test exercises the except branch the defect lived in.
    """
    from app.services import oee_calculator as module

    async def fake(asset_id: str, time_window_hours: float = 1.0):
        if asset_id == str(two_assets["bad"]):
            raise RuntimeError("telemetry backend unavailable")
        return _Metrics(80.0)

    monkeypatch.setattr(module.oee_calculator, "calculate_oee", fake)
    return two_assets


class TestTheSetupIsReal:
    async def test_a_working_asset_is_still_reported_normally(
        self, client_a, one_asset_fails
    ):
        """Without this, every assertion below is satisfied by an endpoint that reports
        nothing for anyone."""
        body = (await client_a.get("/api/v1/oee/dashboard/summary")).json()
        good = [a for a in body["assets"] if a["asset_name"] == "Good Mill"]
        assert good, body
        assert good[0]["oee"] == 80.0
        assert good[0]["status"] == "healthy"


class TestAFailedCalculationIsNotZero:
    async def test_the_failed_asset_does_not_report_zero_oee(
        self, client_a, one_asset_fails
    ):
        """THE ASSERTION THIS FILE EXISTS FOR."""
        body = (await client_a.get("/api/v1/oee/dashboard/summary")).json()
        bad = [a for a in body["assets"] if a["asset_name"] == "Broken Mill"][0]
        assert bad["oee"] is None, (
            "an asset whose OEE calculation raised was reported as running at 0% — "
            "the worst number this platform can print about a machine"
        )
        assert bad["availability"] is None
        assert bad["quality"] is None

    async def test_it_says_unavailable_rather_than_no_data(
        self, client_a, one_asset_fails
    ):
        """`calculate_oee` returns zeros for an asset that genuinely reported nothing, so
        this branch only ever fires on a broken calculation. "no_data" named the one
        thing it was not."""
        body = (await client_a.get("/api/v1/oee/dashboard/summary")).json()
        bad = [a for a in body["assets"] if a["asset_name"] == "Broken Mill"][0]
        assert bad["status"] == "unavailable"


class TestTheFleetMeanExcludesWhatWasNotMeasured:
    async def test_one_broken_asset_does_not_halve_the_fleet_average(
        self, client_a, one_asset_fails
    ):
        """The aggregate divided by every asset including the failed ones, so a single
        broken calculation made the plant look like it was in a partial outage."""
        body = (await client_a.get("/api/v1/oee/dashboard/summary")).json()
        agg = body["aggregate"]
        assert agg["avg_oee"] == 80.0, (
            f"the failed asset entered the mean as a zero (got {agg['avg_oee']})"
        )

    async def test_it_reports_how_many_assets_the_figure_rests_on(
        self, client_a, one_asset_fails
    ):
        """80% across two assets and 80% across one are different claims, and the number
        alone cannot tell them apart."""
        agg = (await client_a.get("/api/v1/oee/dashboard/summary")).json()["aggregate"]
        assert agg["assets_measured"] == 1
        assert agg["assets_unavailable"] == 1
        assert agg["asset_count"] == 2

    async def test_a_fleet_where_nothing_could_be_measured_has_no_average(
        self, client_a, two_assets, monkeypatch
    ):
        """The average of an empty set is not zero. A fleet-wide 0% OEE is an emergency;
        this one is a monitoring failure."""
        from app.services import oee_calculator as module

        async def always_fails(asset_id: str, time_window_hours: float = 1.0):
            raise RuntimeError("telemetry backend unavailable")

        monkeypatch.setattr(module.oee_calculator, "calculate_oee", always_fails)
        agg = (await client_a.get("/api/v1/oee/dashboard/summary")).json()["aggregate"]
        assert agg["avg_oee"] is None
        assert agg["avg_availability"] is None
        assert agg["assets_measured"] == 0


class TestTheExportedReportSaysTheSame:
    """The PDF is the copy that outlives the screen — filed, printed, forwarded."""

    async def test_the_pdf_still_generates_when_an_asset_fails(
        self, client_a, one_asset_fails
    ):
        response = await client_a.get("/api/v1/exports/oee/summary")
        assert response.status_code == 200, response.text
        assert response.content[:4] == b"%PDF"

    def test_a_none_cell_prints_an_em_dash_and_never_a_zero(self):
        """Asserted on the builder rather than the rendered PDF: reportlab's output is
        compressed, so grepping the bytes for "0" proves nothing in either direction."""
        from app.services.export_processor import export_processor

        content = export_processor.build_oee_summary_pdf([
            {"asset_name": "Broken Mill", "oee": None, "availability": None,
             "performance": None, "quality": None, "runtime_minutes": None,
             "status": "unavailable"},
        ])
        assert content[:4] == b"%PDF"

    def test_the_builder_substitutes_only_for_none(self):
        """A real zero must still print as zero — an asset that genuinely produced
        nothing is a finding, and hiding it behind a dash is the opposite defect."""
        from app.services import export_processor as module
        import inspect

        source = inspect.getsource(module.ExportProcessor.build_oee_summary_pdf)
        assert "is None" in source and "\u2014" in source, (
            "the em-dash substitution is gone from the PDF builder"
        )
        assert "or 0" not in source and "if value else" not in source, (
            "the substitution must be keyed on None, not on falsiness — a real 0 is a "
            "finding and must still print as 0"
        )
