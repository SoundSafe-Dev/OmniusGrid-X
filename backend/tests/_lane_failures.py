"""The endpoints another lane's code is allowed to 5xx on — with a deadline (FS-363).

Two real-DB walks carry an allowlist of endpoints that fail and are not ours to fix: the
GET walk (`test_realdb_endpoint_smoke.py`) and the write walk
(`test_write_endpoints_reject_cleanly_realdb.py`). Both were already asserted BOTH ways —
a new 5xx outside the list fails, an entry that starts passing also fails — so neither can
rot silently.

WHAT THEY STILL COULD NOT DO IS END. An entry with an owner and a reason but no date is a
decision nobody has to make again. `test_ci_quarantine_expires.py` says this better than I
can, about the CI `--ignore` flags it governs:

    a flag in a workflow file has no expiry, no owner and no record of what would have to
    be true to remove it. It is a suppression, and this repository has spent a long time
    learning what suppressions do: they convert a defect into a survivable condition, and
    survivable conditions are never revisited.

That register's entries went from five to one, and the note explaining why is worth
repeating: the assumption that the excluded tests encoded unbuilt behaviour dissolved the
moment someone checked it. An expiry is what makes someone check.

WHAT THE DATE MEANS. Not a commitment by the owner — I cannot make those. It is the day
this repository asks the question again, and the failure message carries the diagnosis so
answering it is cheap. Re-dating an entry with a fresh reason is a perfectly good outcome;
letting it sit unexamined for a year is not.

TWO TIERS, because the entries are not equally ready:

  * 2026-09-15 — the fix is already written down precisely enough to apply.
  * 2026-09-30 — a design decision is needed first (what a missing object store should
    return, whether a write-on-read path should exist at all).

`test_lane_failures_expire.py` enforces this, and deliberately needs no database: an
expiry that only fires when Docker is available is an expiry that does not fire.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class LaneFailure:
    """A 5xx owned by another lane, and what would end it."""

    #: The lane or person who owns the subsystem. Not a blame field — a routing field.
    owner: str
    #: Why it fails, precisely enough that the owner does not have to reproduce it.
    reason: str
    #: What has to change. Where this is a one-liner, the expiry is the near tier.
    fix: str
    #: ISO date after which this test fails and someone re-decides.
    expires: str

    @property
    def expiry_date(self) -> datetime.date:
        return datetime.date.fromisoformat(self.expires)


#: BOTH REGISTERS ARE EMPTY as of 2026-08-04 (FS-431). Every entry was fixed rather than
#: re-dated, and what the entries got wrong is worth more than the fact that they closed:
#:
#:   * `/nlp/correlation/intake/{intake_id}` — recorded as "select() is given the class
#:     rather than a column expression". `select(SomeModel)` is correct SQLAlchemy 2.0, so
#:     the recorded reason described valid code. The actual cause was NAME SHADOWING: the
#:     module defines a Pydantic `IntakeItem` for the response body and imports the ORM
#:     class as `IntakeItemModel`, and this one call site reached for the Pydantic one. A
#:     sibling read forty lines away had always used the right name.
#:   * `/kanban/rules/premade` — recorded as omitting "org_id/is_active/target_board_id".
#:     It omits TEN required fields, because a template is not a rule and cannot have an
#:     id, an owner or timestamps before someone creates one. The fix was a response model,
#:     not three added fields.
#:   * `POST /engines/correlation/generate` — recorded as "500 on an empty scenario body
#:     rather than 422". There is no body; `count` defaults. It 500'd because
#:     `StateSpaceLoader("state_space")` resolves against the WORKING DIRECTORY, loaded
#:     nothing when the server was not started from `backend/`, and reported success —
#:     `random.choice` then failed several frames later on an empty sequence. Running the
#:     endpoint by hand from `backend/` "passed", which is how it stayed misdiagnosed.
#:   * the two RAG entries — recorded as needing "a decision on whether an absent store is
#:     degraded or fatal". The decision was already made and already written in that file:
#:     `document_link` twenty lines up raises 503. What defeated it is that
#:     `DocumentStore.available` is `aioboto3 is not None` — a PACKAGE-INSTALLED check that
#:     is True on every deployment and can never observe an unreachable store.
#:
#: FOUR OF FIVE RECORDED CAUSES WERE WRONG, and each was wrong in the same direction: it
#: described something plausible that could be believed without running anything. An
#: allowlist entry is a hypothesis with a date on it, not a diagnosis. The expiry is what
#: made someone check, and checking is what found the real ones — so the mechanism worked
#: exactly as intended, including in its failure to be accurate.
#:
#: KEEP THE DICTS. Both walks read them, both assert in both directions, and an empty
#: register that a new 5xx must be added to deliberately is the point.

#: GET endpoints permitted to 5xx. Keyed by path, mirroring the GET walk.
GET_FAILURES: dict[str, LaneFailure] = {}

#: Write endpoints permitted to 5xx. Keyed by (method, path) — the write walk records why
#: the method is part of the key, and it is not optional.
WRITE_FAILURES: dict[tuple[str, str], LaneFailure] = {}
