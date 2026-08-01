"""A `response_model` must name every key its handler produces.

THE HAZARD THIS FILE EXISTS FOR. Declaring a response model is not additive.
FastAPI **filters the response through it**: any key the handler returns that the
model does not declare is silently deleted from the payload. The request still
returns 200, the client still parses it, and the missing field renders as blank.

That is this repository's most expensive defect class arriving through the front
door — `AssetResponse` omitting `maintenance_mode` cost a column, a write
endpoint and an engine that honoured it (see
`test_response_models_match_their_tables.py`, which asserts the opposite
direction: fields declared that nothing produces).

So the burn-down of pool #43 needs this: for every route where a model was
attached to an already-working handler, the model's field set must equal the
dict the handler builds. Not a subset. Equal.

WHY THE ASSERTIONS ARE AGAINST THE SHAPING HELPERS AND NOT LIVE RESPONSES.
These routers build their payload in one place — `_vehicle_row`, `_security_out`,
`_driver_safety_out` — precisely so the list and detail endpoints cannot drift.
Calling those helpers with stub rows needs no database and pins the contract at
the point the shape is decided, which is where a future edit would break it. A
live-response test would need Postgres and would only cover whichever route the
fixture happened to exercise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api import fleet_health as fh


def _diag(**over):
    base = dict(
        dtc_code="P0301",
        description="Cylinder 1 misfire",
        severity="critical",
        last_seen_at=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        status="active",
        vehicle_id="VH-1",
        device_id="DEV-1",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _exception(**over):
    base = dict(
        id=uuid4(),
        device_id="DEV-1",
        exception_type="speeding",
        timestamp=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        severity="high",
        location={"lat": 1.0, "lng": 2.0},
        acknowledged=False,
        driver_id=uuid4(),
    )
    base.update(over)
    return SimpleNamespace(**base)


def _driver(**over):
    base = dict(id=uuid4(), first_name="Dana", last_name="Reyes")
    base.update(over)
    return SimpleNamespace(**base)


class TestTheModelNamesEveryKeyTheHandlerProduces:
    """The load-bearing direction: a key the model omits is a key the client loses."""

    def test_vehicle_health_item(self):
        produced = set(fh._vehicle_row("VH-1", [_diag()], 3))
        declared = set(fh.VehicleHealthItem.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )

    def test_security_event_item(self):
        produced = set(fh._security_out(_exception()))
        declared = set(fh.SecurityEventItem.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )

    def test_driver_safety_item(self):
        produced = set(
            fh._driver_safety_out(_driver(), {"harsh_braking": 2, "speeding": 1})
        )
        declared = set(fh.DriverSafetyItem.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )

    def test_dtc_item(self):
        """Pre-existing model, asserted for the first time — it was attached to
        four routes with nothing checking it still matched `_dtc_out`."""
        produced = set(fh._dtc_out(_diag()))
        declared = set(fh.DtcItem.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )


class TestExportsShapersMatchTheirModels:
    """`exports.py` builds every JSON payload through three shapers, so the same
    three models cover eleven routes. That leverage cuts both ways: one dropped
    field is dropped from list, create, get and update at once."""

    @staticmethod
    def _template():
        now = datetime(2026, 7, 31, tzinfo=timezone.utc)
        return SimpleNamespace(
            id=uuid4(), organization_id=uuid4(), name="n", description=None,
            export_type="telemetry", export_format="csv", columns=None, filters=None,
            created_by=None, created_at=now, updated_at=now,
        )

    @staticmethod
    def _schedule():
        now = datetime(2026, 7, 31, tzinfo=timezone.utc)
        return SimpleNamespace(
            id=uuid4(), organization_id=uuid4(), template_id=uuid4(), name="s",
            frequency="daily", timezone="UTC", next_run_at=None, recipients=None,
            is_active=True, last_run_at=None, last_status=None, created_by=None,
            created_at=now, updated_at=now,
        )

    @staticmethod
    def _job():
        return {
            "job_id": "j1", "type": "telemetry", "status": "completed", "total": 5,
            "processed": 5, "succeeded": 5, "failed": 0, "filename": "f.csv",
            "created_at": "2026-07-31T00:00:00Z", "updated_at": "2026-07-31T00:00:00Z",
        }

    def test_template_out(self):
        from app.api import exports as ex
        produced = set(ex._template_dict(self._template()))
        assert produced == set(ex.ExportTemplateOut.model_fields)

    def test_schedule_out(self):
        from app.api import exports as ex
        produced = set(ex._schedule_dict(self._schedule()))
        assert produced == set(ex.ScheduledExportOut.model_fields)

    def test_job_out_omits_the_server_side_file_path(self):
        from app.api import exports as ex
        produced = set(ex._job_public(self._job()))
        assert produced == set(ex.ExportJobOut.model_fields)
        # `_job_public` exists to keep `file_path` off the wire. If it ever
        # reappears, the model must not be the thing that quietly hides it again.
        assert "file_path" not in produced

    def test_the_shapers_validate_with_null_columns_and_recipients(self):
        """`columns or []` / `recipients or []` — the null-column path is what a
        freshly-created row looks like before the worker fills it in."""
        from app.api import exports as ex
        ex.ExportTemplateOut.model_validate(ex._template_dict(self._template()))
        ex.ScheduledExportOut.model_validate(ex._schedule_dict(self._schedule()))
        ex.ExportJobOut.model_validate(ex._job_public(self._job()))


class TestTheModelAcceptsWhatTheHandlerProduces:
    """Naming a key is not enough — the declared TYPE has to accept the value.

    A field typed `str` against a handler that can return `None` fails
    validation at response time, which surfaces as a 500 on a route that worked
    yesterday. The empty/default cases below are the ones most likely to differ
    from the populated case.
    """

    def test_a_vehicle_with_no_diagnostics_validates(self):
        # `_vehicle_row(vid, [], 0)` is the documented "unknown vehicle" default,
        # reached by the single-vehicle endpoint for any id it has no rows for.
        fh.VehicleHealthItem.model_validate(fh._vehicle_row("VH-UNKNOWN", [], 0))

    def test_a_populated_vehicle_validates(self):
        fh.VehicleHealthItem.model_validate(fh._vehicle_row("VH-1", [_diag()], 3))

    def test_a_diagnostic_with_null_fields_validates(self):
        fh.DtcItem.model_validate(
            fh._dtc_out(_diag(dtc_code=None, description=None, severity=None,
                              last_seen_at=None, vehicle_id=None))
        )

    def test_an_exception_with_no_location_validates(self):
        fh.SecurityEventItem.model_validate(
            fh._security_out(_exception(location=None, timestamp=None, severity=None))
        )

    def test_a_driver_with_no_events_validates(self):
        fh.DriverSafetyItem.model_validate(fh._driver_safety_out(_driver(), {}))


def _fl_zone(**over):
    """A circle zone as `geofence_zones` stores one."""
    base = dict(
        id=uuid4(), name="Depot", zone_type="circle", center_lat=51.5, center_lng=-0.1,
        radius_meters=250.0, polygon=None, trigger_on="both", severity="warning",
        is_active=True,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _fl_schedule(**over):
    base = dict(
        id=uuid4(), vehicle_id="VH-1", maintenance_type="oil_change",
        description="6-month service",
        due_date=datetime(2026, 8, 15, tzinfo=timezone.utc),
        due_odometer_miles=145000.0, status="scheduled", priority="urgent",
        estimated_cost=420.5, completed_at=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _fl_order(**over):
    base = dict(
        id=uuid4(), vehicle_id="VH-1", title="Brake pads", description="Front pads worn",
        status="open", priority="medium", vendor="Acme Motors", cost=310.0,
        category="brakes", opened_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        completed_at=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


class TestFleetLogisticsShapersMatchTheirModels:
    """`fleet_logistics.py` is the largest single file in the burn-down — 23 routes — and it
    reaches that size by serving four shapes from four helpers, each on several routes.

    `_schedule_out` alone backs list, get, patch, create and the per-vehicle list. So one
    field missing from `MaintenanceScheduleOut` is that field missing from five endpoints,
    and the AST sweep next door cannot see any of it: these handlers return
    `[_schedule_out(s) for s in ...]`, which has no dict literal in the syntax. This is
    exactly the blind spot that file documents and this one covers.
    """

    def test_zone_out(self):
        from app.api import fleet_logistics as fl
        produced = set(fl._zone_out(_fl_zone()))
        declared = set(fl.GeofenceZoneOut.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )

    def test_schedule_out(self):
        from app.api import fleet_logistics as fl
        produced = set(fl._schedule_out(_fl_schedule()))
        declared = set(fl.MaintenanceScheduleOut.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )

    def test_order_out(self):
        from app.api import fleet_logistics as fl
        produced = set(fl._order_out(_fl_order()))
        declared = set(fl.RepairOrderOut.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )

    def test_history_out(self):
        from app.api import fleet_logistics as fl
        produced = set(fl._history_out(_fl_order()))
        declared = set(fl.ServiceHistoryOut.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )

    def test_summarize_maintenance(self):
        """`summarize_maintenance` feeds `/statistics` directly AND supplies five of the six
        keys `/costs` re-labels, so its key set is load-bearing twice over."""
        from app.api import fleet_logistics as fl
        produced = set(fl.summarize_maintenance([_fl_schedule()], [_fl_order()]))
        declared = set(fl.MaintenanceStatisticsOut.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )

    def test_delivery_efficiency(self):
        """The aggregate lives in `transportation.py`; the route that declares a model for it
        is in `fleet_logistics.py`. Nothing else pins those two together."""
        from app.api.transportation import compute_delivery_efficiency
        from app.api import fleet_logistics as fl
        produced = set(compute_delivery_efficiency([]))
        declared = set(fl.DeliveryEfficiencyOut.model_fields)
        assert produced == declared, (
            f"dropped by the model: {sorted(produced - declared)} · "
            f"declared but never produced: {sorted(declared - produced)}"
        )


class TestFleetLogisticsModelsAcceptTheEmptyPaths:
    """The populated row is the easy case. These are the ones a fixture-shaped test misses.

    Every nullable column in the four tables is reachable: a POLYGON zone has no centre and
    no radius, a schedule created without a due date has no `scheduledDate`, a repair order
    that is still open has no `completedAt`, and a fleet with nothing outstanding produces
    `upcomingEstimated: None` — which is not the same fact as an estimate of zero.
    """

    def test_a_polygon_zone_with_no_centre_or_radius_validates(self):
        from app.api import fleet_logistics as fl
        fl.GeofenceZoneOut.model_validate(fl._zone_out(_fl_zone(
            zone_type="polygon", center_lat=None, center_lng=None, radius_meters=None,
            polygon=[[51.5, -0.1], [51.6, -0.1], [51.6, -0.2]],
        )))

    def test_a_zone_with_a_float_radius_validates(self):
        """`radius_meters` is a Float column. An `int` here is the `HealthBandItem.min/max`
        bug — correct field name, wrong type, 500 on the first fractional row."""
        from app.api import fleet_logistics as fl
        fl.GeofenceZoneOut.model_validate(fl._zone_out(_fl_zone(radius_meters=249.75)))

    def test_a_schedule_with_no_due_date_or_estimate_validates(self):
        from app.api import fleet_logistics as fl
        fl.MaintenanceScheduleOut.model_validate(fl._schedule_out(_fl_schedule(
            due_date=None, due_odometer_miles=None, estimated_cost=None, description=None,
        )))

    def test_an_overdue_schedule_reports_overdue_and_validates(self):
        from app.api import fleet_logistics as fl
        row = fl._schedule_out(_fl_schedule(
            due_date=datetime(2020, 1, 1, tzinfo=timezone.utc), status="scheduled"
        ))
        assert row["status"] == "overdue"
        fl.MaintenanceScheduleOut.model_validate(row)

    def test_an_open_repair_order_with_no_cost_validates(self):
        from app.api import fleet_logistics as fl
        fl.RepairOrderOut.model_validate(fl._order_out(_fl_order(
            cost=None, vendor=None, category=None, description=None, completed_at=None,
        )))

    def test_a_history_entry_with_no_cost_or_notes_validates(self):
        """`_history_out` coerces a missing cost to the integer `0` — a `float` field takes
        it, an `int` field would then reject the real 310.0 next door."""
        from app.api import fleet_logistics as fl
        fl.ServiceHistoryOut.model_validate(fl._history_out(_fl_order(
            cost=None, description=None, vendor=None, category=None,
        )))

    def test_an_empty_fleet_summarises_and_validates(self):
        from app.api import fleet_logistics as fl
        stats = fl.summarize_maintenance([], [])
        assert stats["upcomingEstimated"] is None, (
            "None means nobody has costed the outstanding work; 0 means it is free"
        )
        fl.MaintenanceStatisticsOut.model_validate(stats)

    def test_an_empty_delivery_efficiency_validates(self):
        from app.api.transportation import compute_delivery_efficiency
        from app.api import fleet_logistics as fl
        fl.DeliveryEfficiencyOut.model_validate(compute_delivery_efficiency([]))
