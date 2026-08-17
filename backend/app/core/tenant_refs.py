"""Refuse a request field that names a row the caller's organisation does not own.

WHY THIS IS A MODULE AND NOT A CHECK IN EACH HANDLER (FS-737).

**A foreign key is validated below row-level security.** A policy decides which rows a
session may READ; Postgres checks a reference without consulting it. So a request body
carrying another tenant's id is accepted by the database, and the only thing that can
refuse it is the handler.

Six of these were closed one at a time — `operations` (FS-720), four shop-floor writes
(FS-724), two notification subscriptions (FS-726), insight activation (FS-729), six kanban
task links and the command back door (FS-736). Each fix was correct and none of them
generalised, so the seventh instance started from zero exactly like the first.

Then the population was measured: **89 id-shaped fields across 35 request models** in
`app/models/schemas.py`, on 31 live routes. Nine cross-tenant writes were reproduced over
HTTP in one sitting. At that size the answer is not a seventh hand-written check.

WHAT THE REGISTRY BUYS. `verify_refs` is the runtime half; the guard in
`test_every_tenant_reference_is_registered.py` is the half that matters over time — every
id-shaped field on a request schema must appear in `TENANT_REFS` or in `NOT_TENANT_SCOPED`
with a reason, so a field ADDED next year fails the build rather than quietly joining the
class. A fix that only closes today's instances is a fix that has to be rediscovered.

404, NEVER 403. An id in another tenant is an id that does not exist as far as this caller
is concerned; 403 would confirm that it does, which is a membership oracle over every
table listed here.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.exc import DBAPIError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ActionableRegistry,
    Alarm,
    Asset,
    Carrier,
    Command,
    DockDoor,
    Driver,
    Operation,
    Route,
    Shipment,
    Task,
    TaskBoard,
    TaskColumn,
    User,
    Workcell,
    YardTrailer,
)


#: WHICH HALF OF THIS IS LOAD-BEARING, measured rather than assumed (rule 213).
#:
#: Deleting `model.organization_id == org` from `_direct` and re-running the real-database
#: guards failed **two** assertions out of fifty-one, both on `assigned_to`. The reason is
#: worth writing down: every other table these queries touch is under FORCE ROW LEVEL
#: SECURITY, and `verify_refs` runs on a tenant-bound session, so the policy has already
#: removed the other tenant's row before the predicate is evaluated.
#:
#:     under FORCE RLS   assets alarms commands carriers drivers shipments
#:                       yard_trailers dock_doors routes workcells task_boards
#:     NO policy at all  users tasks task_columns operations
#:
#: So for the second group the predicate (or the join) is the ONLY thing refusing the
#: write, and for the first it is redundant TODAY. It stays, and not out of caution: the
#: redundancy holds only while the caller passes a tenant-bound session. Hand this an
#: `AsyncSessionLocal()` — which is how four defects in this codebase were introduced, most
#: recently the GeoTab webhook — and the policy stops applying while the predicate does not.
#: A check that is redundant under one precondition is a check that becomes load-bearing
#: the moment somebody breaks it.


def _direct(model) -> Callable[[Any, Any], Select]:
    """A table that carries `organization_id` itself."""

    def build(ref: Any, org: Any) -> Select:
        return select(model.id).where(model.id == ref, model.organization_id == org)

    return build


def _via_asset(model) -> Callable[[Any, Any], Select]:
    """A table tenanted through the asset it belongs to — `operations` has no org column."""

    def build(ref: Any, org: Any) -> Select:
        return (
            select(model.id)
            .join(Asset, model.asset_id == Asset.id)
            .where(model.id == ref, Asset.organization_id == org)
        )

    return build


def _via_board(model) -> Callable[[Any, Any], Select]:
    """A table tenanted through the kanban board above it — `tasks`, `task_columns`."""

    def build(ref: Any, org: Any) -> Select:
        return (
            select(model.id)
            .join(TaskBoard, model.board_id == TaskBoard.id)
            .where(model.id == ref, TaskBoard.organization_id == org)
        )

    return build


#: Request-body field name -> how to prove the caller's organisation owns that row.
#:
#: KEYED BY FIELD NAME, which is a deliberate trade. It means one entry covers every route
#: that accepts `carrier_id`, including routes not written yet — and it means a field whose
#: name is reused for a DIFFERENT table would be checked against the wrong one. The guard
#: asserts the name-to-table mapping is consistent across every schema that declares it, so
#: that collision fails the build rather than passing the wrong check.
TENANT_REFS: Dict[str, Callable[[Any, Any], Select]] = {
    "alarm_id": _direct(Alarm),
    "asset_id": _direct(Asset),
    "assigned_owner_id": _direct(User),
    "assigned_to": _direct(User),
    "board_id": _direct(TaskBoard),
    "carrier_id": _direct(Carrier),
    "column_id": _via_board(TaskColumn),
    "command_id": _direct(Command),
    "current_trailer_id": _direct(YardTrailer),
    "dock_door_id": _direct(DockDoor),
    "driver_id": _direct(Driver),
    "jockey_driver_id": _direct(Driver),
    "operation_id": _via_asset(Operation),
    "parent_task_id": _via_board(Task),
    "registry_id": _direct(ActionableRegistry),
    "related_task_id": _via_board(Task),
    "route_id": _direct(Route),
    "shipment_id": _direct(Shipment),
    "specific_assignee_id": _direct(User),
    "target_board_id": _direct(TaskBoard),
    "target_column_id": _via_board(TaskColumn),
    "trailer_id": _direct(YardTrailer),
    "workcell_id": _direct(Workcell),
}


#: Id-shaped fields that are NOT a tenant-owned reference, each with the reason. Every
#: entry here is a claim the guard re-checks; "it looked fine" is not one of them.
NOT_TENANT_SCOPED: Dict[str, str] = {
    "asset_type_id": (
        "`asset_types` is a GLOBAL catalogue with no organization_id — see "
        "`GET /assets/types/`, which serves it to every tenant. `assets.py` already argues "
        "this at length: a bad id here is a foreign-key violation that `core/errors.py` "
        "renders as a 400 naming the column, which is more specific than a 404."
    ),
    "assigned_team_id": (
        "There is no teams table. `actionable_registries.assigned_team_id` is a bare "
        "`UUIDString()` with no foreign key, so there is nothing to verify it against — "
        "registering it would mean inventing an owner. Recorded rather than guessed at."
    ),
    "eld_device_id": (
        "`drivers.eld_device_id` is a `String(100)` vendor device identifier, not a row in "
        "this database. It names hardware in the ELD provider's system."
    ),
    "job_id": (
        "`operations.job_id` is a `String(255)` from the MES/ERP that scheduled the work, "
        "not a row here."
    ),
    "organization_id": (
        "A DIFFERENT defect class, already closed and guarded. A tenant id in a request "
        "body is never read — it is taken from the token — and "
        "`test_no_handler_takes_its_tenant_from_the_body.py` enforces that. Verifying it "
        "here would imply the body's value is used."
    ),
    "source_id": (
        "`data_correlations.source_id` is polymorphic: the table it points into is named by "
        "a sibling `source_type` column, so there is no single owner to join to. Its route "
        "must check against the resolved type; see the register entry."
    ),
    "target_id": (
        "Polymorphic, paired with `target_type`. Same reasoning as `source_id`."
    ),
    "task_id": (
        "`TaskCommentCreate.task_id` is declared on a model no route consumes — the comment "
        "routes take the task id from the PATH, where `get_organization_task` verifies it."
    ),
}


async def verify_refs(
    session: AsyncSession,
    organization_id: Any,
    supplied: Mapping[str, Any],
    *,
    only: Optional[Iterable[str]] = None,
    exclude: Iterable[str] = (),
) -> None:
    """Refuse any registered reference in `supplied` the organisation does not own.

    `supplied` should come from `model_dump(exclude_unset=True)`, so a field the caller did
    not send is not checked and an explicit `null` still unlinks.

    `only` narrows to a named set — for a handler that validates part of a body itself and
    wants no second opinion. `exclude` skips a field this route legitimately treats
    differently, and every use of it should say why at the call site.
    """
    fields = set(TENANT_REFS) if only is None else (set(only) & set(TENANT_REFS))
    for field in sorted(fields - set(exclude)):
        value = supplied.get(field)
        if value is None:
            continue
        query = TENANT_REFS[field](str(value), str(organization_id))
        try:
            owned = (await session.execute(query)).first()
        except (DBAPIError, StatementError):
            # A malformed id is an id nobody owns. Postgres refuses to compare a non-UUID
            # string to a uuid column, and that must read as "not found" rather than
            # escape as a 500 — several of these columns are TEXT, so it is reachable.
            await session.rollback()
            owned = None
        if owned is None:
            raise HTTPException(status_code=404, detail=f"{field} not found")
