#!/usr/bin/env python3
"""Seed a user the e2e suite can actually log in as (FS-239).

WHY THIS IS SEPARATE FROM THE DEMO SEEDER. `seed_demo_data.py` creates
`admin@omniusgrid.com` with a hard-coded bcrypt hash
(`$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYHqF5pXa9W`) that corresponds
to no known plaintext — the same placeholder hash the dev-token bypass in
`app/api/auth.py` uses. So the demo "admin" account CANNOT be logged into through
the real login form; the demo works because `VITE_DEV_MODE=true` bypasses
authentication entirely.

That is fine for a demo and useless for an e2e whose entire purpose is to exercise
the real auth path. Rather than change the demo seeder's semantics, this creates a
dedicated user whose password is hashed with the application's own
`get_password_hash`, so the credential is real by construction rather than by a
hash somebody pasted in.

Idempotent: re-running updates the password rather than failing on the unique email.

    DATABASE_URL=... python scripts/seed_e2e_user.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Credentials the Playwright suite uses. Deliberately obvious and deliberately
# NOT a real-looking secret: this account exists only inside an ephemeral test
# database that is destroyed with the job.
E2E_EMAIL = os.environ.get("E2E_USER_EMAIL", "e2e@omniusgrid.test")
E2E_PASSWORD = os.environ.get("E2E_USER_PASSWORD", "e2e-playwright-password")

# The demo organization seed_demo_data.py populates, so the dashboard this user
# lands on has real assets, alarms and telemetry to render. Logging in to an empty
# org would make the test pass against a blank dashboard — exactly the bug FS-191
# fixed and the reason this test exists.
DEMO_ORG = UUID("00000000-0000-0000-0000-000000000001")


async def main() -> int:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.api.auth import get_password_hash
    from app.db.database import AsyncSessionLocal
    from app.db.models import Organization, User

    async with AsyncSessionLocal() as session:  # type: AsyncSession
        org = (
            await session.execute(
                select(Organization).where(Organization.id == DEMO_ORG)
            )
        ).scalars().first()
        if org is None:
            print(
                f"ERROR: demo organization {DEMO_ORG} is missing. Run "
                f"scripts/seed_demo_data.py first — this user must land on an org "
                f"that has data, or the dashboard assertions pass against a blank "
                f"page.",
                file=sys.stderr,
            )
            return 1

        existing = (
            await session.execute(select(User).where(User.email == E2E_EMAIL))
        ).scalars().first()

        if existing:
            existing.hashed_password = get_password_hash(E2E_PASSWORD)
            existing.is_active = True
            existing.role = "admin"
            existing.organization_id = DEMO_ORG
            action = "updated"
        else:
            session.add(
                User(
                    email=E2E_EMAIL,
                    full_name="E2E Test User",
                    hashed_password=get_password_hash(E2E_PASSWORD),
                    organization_id=DEMO_ORG,
                    # admin so the suite can reach the admin surfaces too.
                    role="admin",
                    is_active=True,
                )
            )
            action = "created"

        await session.commit()

    print(f"e2e user {action}: {E2E_EMAIL} (org {DEMO_ORG})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
