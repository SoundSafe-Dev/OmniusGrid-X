"""A TypeScript field the backend never emits is a value somebody invented.

`MaintenanceSchedule.currentMileage` was the entry point: declared on the type, supplied by
the mock fixtures, rendered by the panel as "Mileage: 128,500", and produced by nothing on
the server. The client's adapter filled it from `dueMileage` — the odometer at which the
service falls DUE — so the panel showed the wrong mileage under a label a technician reads
as the vehicle's present one, or "0" when neither existed.

Once one is found the question generalises, and it is mechanically answerable: **which
fields does the frontend declare and read that no backend source produces?**

WHAT THE VOCABULARY IS. Every string key in a dict literal anywhere under `app/`, every
Pydantic/SQLAlchemy attribute name, every `Field(alias=…)`, every endpoint PARAMETER (a
`*Params` interface describes a request), every constant-string subscript assignment
(`row["carrierName"] = …` is a producer too), each also in camelCase — plus the values in the
frontend casing seam's `inAliases` maps, which legitimately rename a field on the way in
(`checkInAt` -> `checkedInAt`) and would otherwise be reported as missing. A field absent from
all of that has no producer.

The last two forms were added after the sweep was wrong about them: parameters, because it was
comparing what the backend CONSUMES against what it PRODUCES; subscripts, because a field the
server had started sending and the panel had started rendering stayed on the baseline. Each
widening carries a positive and a negative control below — a vocabulary that absorbs names too
freely stops reporting anything, which is the same failure as one that reads nothing.

WHAT THIS TEST IS FOR. Not to drive the list to zero — several entries are honest (a value
computed client-side, a field a future endpoint will carry). It is to stop the list
GROWING. A new name here means someone has declared a field with no source, and the next
step is always one of three: rename it to what the wire calls it, delete it, or make the
server send it. `currentMileage` needed the second; `priority` on a maintenance schedule
needed the third (migration 054).

THE FINDINGS SO FAR — the count is deliberately not written here (rule 44):

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
  * `GeofenceAlert.alertType` / `.geofenceId` / `.geofenceName` — the endpoint and the client
    had drifted to entirely different names, so the panel's ternary fell through to its last
    branch and every alert, including a routine authorised entry, read "Violation".
  * `DockDoor.trailerLicensePlate` and friends — the first entry needing two DIFFERENT fixes
    in one cluster: the plate exposed through a join that existed, `workcellName` deleted
    because the relationship does not.
  * `RepairOrder.assignedTechnician` and six siblings — the sharpest kind again:
    `repair_orders.vendor`, who actually did the repair, was sent on every response and shown
    NOWHERE, beside a "Tech:" line that could never populate.
  * `MaintenanceCosts.*` — the first cluster fixed by the THIRD option. Four figures the
    client manufactured (one as `ytd / 12`, two as hardcoded zeros, one a chart with no data)
    are all computable from columns the endpoint already had.
  * `Vehicle.currentLocation` and the position cluster — one group needing all three fixes:
    a rename that woke a dead panel, two reverse lookups the server now resolves, and a
    "Current Location (GeoTab)" card for a position nothing records.

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
                    # SUBSCRIPT ASSIGNMENT IS A PRODUCER. `row["currentVehicleId"] = ...` puts
                    # a name on the wire exactly as a dict literal does, and this walk saw only
                    # the literal form. `transportation.py` builds several responses by
                    # validating a model and then adding derived keys this way — carrierName,
                    # the HOS remaining hours, the driver's vehicle and shipment — so every one
                    # of those was invisible to the vocabulary and would be reported as
                    # unsourced the moment a client declared it.
                    #
                    # Found by fixing `Driver.currentVehicleId`: the server sent it, the panel
                    # rendered it, and the sweep still listed it as having no producer.
                    elif isinstance(target, ast.Subscript) and isinstance(
                        target.slice, ast.Constant
                    ):
                        if isinstance(target.slice.value, str):
                            vocab.add(target.slice.value)
            # FUNCTION PARAMETERS TOO. A `*Params` interface on the frontend describes a
            # REQUEST, and the names a request may carry are the endpoint's own parameters —
            # which are `ast.arg` nodes, not `AnnAssign`, so the walk above never saw them.
            # `ErrorListParams.sort` was reported as unsourced while
            # `list_errors(..., sort: Literal["count", "last_seen", "first_seen"] = "count")`
            # accepts it, and the client sends it correctly. The sweep was conflating what
            # the backend PRODUCES with what it CONSUMES; a request field checked against a
            # response vocabulary is a false positive by construction.
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                    vocab.add(arg.arg)
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
    # A FALSE POSITIVE OF THIS SWEEP, kept because the fix costs more than the finding.
    # `AgentRolloutCreate` describes a REQUEST, and `_resolve_targets` branches on
    # `selector.get("all") is True`, so `all` is a name the backend really does read — it just
    # lives inside a free-form dict rather than in a signature, which is where the parameter
    # walk above looks. Crediting the argument of every `.get("literal")` call would remove it
    # and add 425 names reachable ONLY that way: a third of the vocabulary's discriminating
    # power spent on one entry. Measured before deciding, and declined;
    # `test_the_vocabulary_stays_narrow_enough_to_report_anything` keeps it declined.
    "AgentRolloutCreate.all",
    # The four contact entries (Carrier and Location) were HERE, and are the ninth
    # finding — a DELETE, not an expose. `carriers` has no contact_phone or
    # contact_email column: the table carries DOT/MC numbers, C-TPAT and insurance
    # dates, safety rating, CSA score, SCAC and operating authority, and no way to
    # reach anybody. The carrier card rendered a "Contact" heading above two empty
    # lines for every row, and both fields were declared REQUIRED.
    #
    # Removed rather than filled with "not recorded", which would be permanent noise on
    # every row. Carrier contact details are collected nowhere in this product — a gap
    # in the schema, not something a panel or a type can paper over. The `Location`
    # pair went with them: nothing rendered those either.
    # `DockDoor.estimatedReleaseAt` was HERE, and came out of the per-interface audit
    # rule 34 says this sweep cannot do. `DockDoor` declared five fields `dock_doors`
    # does not have, and only this one was reported — the others (`supportedEquipment`,
    # `hasLoadingEquipment`, `maxWeightCapacity`, `currentAppointmentId`) name columns
    # that exist on OTHER tables, and a global vocabulary credits them.
    #
    # It rendered "Release: HH:MM", a prediction nothing produces. `last_occupied_at`
    # exists and means something different — when the door was last occupied, a fact
    # about the past — so the card shows that instead. Mapping one onto the other would
    # have been the `currentMileage` defect exactly: the right number, the wrong label.
    # A schema-vs-table assertion in test_yard_trailer_plate_is_resolved.py now keeps
    # DockDoorResponse honest.
    # The six yard entries (trailerLicensePlate x4, workcellName x2) were HERE, and
    # are the sixth finding — the one that needed TWO of the three fixes:
    #   * `trailerLicensePlate` was EXPOSED. Both dock_doors.current_trailer_id and
    #     dock_appointments.trailer_id reference yard_trailers, where the plate lives,
    #     so the door card printed an empty line where the trailer at the dock should
    #     be named. Resolved in one batched query per list.
    #   * `workcellName` was DELETED. dock_doors has no workcell relationship of any
    #     kind, so nothing could ever have fed it.
    # Pinned by tests/test_yard_trailer_plate_is_resolved.py.
    # `ErrorListParams.sort` was HERE and was a FALSE POSITIVE of this sweep, not a
    # defect: `list_errors` accepts `sort` and the client sends it correctly. The
    # vocabulary collected `AnnAssign` targets but not function PARAMETERS, so every
    # query param an endpoint accepts was invisible — and a `*Params` interface
    # describes a REQUEST, whose valid names are exactly those parameters. The sweep
    # was checking what the backend CONSUMES against what it PRODUCES. Fixed in
    # `_wire_vocabulary`; the entry is gone because it was never real.
    # `Driver.geoTabDeviceId` and `Vehicle.geoTabDeviceId` were HERE, and are the
    # eighth finding — one field name hiding TWO different defects:
    #   * vehicles DO have one, `vehicles.geotab_device_id`, but the casing seam
    #     produces `geotabDeviceId` with a lower-case t, so the declared name matched
    #     nothing and the detail row never rendered;
    #   * drivers do NOT. The column is `eld_device_id` — an ELD, a different system
    #     with different compliance meaning — so the panel offered a "GeoTab Device ID"
    #     row that could never populate while the id the driver DOES have was sent and
    #     never displayed.
    # Both rows are conditional, so neither made a false claim; they were simply never
    # there, which is why nothing reported them.
    # The six `GeofenceAlert*` entries were HERE, and are the fifth finding: the
    # endpoint sent zoneId/eventType/createdAt while the client read
    # geofenceId/alertType/timestamp, with no overlap. `alertType` undefined made the
    # panel's ternary fall through to its last branch, so EVERY alert — including a
    # routine authorised entry — rendered as "Violation". Fixed on the producer side,
    # because nothing consumed the names it was sending.
    # Pinned by tests/test_geofence_alert_names_match_the_client.py.
    # `todayAppointments` STAYS, and is the honest kind: `YardManagement` computes it
    # client-side by filtering the appointments list. The sweep cannot tell a local
    # computation from a fabrication, which is why the list is a baseline and not a
    # defect count.
    # The eight position/assignment entries across Vehicle, Driver, Shipment and
    # HOSViolationAlert were HERE, and are the thirteenth finding — one cluster, all three
    # fixes, plus a hole in this sweep's own vocabulary.
    #
    #   * `Vehicle.currentLocation` — RENAMED. The column is `vehicles.last_location` and the
    #     serializer emits `lastLocation` with exactly this shape, so every location block on
    #     the vehicle panel was dead against a value arriving on every response.
    #   * `Driver.currentVehicleId` / `.currentShipmentId` — SERVED. Neither is a column on
    #     `drivers` and neither should be: a vehicle names its driver and a shipment names its
    #     driver, so the driver's side of both is a reverse lookup. Two batched queries.
    #   * `Shipment.currentLocation` — DELETED, with a "Current Location (GeoTab)" card. A
    #     shipment has no position; the nearest real one is the driver's vehicle's, two hops
    #     away, and stale the moment they change vehicle.
    #   * `Shipment.estimatedDelivery` — DELETED. Nothing predicts a delivery time, so the
    #     late-running warning it drove never fired.
    #   * `HOSViolationAlert.*` — the whole INTERFACE deleted. One occurrence in the frontend:
    #     its own declaration. A type nothing constructs is a plan, not a contract.
    #
    # `Driver.lastLocation` went with them though the sweep never reported it — `drivers` has
    # no position column, and the global vocabulary credited the name from `vehicles`. Rule
    # 34's blind spot, found by auditing the interface against its own table.
    #
    # AND THE SWEEP COULD NOT SEE THE FIX. The two Driver ids stayed listed after the server
    # started sending them, because `_wire_vocabulary` collected dict-literal keys and not
    # `row["name"] = ...`. Widened, with both a positive and a negative control above.
    # The four yard entries were HERE, and are the fourteenth finding — two joins and two
    # deletions, plus a whole interface that had drifted from its endpoint.
    #
    #   * `YardTrailer.driverPhone` and `DockAppointment.driverPhone` — SERVED. Both tables
    #     carry `driver_id` and `drivers.phone` is where the number lives, so this is the same
    #     join as `trailerLicensePlate` one finding earlier. It is the number an operator calls
    #     about a trailer sitting on the yard, rendered in three places and sent by nothing.
    #   * `YardTrailer.contents` — DELETED, with `poNumber` beside it. `yard_trailers` records
    #     what the trailer IS — type, seal, weight, temperature setpoint — and nothing about
    #     what is inside it. The inventory table printed a dash on every row under a column
    #     headed "Contents"; it shows the seal number now, which exists.
    #   * `DetentionAlert.excessMinutes` — RENAMED, and it was the only one of that
    #     interface's TWELVE fields the sweep could report: `carrierName`, `location` and
    #     `estimatedCost` are all named by other tables, so the global vocabulary credits them.
    #     Rule 34 again. The banner appears only when a trailer is costing money and it read
    #     "<id> • " above "$" and "N/A excess". The numbers were being sent under the
    #     endpoint's names; the carrier, yard location and plate were not sent at all and are
    #     real columns on the row the loop already held.
    #
    # `YardTrailer.lastLocation` went too, unreported for the same reason as
    # `Driver.lastLocation` — credited from `vehicles.last_location`, a different table. It
    # gated a "Current GPS Location (GeoTab)" card behind a condition that was never true.
    # Pinned by test_yard_driver_phone_is_resolved_realdb.py and
    # test_detention_alert_names_the_trailer_realdb.py.
    # The last four were HERE, and are the fifteenth finding — three interfaces that had each
    # drifted from their endpoint, reported by ONE field apiece because the rest of their names
    # exist elsewhere in the tree (rule 34, for the fourth time).
    #
    #   * `CloudGatewayStatus` declared ELEVEN fields — an uptime, a certificate expiry, a
    #     last-sync time and a nested `egressStats` of five — and `cloud_gateway.get_stats()`
    #     returns four keys. The page had already worked this out and declared its OWN local
    #     interface with the four real ones, under a comment saying so; that left the EXPORTED
    #     type wrong, so the api client still promised eleven and only the mock could deliver
    #     them. One type now, matching the wire.
    #   * `MaintenanceSchedule.assignedTechnician` — DELETED. `maintenance_schedules` has no
    #     technician column and, unlike `repair_orders`, no vendor either: a schedule records
    #     what is due and when, not who will do it.
    #   * `StrategicRecommendation.expectedImpact` — the grid named three keys and the engine
    #     sends a different set per recommendation type (`cost_reduction`, `throughput_gain`,
    #     `rul_extension_days`). `costSavings` is `costReduction` on the wire, so the cost
    #     figure never appeared on a card whose whole purpose is justifying an approval, and
    #     `timeSavings` is produced by nothing. The dict is free-form by design, so the card
    #     renders what arrives and labels it, rather than naming slots in advance.
    "LogisticsOverview.todayAppointments",
    # `LogisticsOverview.vehiclesIdle` was HERE, and is the seventh finding. The fleet
    # card promised totalVehicles/vehiclesMoving/vehiclesIdle/avgSpeed/
    # totalDistanceToday/fuelConsumedToday; /geotab/fleet/summary sends total_devices/
    # active_devices/total_drivers/drivers_on_duty/total_miles_today/
    # average_fuel_efficiency. NOT ONE FIELD OVERLAPPED, so all six figures on a card
    # headed "Fleet Status (GeoTab Live)" were undefined — two of them printed beside
    # bare units, " mph" and " mi". The client now names its fields after the wire, so
    # there is no adapter to drift and nothing here to report.
    # Pinned by the fleet-card block in TransportationManagement.test.tsx.
    # The five `MaintenanceCosts.*` entries were HERE, and are the twelfth finding — the
    # only one so far fixed by the THIRD option, making the server send it. Four of the
    # five were figures the client manufactured: `monthlyAverage` as `ytd / 12` (computed
    # in January as readily as in December), `costPerVehicle` and `upcomingEstimated` as
    # hardcoded zeros, and `monthlyBreakdown` as a required array nothing sent, so the
    # trend chart drew nothing. An earlier pass removed the fabrications and left four
    # blank rows, which was right and was not the end of the job.
    #
    # Every one is a fact about data `/maintenance/costs` already had or could reach with
    # one count, so it computes them: spend per elapsed month, YTD over months elapsed,
    # the sum of `maintenance_schedules.estimated_cost` on work not yet done, and YTD over
    # the fleet size. The endpoint had been passing `[]` for schedules — the costs of work
    # not yet done live there.
    #
    # `totalYTD` was the fifth and a different case: real data under a name no endpoint
    # sends. RENAMED to `ytdTotal` — rule 35.
    #
    # NONE-VERSUS-ZERO runs through all of it. An empty fleet has no cost per vehicle;
    # outstanding work nobody costed has no estimate; a month with no repairs cost zero,
    # and that one IS a number. Pinned by
    # test_maintenance_costs_are_computed_not_invented.py.
    # The seven `RepairOrder.*` entries were HERE, and are the eleventh finding — the
    # largest single cluster the sweep had left. `repair_orders` has thirteen columns and
    # `_order_out` emits eleven of them; the TypeScript described a richer object that no
    # endpoint produces and no migration plans:
    #
    #   * `assignedTechnician` — the sharpest, because everything around it worked.
    #     `repair_orders.vendor`, who actually did the repair, was sent on every response
    #     and rendered NOWHERE, while the card offered a "Tech:" line that could never
    #     populate. Same shape as the `geoTabDeviceId` finding: a row that cannot fill
    #     itself standing next to the value it should have shown.
    #   * `workOrderNumber` — deleted rather than left optional. Nothing in this product
    #     issues one, and an optional field for it is a standing invitation to synthesise
    #     it again, which is exactly what the mock `createRepairOrder` was still doing.
    #   * `actualCost` — a second cost on a table with one `cost` column, which IS the
    #     actual cost. Two names for one number invites populating both.
    #   * `laborHours`, `partsUsed` (and its `PartUsed` shape) — no columns, no tables.
    #   * `issueDescription`, `reportedDate` — real data under invented names, filled by the
    #     adapter from `title` and `openedAt`. RENAMED, not deleted: rule 35.
    #
    # `vendor` and `category` are now displayed, so this cluster also shortened the mirror
    # sweep's list. Pinned by MaintenancePanel.test.tsx.
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

    def test_a_key_added_by_subscript_assignment_is_credited(self):
        """`row["carrierName"] = ...` puts a name on the wire exactly as a dict literal does,
        and the walk originally saw only the literal form. `transportation.py` builds several
        responses by validating a model and then adding derived keys this way, so all of them
        were invisible — found when `Driver.currentVehicleId` stayed on the baseline after the
        server started sending it and the panel started rendering it.

        `carrierName` is asserted rather than one of the two that prompted this, so the check
        does not merely restate the change that motivated it."""
        assert "carrierName" in _wire_vocabulary()

    def test_the_vocabulary_stays_narrow_enough_to_report_anything(self):
        """A DETECTOR CAN BE WIDENED UNTIL IT REPORTS NOTHING, and each widening looks like a
        bug fix on its own.

        Crediting the argument of every `.get("literal")` call would have removed
        `AgentRolloutCreate.all` — genuinely a false positive, since `_resolve_targets`
        branches on `selector.get("all") is True` and a `*Create` interface describes a
        REQUEST. It was measured before being accepted: 425 names are reachable ONLY that way,
        so the fix costs a third of the vocabulary's discriminating power to remove one
        baseline entry. Declined, and the entry says so instead.

        This asserts the vocabulary has not since acquired them. The number is a floor on
        precision, not a target."""
        vocab = _wire_vocabulary()
        # Keys read from request bodies by `.get()` and named nowhere else in the tree.
        get_only = {"/aggregates", "/alarms/trend", "/cache-hit-ratio"}
        leaked = sorted(get_only & vocab)
        assert not leaked, (
            f"the vocabulary has been widened to credit `.get()` keys: {leaked}. That removes "
            "one baseline entry and adds ~425 names the sweep will then never report."
        )

    def test_the_subscript_form_does_not_credit_arbitrary_indexing(self):
        """The control on the widening. Only a CONSTANT STRING subscript is a wire name; a
        variable index (`row[key] = ...`) names nothing in particular, and crediting whatever
        it resolves to would let the vocabulary absorb names at random and quietly stop
        reporting anything."""
        import ast as _ast

        tree = _ast.parse("row[some_variable] = 1\nrow[0] = 2\n")
        credited = []
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Assign):
                for target in node.targets:
                    if isinstance(target, _ast.Subscript) and isinstance(
                        target.slice, _ast.Constant
                    ):
                        if isinstance(target.slice.value, str):
                            credited.append(target.slice.value)
        assert credited == [], f"a non-string subscript was credited: {credited}"

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
        # COMMENTS STRIPPED. This assertion has now failed twice against FIXED code, because
        # prose about a defect gathers precisely around the defect: first the comment
        # explaining the deletion, then a comment in the DockDoor audit citing
        # `currentMileage` as the precedent for not mapping `last_occupied_at` onto
        # `estimatedReleaseAt`. Method rule 14, three times in one file — the lesson is that
        # ANY substring assertion over source must strip comments first, not that this
        # particular one needed it.
        assert "MaintenanceSchedule.currentMileage" not in _declared_but_unsent()
        text = COMMENT.sub(" ", (FRONTEND / "types" / "logistics.ts").read_text())
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


# ---------------------------------------------------------------------------------------
# The third quadrant: declared, no producer, AND NOT YET READ (FS-367).
#
# `_declared_but_unsent` requires `re.search(rf"\.{name}\b", source)` — the field must be
# READ somewhere. That scoping is deliberate and right for that guard: a field nobody
# renders is doing no visible harm today, and crediting every declaration would bury the
# signal.
#
# But it is exactly why THREE separate sets of phantom fields survived this file:
#
#   * `CloudGatewayStatus` — eleven fields, removed with a comment saying the interface
#     "described a different service".
#   * `StrategicRecommendation` — seven, and this one WAS eventually read: the Decision
#     History pane got built on them, and rendered `0 Approved` forever (FS-366).
#   * `TacticalEngineStatus` + `MLOpsStatus` — six, plus the whole `ModelDeployment`
#     interface, all supplied by `mockApi` including two populated deployment records
#     with rollback timestamps (FS-367).
#
# The pattern is the same each time and the ORDER is the point: the field is declared, the
# mock supplies it, and it sits harmless until somebody builds a pane on it. `VITE_USE_MOCK`
# defaults to true, so that pane looks finished in development and is blank against the real
# API. StrategicRecommendation is the completed cycle — the other two were caught mid-way.
#
# So this counts the fields still waiting for a first reader. It is a COUNT ratchet rather
# than a name baseline because the population is large and mostly benign: value objects
# (`GeoLocation.altitude`), request shapes, and fields a future endpoint will carry. Driving
# it to zero is not the goal; noticing it GROW is.
# ---------------------------------------------------------------------------------------

#: Measured 2026-08-01, after removing the six engine fields in FS-367. LOWER THIS as
#: phantom declarations are removed; never raise it. A rise means someone declared a field
#: with no producer — the first half of the cycle above, and the cheapest moment to stop it.
MAX_UNREAD_PHANTOM_FIELDS = 57

#: Interfaces describing a REQUEST rather than a response. A field here is something the
#: client sends, so "no backend producer" is the normal case and not a defect. `*Params` is
#: already excluded from the sweep above for the same reason.
_REQUEST_SUFFIXES = ("Params", "Request", "Create", "Update", "Filters", "Credentials")


def _declared_unread_and_unsent() -> set[str]:
    vocab = _wire_vocabulary()
    source = _component_source()
    found = set()
    for path in (FRONTEND / "types").glob("*.ts"):
        text = COMMENT.sub(" ", path.read_text())
        for match in INTERFACE.finditer(text):
            interface, body = match.group(1), match.group(2)
            if interface.endswith(_REQUEST_SUFFIXES):
                continue
            for field in FIELD.finditer(body):
                name = field.group(1)
                if name in vocab:
                    continue
                if re.search(rf"\.{name}\b", source):
                    continue  # read somewhere — that is `_declared_but_unsent`'s job
                found.add(f"{interface}.{name}")
    return found


class TestTheTrapsForTheNextPage:
    def test_the_two_quadrants_do_not_overlap(self):
        """They partition the same population by whether anything reads the field. An
        overlap would mean one of the two `re.search` conditions has drifted, and the pair
        would be double-counting rather than dividing."""
        assert not (_declared_but_unsent() & _declared_unread_and_unsent())

    def test_it_finds_the_unread_ones_at_all(self):
        """Vacuity guard. If the interface or field regex drifts this returns nothing and
        the ratchet below passes at zero — the failure every sweep in this repo has a rule
        about, and one this session hit three times in other tools."""
        assert len(_declared_unread_and_unsent()) > 20, (
            "the unread-phantom sweep found almost nothing; fix the parsing rather than "
            "accepting the pass"
        )

    def test_the_count_does_not_grow(self):
        current = _declared_unread_and_unsent()
        assert len(current) <= MAX_UNREAD_PHANTOM_FIELDS, (
            f"{len(current)} declared fields have no backend producer and no reader; the "
            f"ratchet allows {MAX_UNREAD_PHANTOM_FIELDS}. Each is a field waiting for its "
            "first pane, and mockApi will make that pane look finished in development. "
            "Rename it to what the wire calls it, delete it, or make the server send "
            "it.\n\nCurrent:\n  " + "\n  ".join(sorted(current))
        )

    def test_the_ratchet_has_no_slack_at_all(self):
        """ZERO slack, not "a little". This was set one too high on the first attempt and a
        deliberately-planted phantom field slipped through unnoticed — the single spare slot
        absorbed exactly the regression the ratchet exists to catch. A count ratchet with
        any headroom cannot detect a single addition, which is the only size these arrive
        in."""
        current = _declared_unread_and_unsent()
        assert MAX_UNREAD_PHANTOM_FIELDS == len(current), (
            f"the ratchet says {MAX_UNREAD_PHANTOM_FIELDS} and {len(current)} exist. Set it "
            f"to {len(current)}: one spare slot is one free phantom field."
        )

    def test_the_engine_fields_really_are_gone(self):
        """The three FS-367 removals, asserted by name. The count above would be satisfied
        just as well by removing three unrelated fields elsewhere."""
        # COMMENTS STRIPPED FIRST. The removal is explained in a doc comment that names
        # every field it removed, so a raw substring check finds them all and fails —
        # the detector-reads-the-prose-about-its-subject problem this file's header
        # describes, and which caught the first version of this very test.
        engine_types = COMMENT.sub(" ", (FRONTEND / "types" / "engine.ts").read_text())
        for gone in ("deploymentHistory", "lastInferenceAt", "averageLatencyMs",
                     "totalInferences", "lastPollAt", "lastDeploymentAt"):
            assert gone not in engine_types, (
                f"`{gone}` is back on an engine interface and no endpoint sends it"
            )
