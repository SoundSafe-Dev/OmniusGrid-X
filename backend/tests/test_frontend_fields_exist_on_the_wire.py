"""A TypeScript field the backend never emits is a value somebody invented.

`MaintenanceSchedule.currentMileage` was the entry point: declared on the type, supplied by
the mock fixtures, rendered by the panel as "Mileage: 128,500", and produced by nothing on
the server. The client's adapter filled it from `dueMileage` — the odometer at which the
service falls DUE — so the panel showed the wrong mileage under a label a technician reads
as the vehicle's present one, or "0" when neither existed.

Once one is found the question generalises, and it is mechanically answerable: **which
fields does the frontend declare and read that no backend source produces?**

WHAT THE VOCABULARY IS. Every string key in a dict literal anywhere under `app/`, every
Pydantic/SQLAlchemy attribute name, every `Field(alias=…)`, each also in camelCase — plus
the values in the frontend casing seam's `inAliases` maps, which legitimately rename a
field on the way in (`checkInAt` -> `checkedInAt`) and would otherwise be reported as
missing. A field absent from all of that has no producer.

WHAT THIS TEST IS FOR. Not to drive the list to zero — several entries are honest (a value
computed client-side, a field a future endpoint will carry). It is to stop the list
GROWING. A new name here means someone has declared a field with no source, and the next
step is always one of three: rename it to what the wire calls it, delete it, or make the
server send it. `currentMileage` needed the second; `priority` on a maintenance schedule
needed the third (migration 054).

FOUR FINDINGS SO FAR:

  * `MaintenanceSchedule.currentMileage` — the due odometer shown as the current one.
  * `RepairOrder.workOrderNumber` — the first eight characters of a UUID, shown as the
    heading a technician would quote to a vendor.
  * `MaintenanceCosts.costPerVehicle` / `.upcomingEstimated` — hardcoded zeros, the second
    in a highlighted box reading "Upcoming (Est.) $0".
  * `Asset.isInMaintenance` — the sharpest of the four, because everything AROUND it
    worked. Migration 053 added `assets.maintenance_mode`, the admin endpoint writes it,
    and the tactical engine reads it before dispatching a control command — but
    `AssetResponse` never declared the field, so FastAPI dropped it from every response
    and nothing in the product could show which assets were out of service. The frontend's
    name for it had never been sent by any endpoint under any spelling. Adding a column is
    not the same as exposing it; see `test_maintenance_mode_reaches_the_client.py`.

Its sibling `test_qualifiers_reach_the_frontend.py` asks the mirror question: which fields
does the BACKEND send that no frontend file reads? Between them the contract is checked in
both directions.
"""

from __future__ import annotations

import ast
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "app"
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"

COMMENT = re.compile(r"/\*[\s\S]*?\*/|(?<![:'\"`])//[^\n]*")
INTERFACE = re.compile(r"export interface (\w+)\s*\{([^}]*)\}", re.S)
FIELD = re.compile(r"^\s*(\w+)\??\s*:", re.M)
ALIAS_ENTRY = re.compile(r"^\s*(\w+):\s*'([^']+)',", re.M)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w[:1].upper() + w[1:] for w in rest)


