"""create_route wires `is_active` through to the stored row (FS-907).

THE DEFECT. `RouteCreate` declared `is_active: bool = True` and the handler never read
`data.is_active` -- unlike the four other dropped fields on this schema, which are
genuinely computed by the route optimizer, nothing computes `is_active`. A caller
creating a route already marked inactive (e.g. an archived/historical route imported in
one call) had that silently overridden to the column default (True).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from tests._sqlite import create_all, minimal_organization, sqlite_engine
from app.db.models import Base, Route
from app.services.transportation_management import TransportationManagementService

ORG = uuid4()


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _fake_optimize_route(*, origin, destination, waypoints, optimization_criteria):
    return {
        "total_distance_miles": 42.0,
        "estimated_duration_hours": 1.0,
        "fuel_cost_estimate": 10.0,
        "toll_cost_estimate": 0.0,
    }


async def _factory():
    engine = sqlite_engine()
    await create_all(engine, Base.metadata, [Route.__table__])
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        s.add(minimal_organization(ORG))
        await s.flush()
        await s.commit()
    return Session


class TestIsActiveReachesTheStoredRow:
    def test_a_route_created_inactive_is_stored_inactive(self):
        async def scenario():
            Session = await _factory()
            service = TransportationManagementService()
            with patch.object(
                service.route_optimizer, "optimize_route", side_effect=_fake_optimize_route
            ):
                async with Session() as s:
                    route = await service.create_route(
                        organization_id=ORG,
                        origin={"city": "A"},
                        destination={"city": "B"},
                        is_active=False,
                        db=s,
                    )
                    return route

        route = run(scenario())
        assert route.is_active is False, (
            "is_active=False was passed to create_route but the stored row is active -- "
            "the wiring regressed"
        )

    def test_the_default_is_still_active(self):
        """Not overcorrected: omitting is_active must still create an active route."""
        async def scenario():
            Session = await _factory()
            service = TransportationManagementService()
            with patch.object(
                service.route_optimizer, "optimize_route", side_effect=_fake_optimize_route
            ):
                async with Session() as s:
                    route = await service.create_route(
                        organization_id=ORG,
                        origin={"city": "A"},
                        destination={"city": "B"},
                        db=s,
                    )
                    return route

        route = run(scenario())
        assert route.is_active is True
