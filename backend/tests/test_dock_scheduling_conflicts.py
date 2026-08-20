"""Two trailers must not be sent to one dock door (FS-360, FS-392).

The second half of the untested 749-line `app/services/yard_management.py`.
`DockScheduler._check_conflicts` is the only thing standing between a schedule and two
drivers arriving at the same door, and nothing exercised it.

WHY THIS RUNS ON IN-MEMORY SQLITE. The overlap test is a SQL expression — three ORed
range comparisons — so checking it by reading the code proves nothing about what the
database does with it. Every other harness that could run it is gated on
`require_testcontainers()  # FS-808: skips on a laptop, FAILS when REQUIRE_REALDB=1` and skips wherever Docker is absent, which is most
developer machines. `Base.metadata.create_all` on SQLite is the same schema `make demo`
builds, so these run everywhere and the predicate is executed rather than reasoned about.

WHAT THAT COSTS, stated so it is not mistaken for full coverage: no RLS. Tenant isolation
for this path belongs to `test_yard_tenant_scoping_realdb.py` against real Postgres. What
is verified here is the overlap arithmetic and the validation, which are database-agnostic
and were the untested part.

THE DEFECT FOUND. `schedule_appointment` accepted a REVERSED booking — end before start —
and stored it. That is not inert: `_check_conflicts` matches such a row through its
"existing is contained by new" branch, so a 13:00->08:00 appointment blocks a legitimate
09:00-10:00 booking on that door while protecting no real slot. Measured before the fix:
09:00-10:00 blocked, 14:00-15:00 and 06:00-07:00 free. Zero-length bookings were accepted
too.

THE OVERLAP LOGIC ITSELF WAS CORRECT, including the case most implementations get wrong —
back-to-back appointments (one ends exactly when the next begins) do NOT conflict, in
either order. That is asserted below rather than assumed, because it is the behaviour a
tightening of the comparisons would silently break, and it is what makes a dock usable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests._realdb import require_testcontainers
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests._sqlite import create_all, minimal_organization, sqlite_engine

from app.db.models import Base, DockAppointment
from app.services.yard_management import DockScheduler

pytestmark = pytest.mark.asyncio

ORIGIN = datetime(2026, 8, 2, 8, 0, 0, tzinfo=timezone.utc)


def hour(offset: float) -> datetime:
    return ORIGIN + timedelta(hours=offset)


@pytest_asyncio.fixture
async def session():
    # NOT the whole metadata: under pytest the conftest imports the full app, which
    # registers `data_processing_records` with a Postgres ARRAY column SQLite cannot render.
    # `create_all` takes the one table this file is about and closes over what it REFERENCES
    # — organisations, dock doors and their parents — which is the smallest schema in which
    # the appointment rows below are legal (FS-410).
    #
    # This file was briefly exempted from FK enforcement on the grounds that it exists to
    # test one WHERE clause. That was true and still is, but the exemption was unnecessary:
    # the closure is a dozen tables, not the whole schema, and it costs one seeded
    # organisation and door.
    engine = sqlite_engine()
    await create_all(engine, Base.metadata, [DockAppointment.__table__])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as active:
        yield active
    await engine.dispose()


@pytest.fixture
def org():
    return uuid4()


@pytest_asyncio.fixture
async def door(session, org):
    """A real organisation and a real dock door, because an appointment references both."""
    from app.db.models import DockDoor

    door_id = uuid4()
    session.add(minimal_organization(org))
    await session.flush()
    session.add(DockDoor(id=str(door_id), organization_id=str(org), door_number="D1"))
    await session.commit()
    return door_id


async def _book(session, org, door, start_h, end_h, status="scheduled"):
    appointment = DockAppointment(
        organization_id=org, dock_door_id=door, appointment_type="inbound",
        scheduled_start=hour(start_h), scheduled_end=hour(end_h), status=status,
    )
    session.add(appointment)
    await session.commit()
    return appointment


async def _conflicts(session, door, start_h, end_h, exclude_id=None):
    return await DockScheduler()._check_conflicts(
        session, door, hour(start_h), hour(end_h), exclude_id=exclude_id
    )


class TestAnOccupiedDoorIsDetected:
    """The existing booking runs 08:00-10:00 in every case."""

    @pytest.mark.parametrize(
        "label,start,end",
        [
            ("the identical slot", 0, 2),
            ("entirely inside it", 0.5, 1.5),
            ("straddling its start", -1, 1),
            ("straddling its end", 1, 3),
            ("completely containing it", -1, 3),
            ("sharing only its start instant", 0, 0.5),
            ("sharing only its end instant", 1.5, 2),
        ],
    )
    async def test_an_overlapping_request_conflicts(self, session, org, door, label, start, end):
        await _book(session, org, door, 0, 2)
        assert await _conflicts(session, door, start, end), (
            f"a booking {label} was not detected as a conflict — two trailers would be "
            "sent to one door"
        )


class TestADoorStaysUsable:
    """The control. A conflict check that flags everything is as useless as one that
    flags nothing, and it fails in a direction nobody reports as a bug — the dock just
    appears fully booked."""

    async def test_back_to_back_after_is_allowed(self, session, org, door):
        await _book(session, org, door, 0, 2)
        assert not await _conflicts(session, door, 2, 4), (
            "an appointment starting exactly when the previous ends was rejected; that is "
            "the normal way a dock is scheduled"
        )

    async def test_back_to_back_before_is_allowed(self, session, org, door):
        await _book(session, org, door, 0, 2)
        assert not await _conflicts(session, door, -2, 0)

    async def test_a_different_time_is_allowed(self, session, org, door):
        await _book(session, org, door, 0, 2)
        assert not await _conflicts(session, door, 5, 6)

    async def test_a_different_door_is_not_consulted(self, session, org, door):
        await _book(session, org, door, 0, 2)
        assert not await _conflicts(session, uuid4(), 0, 2), (
            "a booking on one door blocked another door — the whole yard would serialise"
        )


class TestOnlyLiveAppointmentsBlock:
    @pytest.mark.parametrize("status", ["scheduled", "in_progress"])
    async def test_a_live_appointment_blocks(self, session, org, door, status):
        await _book(session, org, door, 0, 2, status=status)
        assert await _conflicts(session, door, 0, 2)

    @pytest.mark.parametrize("status", ["completed", "cancelled", "no_show"])
    async def test_a_finished_appointment_does_not_block(self, session, org, door, status):
        """A cancelled booking holding a door forever is how a yard silently loses
        capacity: nothing errors, the slot is simply never offered again."""
        await _book(session, org, door, 0, 2, status=status)
        assert not await _conflicts(session, door, 0, 2)


class TestReschedulingDoesNotConflictWithItself:
    async def test_excluding_the_appointment_being_moved(self, session, org, door):
        """Without `exclude_id`, moving an appointment by ten minutes finds ITSELF in the
        way and refuses.

        NOTHING PASSES IT TODAY — there is no reschedule endpoint (`/dock/appointments`
        has POST, GET, start and complete, and no update). So this covers infrastructure
        that is correct and unused, which is worth having tested precisely because the
        first caller will be written by someone who assumes it works. Stated rather than
        left implied, so the test is not mistaken for evidence that rescheduling ships."""
        appointment = await _book(session, org, door, 0, 2)
        assert await _conflicts(session, door, 0, 2)
        assert not await _conflicts(session, door, 0, 2, exclude_id=appointment.id)

    async def test_another_appointment_still_blocks_the_move(self, session, org, door):
        """The control: excluding one must not excuse the rest."""
        moving = await _book(session, org, door, 0, 2)
        await _book(session, org, door, 3, 5)
        assert await _conflicts(session, door, 3.5, 4, exclude_id=moving.id)


class TestAnAppointmentMustOccupyTime:
    """FS-392. All three were accepted before the fix."""

    async def test_a_reversed_booking_is_rejected(self, session, org, door):
        with pytest.raises(ValueError, match="must be after"):
            await DockScheduler().schedule_appointment(
                organization_id=org, dock_door_id=door,
                scheduled_start=hour(5), scheduled_end=hour(0),
                appointment_type="inbound", db=session,
            )

    async def test_a_zero_length_booking_is_rejected(self, session, org, door):
        with pytest.raises(ValueError, match="must be after"):
            await DockScheduler().schedule_appointment(
                organization_id=org, dock_door_id=door,
                scheduled_start=hour(1), scheduled_end=hour(1),
                appointment_type="inbound", db=session,
            )

    async def test_a_valid_booking_is_still_accepted(self, session, org, door):
        """The control — a validation that rejects everything passes both tests above."""
        appointment = await DockScheduler().schedule_appointment(
            organization_id=org, dock_door_id=door,
            scheduled_start=hour(0), scheduled_end=hour(2),
            appointment_type="inbound", db=session,
        )
        assert appointment.id is not None

    async def test_a_reversed_row_would_have_blocked_an_innocent_slot(self, session, org, door):
        """WHY THE VALIDATION MATTERS, demonstrated on a row inserted directly — which is
        how any that predate the fix got there. A 13:00->08:00 appointment blocks
        09:00-10:00, a span it does not occupy, and leaves 14:00-15:00 free."""
        await _book(session, org, door, 5, 0)
        assert await _conflicts(session, door, 1, 2), (
            "the demonstration no longer reproduces; if the overlap branches changed, this "
            "test is no longer showing why reversed rows are harmful"
        )
        assert not await _conflicts(session, door, 6, 7)


class TestSchedulingRefusesAnOccupiedDoor:
    async def test_it_raises_rather_than_double_books(self, session, org, door):
        await _book(session, org, door, 0, 2)
        with pytest.raises(ValueError, match="conflict"):
            await DockScheduler().schedule_appointment(
                organization_id=org, dock_door_id=door,
                scheduled_start=hour(1), scheduled_end=hour(3),
                appointment_type="inbound", db=session,
            )

    async def test_the_refusal_says_how_many(self, session, org, door):
        await _book(session, org, door, 0, 2)
        await _book(session, org, door, 2, 4)
        with pytest.raises(ValueError, match="2 overlapping"):
            await DockScheduler().schedule_appointment(
                organization_id=org, dock_door_id=door,
                scheduled_start=hour(1), scheduled_end=hour(3),
                appointment_type="inbound", db=session,
            )
