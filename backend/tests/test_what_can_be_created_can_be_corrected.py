"""A field you can set once and never correct (FS-671).

Comparing each `*Create` schema against its `*Update` sibling found fields a caller could
supply at creation and never change again — on entities that already have a working PUT route
updating ten other columns on the same row:

  * a **driver's phone number, email, carrier and ELD device**;
  * a **shipment's** pickup and delivery schedule, origin, destination, weights, hazmat flag
    and temperature range — sixteen fields;
  * a **trailer's** seal number and reefer setpoint, while `seal_status` and
    `temperature_actual` beside them were already editable, which is the pairing that makes
    the omission visible.

`route_id` closes a loop from the same day. FS-665 stopped `get_shipment_costs` inventing 500
miles for a shipment with no route, so such a shipment now honestly reports **not estimated** —
and nothing could assign it a route afterwards, making the honest state inescapable without
recreating the shipment.

WHY THIS IS SAFE TO ADD. Every one of these handlers applies
`data.model_dump(exclude_unset=True)` and `setattr`, which
`test_partial_updates_do_not_wipe_fields.py` enforces. A field on the Update schema becomes
editable when sent and untouched when omitted, so widening the schema cannot blank anything.

WHAT IS DELIBERATELY STILL UNEDITABLE: `shipment_number` and `trailer_number`. They identify
the row, and an API that lets a caller rename the thing it is addressing has a different
problem. Asserted below so the omission reads as a decision.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.schemas import (
    DriverCreate,
    DriverUpdate,
    ShipmentCreate,
    ShipmentUpdate,
    YardTrailerCreate,
    YardTrailerUpdate,
)

PAIRS = [
    ("driver", DriverCreate, DriverUpdate, set()),
    ("shipment", ShipmentCreate, ShipmentUpdate, {"shipment_number"}),
    ("trailer", YardTrailerCreate, YardTrailerUpdate, {"trailer_number"}),
]


class TestEveryCreatableFieldCanBeCorrected:
    @pytest.mark.parametrize("name,create,update,immutable", PAIRS, ids=[p[0] for p in PAIRS])
    def test_nothing_is_set_once_and_frozen(self, name, create, update, immutable):
        uneditable = set(create.model_fields) - set(update.model_fields) - immutable
        assert not uneditable, (
            f"a {name} can be created with {sorted(uneditable)} and never corrected, on an "
            f"entity that already has a PUT route. Add the field to the Update schema — the "
            f"handler applies `model_dump(exclude_unset=True)`, so it stays untouched when "
            f"the caller does not send it."
        )

    @pytest.mark.parametrize("name,create,update,immutable", PAIRS, ids=[p[0] for p in PAIRS])
    def test_the_identifier_stays_immutable(self, name, create, update, immutable):
        """The other direction. If `shipment_number` becomes editable this fails, and that
        should be a deliberate decision rather than a side effect of widening the schema."""
        for field in immutable:
            assert field not in update.model_fields, (
                f"{field} identifies the {name}; an API that lets a caller rename the thing "
                f"it is addressing has a different problem"
            )


class TestTheUpdateStaysPartial:
    """Widening a schema is only safe because the handlers exclude unset fields. These assert
    the property directly rather than trusting the sibling guard, because the sibling guard
    checks the HANDLERS and this file changed the SCHEMAS."""

    @pytest.mark.parametrize("update", [DriverUpdate, ShipmentUpdate, YardTrailerUpdate])
    def test_an_unsent_field_is_excluded_from_the_dump(self, update):
        sent = update()
        assert sent.model_dump(exclude_unset=True) == {}, (
            "a freshly constructed update model dumps fields nobody sent, so applying it "
            "with setattr would blank every column on the row"
        )

    def test_a_one_field_update_carries_only_that_field(self):
        payload = ShipmentUpdate(route_id=uuid.uuid4())
        assert set(payload.model_dump(exclude_unset=True)) == {"route_id"}


class TestTheFieldsThatMotivatedThis:
    def test_a_shipment_can_be_given_a_route_after_creation(self):
        """The loop back to FS-665. A shipment with no route reports its charges as *not
        estimated* — correct, and previously permanent."""
        assert "route_id" in ShipmentUpdate.model_fields

    def test_a_shipment_can_be_rescheduled(self):
        """A pickup moving is the most ordinary event in dispatch."""
        for field in ("scheduled_pickup", "scheduled_delivery"):
            assert field in ShipmentUpdate.model_fields

    def test_a_driver_can_change_phone_number(self):
        for field in ("phone", "email"):
            assert field in DriverUpdate.model_fields

    def test_a_replaced_seal_can_be_recorded(self):
        """`seal_status` was already editable and `seal_number` was not, so a seal replaced
        at the gate could be marked intact while still naming the old seal."""
        assert "seal_number" in YardTrailerUpdate.model_fields
        assert "seal_status" in YardTrailerUpdate.model_fields

    def test_a_reefer_setpoint_can_be_changed(self):
        assert "temperature_setpoint" in YardTrailerUpdate.model_fields
        assert "temperature_actual" in YardTrailerUpdate.model_fields
