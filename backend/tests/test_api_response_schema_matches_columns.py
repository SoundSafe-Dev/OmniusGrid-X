"""No API response model may be stricter than the columns behind it — platform-wide.

THE DEFECT THIS GENERALISES. `ERPIntegrationResponse` declared `sync_schedule`,
`erp_type` and `sync_frequency_minutes` as required while all three are nullable on
`integration_configurations`. A row holding NULL in any of them could not be serialised
at all: pydantic raised inside the handler and FastAPI returned 500 — for create, list,
get AND update, because all four build the same model. The 500 named a validation error
in our schema rather than the data, so nobody would think to look at the row.

`tests/test_erp_response_schema.py` guards that with a hand-maintained mapping of ERP
models. This file does the same thing for **every** response model in `app/api/` by
discovering the pairs, so a new router cannot introduce the bug without being noticed.

WHAT IT DOES NOT CLAIM. It only inspects models it can confidently pair with an ORM
model by name (`FooResponse` -> `Foo`) and fields whose names match a column. A handler
that synthesises a value (`configuration.get("x", "")`) is out of scope, because there
the handler is the guarantee. `test_no_pair_is_vacuous` keeps the discovery honest: if
the pairing ever finds nothing, the whole file would pass while checking zero fields.

WHEN THIS WAS WRITTEN IT FOUND NOTHING, and that is the point of recording it. The ERP
models were the only offenders and were already fixed. Running it now proves the rest of
the API is clean rather than untested, and it fails the moment that stops being true.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import types
import typing
import warnings
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel
from sqlalchemy.inspection import inspect as sa_inspect

import app.api as api_pkg
import app.db.models as orm_models

RESPONSE_SUFFIXES = ("Response", "Out", "Read", "Detail", "Item")


def is_optional(annotation: Any) -> bool:
    """Does this annotation admit None?

    MUST handle both spellings. `Optional[str]` produces `typing.Union`, while the PEP
    604 form `str | None` produces `types.UnionType` — a different object. An earlier
    version of this check only tested `typing.Union`, so every `X | None` field was
    misread as required.

    That is not hypothetical: it made a scan of the whole API report 8 defects that did
    not exist, and it would have made the ERP guard fail the moment someone wrote a
    response field in modern syntax. `test_the_detector_handles_both_spellings` below
    exists because this helper is load-bearing — if it is wrong, every assertion in this
    file is meaningless in one direction or the other.
    """
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        return type(None) in typing.get_args(annotation)
    return annotation is type(None)


def _orm_classes() -> Dict[str, Any]:
    return {
        name: obj
        for name, obj in vars(orm_models).items()
        if isinstance(obj, type) and hasattr(obj, "__tablename__")
    }


def _columns(orm_class) -> Dict[str, Any]:
    try:
        return {c.key: c for c in sa_inspect(orm_class).columns}
    except Exception:  # noqa: BLE001 - not every mapped class inspects cleanly
        return {}


def _discover() -> List[Tuple[str, Any, Any]]:
    """(module, response model, ORM model) for every pair resolvable by name."""
    orm = _orm_classes()
    found: List[Tuple[str, Any, Any]] = []
    seen: set = set()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for module_info in pkgutil.iter_modules(api_pkg.__path__):
            try:
                module = importlib.import_module(f"app.api.{module_info.name}")
            except Exception:  # noqa: BLE001 - an unimportable router is another test's problem
                continue
            for name, obj in vars(module).items():
                if not (isinstance(obj, type) and issubclass(obj, BaseModel)):
                    continue
                # Deliberately NOT `obj.__module__ != module.__name__`. That skipped
                # every response model a router imports from `app/models/schemas.py`,
                # which is where a large share of them live — including
                # `DockDoorResponse`, whose live 500 this file had reported as clean.
                # Dedup below keeps a shared model from being checked once per router.
                if obj is BaseModel:
                    continue
                if not name.endswith(RESPONSE_SUFFIXES):
                    continue
                target = orm.get(re.sub(rf"({'|'.join(RESPONSE_SUFFIXES)})$", "", name))
                if target is not None and (obj, target) not in seen:
                    seen.add((obj, target))
                    found.append((module_info.name, obj, target))
    return found


PAIRS = _discover()


def _offenders() -> List[str]:
    """Fields that are required in the response but can genuinely be NULL on the row.

    A column with a default — Python-side or server-side — is excluded: the ORM or the
    database fills it, so a required response field is safe. Only a nullable column with
    NO default can actually hand pydantic a None.
    """
    bad: List[str] = []
    for module_name, response_model, orm_class in PAIRS:
        columns = _columns(orm_class)
        for field_name, field in response_model.model_fields.items():
            column = columns.get(field_name)
            if column is None or not column.nullable:
                continue
            # ONLY a server default makes a nullable column safe. This used to skip
            # `column.default is not None` as well — a PYTHON-side ORM default, which
            # fires only for rows written through SQLAlchemy. A migration, a seeder or
            # any raw INSERT leaves NULL, and then the response model cannot serialise
            # the row.
            #
            # That exclusion is why this file reported the whole API clean while
            # `DockDoorResponse.equipment_capabilities` (nullable, `default={}`,
            # no server default) returned a live 500 on a raw-inserted dock door.
            if column.server_default is not None:
                continue
            # A pydantic default does NOT rescue this either: the ORM hands the field
            # an explicit None rather than omitting it, so the default never applies
            # and validation runs against None. Hence `is_optional`, not
            # `is_required`, is the test that matters — a field with a default but a
            # non-optional type still fails.
            if not is_optional(field.annotation):
                bad.append(
                    f"{module_name}.{response_model.__name__}.{field_name} "
                    f"(column {orm_class.__name__}.{field_name} is nullable with no default)"
                )
    return bad



# ---------------------------------------------------------------------------
# Pre-existing offenders, recorded rather than hidden.
#
# WHY THERE IS A BASELINE AT ALL. This file used to assert zero offenders and
# passed — but it was excluding any column with a PYTHON-side ORM default, and
# it never paired response models that a router imports from
# `app/models/schemas.py`. Both exclusions were wrong, and correcting them took
# the count from 0 to 158 across 30 response models. The earlier "the rest of the
# API is clean" claim was true only of a much narrower scope than it described.
#
# THE CLASS IS REAL, not theoretical: `DockDoorResponse.equipment_capabilities`
# (nullable, `default={}`, no server default) returned a live 500 —
# "Input should be a valid dictionary" — on a dock door written by a raw INSERT.
# A Python-side default fires only for rows written through SQLAlchemy; a
# migration, a seeder or any raw INSERT leaves NULL. That one is fixed.
#
# 148 of the 158 are that shape; 10 have no default at all and are the most
# certain to bite.
#
# WHY NOT FIX THEM HERE. Weakening 158 response fields to Optional would degrade
# the contract every client codes against. The right fix is the opposite
# direction — server defaults in a migration, so the database enforces what the
# ORM already assumes, exactly as migrations 044/045 did for created_at/updated_at.
# That is a schema change with its own review, not a side effect of correcting a
# detector.
#
# THIS LIST MAY ONLY SHRINK. A new offender fails the build, and fixing one
# without removing it from the list fails too, so it cannot quietly become
# permanent.

KNOWN_OFFENDERS = frozenset({
    "alarms.AlarmResponse.is_acknowledged",
    "alarms.AlarmResponse.is_active",
    "analysis_sessions.SessionMessageResponse.timestamp",
    "assets.AssetResponse.connection_config",
    "assets.AssetResponse.created_at",
    "assets.AssetResponse.current_packml_state",
    "assets.AssetResponse.is_active",
    "assets.AssetResponse.media_config",
    "assets.AssetResponse.updated_at",
    "assets.AssetTypeResponse.action_space",
    "assets.AssetTypeResponse.created_at",
    "assets.AssetTypeResponse.packml_config",
    "assets.AssetTypeResponse.telemetry_schema",
    "commands.CommandResponse.status",
    "kanban.TaskBoardResponse.board_type",
    "kanban.TaskBoardResponse.created_at",
    "kanban.TaskBoardResponse.default_view_config",
    "kanban.TaskBoardResponse.is_active",
    "kanban.TaskBoardResponse.updated_at",
    "kanban.TaskColumnResponse.auto_archive_days",
    "kanban.TaskColumnResponse.color",
    "kanban.TaskColumnResponse.created_at",
    "kanban.TaskColumnResponse.is_collapsed",
    "kanban.TaskColumnResponse.updated_at",
    "kanban.TaskColumnResponse.wip_limit",
    "kanban.TaskCommentResponse.comment_type",
    "kanban.TaskCommentResponse.content",
    "kanban.TaskCommentResponse.created_at",
    "kanban.TaskCommentResponse.extra_data",
    "kanban.TaskEscalationResponse.actions_taken",
    "kanban.TaskEscalationResponse.notification_channels",
    "kanban.TaskEscalationResponse.notified_users",
    "kanban.TaskEscalationResponse.triggered_at",
    "kanban.TaskResponse.approval_status",
    "kanban.TaskResponse.checklist_items",
    "kanban.TaskResponse.completion_actions",
    "kanban.TaskResponse.completion_result",
    "kanban.TaskResponse.created_at",
    "kanban.TaskResponse.custom_fields",
    "kanban.TaskResponse.position",
    "kanban.TaskResponse.priority",
    "kanban.TaskResponse.progress_percent",
    "kanban.TaskResponse.status",
    "kanban.TaskResponse.tags",
    "kanban.TaskResponse.time_logged_minutes",
    "kanban.TaskResponse.updated_at",
    "kanban.TaskRuleResponse.assignee_rule",
    "kanban.TaskRuleResponse.auto_approve_emergency",
    "kanban.TaskRuleResponse.auto_approve_timeout_minutes",
    "kanban.TaskRuleResponse.completion_actions",
    "kanban.TaskRuleResponse.created_at",
    "kanban.TaskRuleResponse.escalation_config",
    "kanban.TaskRuleResponse.is_active",
    "kanban.TaskRuleResponse.is_system_rule",
    "kanban.TaskRuleResponse.notify_users",
    "kanban.TaskRuleResponse.task_template",
    "kanban.TaskRuleResponse.trigger_conditions",
    "kanban.TaskRuleResponse.updated_at",
    "kanban.TaskTimerResponse.created_at",
    "kanban.TaskTimerResponse.duration_minutes",
    "kanban.TaskTimerResponse.is_running",
    "logistics_correlation.LoadQualityLogResponse.carrier_liable",
    "logistics_correlation.LoadQualityLogResponse.claim_filed",
    "logistics_correlation.LoadQualityLogResponse.created_at",
    "logistics_correlation.LoadQualityLogResponse.updated_at",
    "logistics_correlation.TruckAssetCorrelationResponse.created_at",
    "logistics_correlation.TruckAssetCorrelationResponse.detention_incurred",
    "operations.OperationResponse.created_at",
    "operations.OperationResponse.packml_state_durations",
    "registries.ActionableRegistryItemResponse.compliance_score",
    "registries.ActionableRegistryItemResponse.created_at",
    "registries.ActionableRegistryItemResponse.is_active",
    "registries.ActionableRegistryItemResponse.is_required",
    "registries.ActionableRegistryItemResponse.meta_data",
    "registries.ActionableRegistryItemResponse.risk_score",
    "registries.ActionableRegistryItemResponse.severity_level",
    "registries.ActionableRegistryItemResponse.updated_at",
    "registries.ActionableRegistryResponse.checklist_requirements",
    "registries.ActionableRegistryResponse.compliance_score",
    "registries.ActionableRegistryResponse.created_at",
    "registries.ActionableRegistryResponse.is_active",
    "registries.ActionableRegistryResponse.is_compliance",
    "registries.ActionableRegistryResponse.meta_data",
    "registries.ActionableRegistryResponse.priority_level",
    "registries.ActionableRegistryResponse.updated_at",
    "registries.DataCorrelationResponse.confidence_score",
    "registries.DataCorrelationResponse.correlation_meta_data",
    "registries.DataCorrelationResponse.correlation_method",
    "registries.DataCorrelationResponse.correlation_strength",
    "registries.DataCorrelationResponse.created_at",
    "registries.DataCorrelationResponse.is_active",
    "registries.DataCorrelationResponse.is_bidirectional",
    "registries.DataCorrelationResponse.updated_at",
    "transportation.CarrierResponse.contact_info",
    "transportation.CarrierResponse.contract_rate",
    "transportation.CarrierResponse.created_at",
    "transportation.CarrierResponse.ctpat_certified",
    "transportation.CarrierResponse.insurance_on_file",
    "transportation.CarrierResponse.is_active",
    "transportation.CarrierResponse.updated_at",
    "transportation.DriverResponse.created_at",
    "transportation.DriverResponse.dq_file_complete",
    "transportation.DriverResponse.hazmat_endorsed",
    "transportation.DriverResponse.hos_cycle_hours",
    "transportation.DriverResponse.hos_drive_hours_today",
    "transportation.DriverResponse.hos_on_duty_hours_today",
    "transportation.DriverResponse.is_active",
    "transportation.DriverResponse.updated_at",
    "transportation.FreightChargeResponse.created_at",
    "transportation.FreightChargeResponse.currency",
    "transportation.FreightChargeResponse.is_billed",
    "transportation.FreightChargeResponse.shipment_id",
    "transportation.FreightChargeResponse.updated_at",
    "transportation.LoadPlanResponse.created_at",
    "transportation.LoadPlanResponse.is_executed",
    "transportation.LoadPlanResponse.load_sequence",
    "transportation.LoadPlanResponse.planned_at",
    "transportation.LoadPlanResponse.shipment_id",
    "transportation.LoadPlanResponse.temperature_zones",
    "transportation.LoadPlanResponse.updated_at",
    "transportation.LoadPlanResponse.weight_distribution",
    "transportation.RouteResponse.created_at",
    "transportation.RouteResponse.is_active",
    "transportation.RouteResponse.optimization_criteria",
    "transportation.RouteResponse.updated_at",
    "transportation.RouteResponse.waypoints",
    "transportation.ShipmentResponse.created_at",
    "transportation.ShipmentResponse.destination",
    "transportation.ShipmentResponse.hazmat",
    "transportation.ShipmentResponse.origin",
    "transportation.ShipmentResponse.priority",
    "transportation.ShipmentResponse.shipment_type",
    "transportation.ShipmentResponse.status",
    "transportation.ShipmentResponse.temperature_required",
    "transportation.ShipmentResponse.updated_at",
    "workcells.OrganizationOut.settings",
    "yard.DockAppointmentResponse.appointment_type",
    "yard.DockAppointmentResponse.compliance_required",
    "yard.DockAppointmentResponse.created_at",
    "yard.DockAppointmentResponse.dock_door_id",
    "yard.DockAppointmentResponse.priority",
    "yard.DockAppointmentResponse.status",
    "yard.DockAppointmentResponse.updated_at",
    "yard.DriverWaitTimeResponse.created_at",
    "yard.DriverWaitTimeResponse.driver_id",
    "yard.DriverWaitTimeResponse.is_billed",
    "yard.DriverWaitTimeResponse.updated_at",
    "yard.YardCheckPointResponse.created_at",
    "yard.YardCheckPointResponse.passed_at",
    "yard.YardCheckPointResponse.trailer_id",
    "yard.YardMoveResponse.created_at",
    "yard.YardMoveResponse.started_at",
    "yard.YardMoveResponse.trailer_id",
    "yard.YardTrailerResponse.check_in_at",
    "yard.YardTrailerResponse.created_at",
    "yard.YardTrailerResponse.seal_status",
    "yard.YardTrailerResponse.status",
    "yard.YardTrailerResponse.updated_at",
})


class TestTheDetectorItself:
    """This helper decides every other assertion, so it is tested first."""

    def test_the_detector_handles_both_spellings(self):
        assert is_optional(typing.Optional[str]), "Optional[str] not recognised"
        assert is_optional(str | None), (
            "PEP 604 `str | None` not recognised — it produces types.UnionType, not "
            "typing.Union. Getting this wrong misreads every modern annotation as "
            "required and manufactures defects that do not exist."
        )
        assert is_optional(typing.Union[int, None])
        assert is_optional(int | str | None)

    def test_the_detector_rejects_genuinely_required_annotations(self):
        assert not is_optional(str)
        assert not is_optional(int)
        assert not is_optional(typing.Union[int, str])
        assert not is_optional(List[str])


class TestNoResponseModelIsStricterThanItsColumns:
    def test_no_new_offenders(self):
        """A field not on the recorded baseline is a regression."""
        current = {o.split(" ")[0] for o in _offenders()}
        new = sorted(current - KNOWN_OFFENDERS)
        assert not new, (
            "A required response field over a nullable, server-default-less column "
            "means a valid row cannot be serialised — pydantic raises inside the "
            "handler and FastAPI returns 500, naming a validation error in our schema "
            "rather than the data. New offenders:\n  " + "\n  ".join(new)
        )

    def test_the_baseline_only_shrinks(self):
        """Fixing an offender must remove it from the list, or the list stops
        describing reality and the guard silently loses coverage."""
        current = {o.split(" ")[0] for o in _offenders()}
        fixed = sorted(KNOWN_OFFENDERS - current)
        assert not fixed, (
            "These are recorded as known offenders but no longer offend. Delete them "
            "from KNOWN_OFFENDERS:\n  " + "\n  ".join(fixed)
        )

    def test_the_baseline_is_not_growing_silently(self):
        """A hard ceiling, so the list cannot be topped up instead of drained."""
        assert len(KNOWN_OFFENDERS) <= 158, (
            f"{len(KNOWN_OFFENDERS)} recorded offenders — the baseline was 158 and is "
            f"supposed to shrink"
        )

    def test_no_pair_is_vacuous(self):
        """Guards the guard. If discovery finds nothing — a rename, a moved module, a
        broken import — every assertion above passes while checking zero fields, which
        is exactly how the original bug survived."""
        assert len(PAIRS) >= 10, (
            f"only {len(PAIRS)} response/ORM pairs discovered; the sweep is not "
            f"covering the API and would pass vacuously"
        )

    def test_at_least_one_paired_column_is_nullable_without_a_default(self):
        """The other half of not-vacuous: if no discovered column could ever be NULL,
        `test_no_offenders` proves nothing."""
        candidates = [
            f"{orm_class.__name__}.{name}"
            for _m, _r, orm_class in PAIRS
            for name, column in _columns(orm_class).items()
            if column.nullable and column.server_default is None and column.default is None
        ]
        assert candidates, (
            "no paired column is nullable-without-default, so the sweep has nothing to "
            "catch and would pass regardless"
        )


class TestCoverageIsVisible:
    def test_report_what_is_actually_covered(self, capsys):
        """Not an assertion so much as a record. A guard whose reach is invisible drifts
        without anyone noticing which routers it stopped covering."""
        modules = sorted({m for m, _r, _o in PAIRS})
        fields = sum(len(r.model_fields) for _m, r, _o in PAIRS)
        with capsys.disabled():
            print(
                f"\n  response-schema sweep: {len(PAIRS)} model pairs across "
                f"{len(modules)} routers, {fields} fields compared"
            )
        assert fields > 50