def _wire_vocabulary() -> set[str]:
    """Every name the backend can put on the wire, in both casings."""
    vocab: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a syntax error fails elsewhere, loudly
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        vocab.add(key.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                vocab.add(node.target.id)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        vocab.add(target.id)
            elif isinstance(node, ast.keyword) and node.arg in (
                "alias",
                "serialization_alias",
            ):
                if isinstance(node.value, ast.Constant) and isinstance(
                    node.value.value, str
                ):
                    vocab.add(node.value.value)
    vocab |= {_camel(v) for v in vocab}
    # The casing seam renames some fields beyond casing, so an alias VALUE is a name the
    # wire really does deliver even though no Python file spells it.
    transform = FRONTEND / "api" / "transform.ts"
    if transform.exists():
        vocab |= {m.group(2) for m in ALIAS_ENTRY.finditer(transform.read_text())}
    return vocab


def _component_source() -> str:
    """Everything that READS a field — pages, components and clients, minus the types
    themselves (a declaration is not a use) and the mocks (a fixture agreeing with a type
    is exactly the circularity this sweep exists to break)."""
    parts = []
    for path in list(FRONTEND.rglob("*.tsx")) + list(FRONTEND.rglob("*.ts")):
        if ".test." in path.name or "/mocks/" in str(path) or "/types/" in str(path):
            continue
        parts.append(COMMENT.sub(" ", path.read_text()))
    return "\n".join(parts)


def _declared_but_unsent() -> set[str]:
    vocab = _wire_vocabulary()
    source = _component_source()
    found = set()
    for path in (FRONTEND / "types").glob("*.ts"):
        text = COMMENT.sub(" ", path.read_text())
        for match in INTERFACE.finditer(text):
            interface, body = match.group(1), match.group(2)
            for field in FIELD.finditer(body):
                name = field.group(1)
                if name in vocab:
                    continue
                if re.search(rf"\.{name}\b", source):
                    found.add(f"{interface}.{name}")
    return found


#: Entries present when this guard was written. The list may SHRINK freely; anything new
#: is a field somebody declared with no producer, and `test_no_new_unsent_fields` says so.
#: Not an approval — a baseline. Each remaining entry still needs the same judgement:
#: rename it, delete it, or make the server send it.
#:
#: A LITERAL, NOT `_declared_but_unsent()`. The first version of this file computed the
#: baseline at import time from the same tree it then compared against, so the difference
#: was empty by construction and `test_no_new_unsent_fields` could never fail. A guard
#: that derives its own expected value from its own input is not a guard; it is a very
#: expensive way of asserting that a set equals itself.
BASELINE = {
    # `Asset.isInMaintenance` and `AssetUpdate.isInMaintenance` were HERE, and are the
    # fourth finding: the name was declared as a required boolean, populated only by the
    # mock fixtures, and sent by no endpoint under any spelling — because `AssetResponse`
    # did not carry the column at all. Fixed by declaring `maintenance_mode` on the schema
    # and renaming the TypeScript field to `maintenanceMode`, which is what the casing seam
    # then delivers. Re-pinned rather than left in place: a baseline that still lists a
    # fixed entry quietly loses its edge.
    "AgentRolloutCreate.all",
    "Carrier.contactEmail",
    "Carrier.contactPhone",
    "CloudGatewayStatus.lastConnectedAt",
    "DetentionAlert.excessMinutes",
    "DetentionAlert.trailerLicensePlate",
    "DockAppointment.driverPhone",
    "DockAppointment.trailerLicensePlate",
    "DockAppointment.workcellName",
    "DockDoor.estimatedReleaseAt",
    "DockDoor.trailerLicensePlate",
    "DockDoor.workcellName",
    "Driver.currentShipmentId",
    "Driver.currentVehicleId",
    "Driver.geoTabDeviceId",
    "ErrorListParams.sort",
    "GeofenceAlert.alertType",
    "GeofenceAlert.geofenceId",
    "GeofenceAlert.geofenceName",
    "GeofenceAlertExtended.alertType",
    "GeofenceAlertExtended.geofenceId",
    "GeofenceAlertExtended.geofenceName",
    "HOSViolationAlert.currentLocation",
    "HOSViolationAlert.hoursRemaining",
    "Location.contactEmail",
    "Location.contactPhone",
    "LogisticsOverview.todayAppointments",
    "LogisticsOverview.vehiclesIdle",
    "MaintenanceCosts.costPerVehicle",
    "MaintenanceCosts.monthlyAverage",
    "MaintenanceCosts.monthlyBreakdown",
    "MaintenanceCosts.totalYTD",
    "MaintenanceCosts.upcomingEstimated",
    "MaintenanceSchedule.assignedTechnician",
    "RepairOrder.actualCost",
    "RepairOrder.assignedTechnician",
    "RepairOrder.issueDescription",
    "RepairOrder.laborHours",
    "RepairOrder.partsUsed",
    "RepairOrder.reportedDate",
    "RepairOrder.workOrderNumber",
    "Shipment.currentLocation",
    "Shipment.estimatedDelivery",
    "StrategicRecommendation.costSavings",
    "StrategicRecommendation.timeSavings",
    "Vehicle.currentLocation",
    "Vehicle.currentShipmentId",
    "Vehicle.geoTabDeviceId",
    "YardMove.trailerLicensePlate",
    "YardTrailer.contents",
    "YardTrailer.driverPhone",
}


class TestTheSweepIsNotVacuous:
    def test_it_reads_both_sides(self):
        # If either walk stopped matching, every field would look present (or absent) and
        # this file would pass while inspecting nothing.
        assert len(_wire_vocabulary()) > 500
        assert len(_component_source()) > 100_000

    def test_a_field_the_backend_emits_is_not_reported(self):
        """`organizationId` is emitted all over the backend. If the vocabulary missed it,
        the sweep would report half the frontend."""
        assert "organizationId" in _wire_vocabulary()
        assert "organization_id" in _wire_vocabulary()

    def test_an_invented_field_would_be_reported(self):
        """The positive control, run against a name chosen to exist nowhere. Without it a
        clean result says nothing about the sweep — method rule 26."""
        vocab = _wire_vocabulary()
        assert "totallyInventedFieldNobodyEmits" not in vocab

    def test_the_casing_seam_aliases_are_credited(self):
        """`checkedInAt` is produced by `YARD_ALIASES`, not by any Python file. Without
        the alias maps in the vocabulary the sweep reports it and half a dozen others
        that work exactly as designed."""
        assert "checkedInAt" in _wire_vocabulary()


class TestTheListDoesNotGrow:
    def test_no_new_unsent_fields(self):
        """A new name here means a field was declared with no producer. Rename it to what
        the wire calls it, delete it, or make the server send it — the three fixes the
        three findings so far each needed."""
        new = sorted(_declared_but_unsent() - BASELINE)
        assert not new, (
            "these TypeScript fields are read by a component and emitted by nothing on "
            "the server, so they are undefined at runtime or filled in by an adapter:\n  "
            + "\n  ".join(new)
        )

    def test_the_baseline_is_not_silently_stale(self):
        """If the list shrinks, the baseline should be re-pinned so the guard keeps its
        edge. Reported as a skip rather than a failure — shrinking is the good direction
        and must never block a fix."""
        import pytest

        fixed = sorted(BASELINE - _declared_but_unsent())
        if fixed:
            pytest.skip(f"baseline can be tightened; these are gone: {fixed}")


class TestTheThreeFindingsStayFixed:
    """Pinned individually, because the general guard only stops the list growing — it
    would not notice one of these coming back if another were removed at the same time."""

    def test_current_mileage_is_gone(self):
        assert "MaintenanceSchedule.currentMileage" not in _declared_but_unsent()
        text = (FRONTEND / "types" / "logistics.ts").read_text()
        assert "currentMileage" not in text, (
            "a schedule knows when service is DUE; it does not know the vehicle's "
            "present odometer"
        )

    def test_the_work_order_number_is_not_synthesised(self):
        # COMMENTS STRIPPED FIRST. The first version of this assertion failed against the
        # fixed code, because the comment explaining the fix quotes the very expression it
        # forbids. Method rule 14, and this file is where it was written down — a
        # substring match on source is satisfied by prose, and prose about a defect
        # gathers exactly around the defect.
        source = COMMENT.sub(" ", (FRONTEND / "api" / "maintenance.ts").read_text())
        assert ".slice(0, 8)" not in source, (
            "workOrderNumber was eight characters of a UUID, shown as the heading a "
            "technician would quote to a vendor"
        )

    def test_the_cost_figures_are_not_hardcoded(self):
        source = (FRONTEND / "api" / "maintenance.ts").read_text()
        source = COMMENT.sub(" ", source)
        assert "costPerVehicle: 0" not in source
        assert "upcomingEstimated: 0" not in source
        assert "/ 12" not in source, (
            "monthlyAverage was ytd/12 regardless of how many months had elapsed"
        )
