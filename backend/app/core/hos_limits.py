"""Federal hours-of-service limits, in one place (FS-475).

49 CFR 395 — the FMCSA limits for property-carrying drivers. These are **law, not tuning**:
they do not vary by deployment, and this platform does not get to have an opinion about
them. What it does get wrong is having more than one copy.

THREE FILES HELD THE SAME NUMBERS, THREE DIFFERENT WAYS:

    services/transportation_management.py   owned all four as class attributes
    api/transportation.py                   re-declared two at module level
    api/fleet_logistics.py                  imported the whole compliance class for two

The re-declaration carried a reason, which is why it survived review: *"Kept beside the
serializer that needs them rather than imported from the compliance service, which would drag
its session dependencies into this module."* That objection was true. It was also already
being ignored — `fleet_logistics` imports `HOSComplianceMonitor` for exactly the same purpose.

**WHY DUPLICATION IS SHARPER HERE THAN USUAL.** The two copies feed different answers about
the same driver. `api/transportation.py` computes hours REMAINING, which a dispatcher reads
before assigning a load; `transportation_management.py` decides VIOLATIONS, which a compliance
screen reads afterwards. If one is edited and the other is not, the platform tells a
dispatcher a driver has two hours left and tells a compliance officer that same driver is in
breach — and both numbers look authoritative.

This module has no imports on purpose. That is the whole answer to the original objection: a
constant cannot drag a session dependency if it lives somewhere that has none.
"""

from __future__ import annotations

#: Maximum driving hours in a duty period. 49 CFR 395.3(a)(3).
MAX_DRIVE_HOURS_DAY = 11.0

#: Maximum on-duty hours in a duty period, driving or not. 49 CFR 395.3(a)(2).
MAX_ON_DUTY_HOURS_DAY = 14.0

#: Maximum on-duty hours in an 8-day cycle. 49 CFR 395.3(b)(2).
MAX_CYCLE_HOURS = 70.0

#: Consecutive off-duty hours required before a new duty period. 49 CFR 395.3(a)(1).
REQUIRED_REST_HOURS = 10.0
