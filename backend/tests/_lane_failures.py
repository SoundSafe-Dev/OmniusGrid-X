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


#: A root cause shared by four entries across both walks, recorded once.
_WRITE_ON_READ = (
    "a read endpoint INSERTs a default row, and the INSERT runs on a session whose tenant "
    "GUC is not bound, so the FORCE ROW LEVEL SECURITY policy rejects it"
)

#: GET endpoints permitted to 5xx. Keyed by path, mirroring the GET walk.
GET_FAILURES: dict[str, LaneFailure] = {
    "/api/v1/kanban/board": LaneFailure(
        owner="HARSH",
        reason=f"RLS violation writing the default board on read — {_WRITE_ON_READ}",
        fix="bind the tenant session (get_tenant_db) before the default-board INSERT, or "
            "stop writing on a read path",
        expires="2026-09-15",
    ),
    "/api/v1/kanban/metrics": LaneFailure(
        owner="HARSH",
        reason=f"same default-board write path as /kanban/board — {_WRITE_ON_READ}",
        fix="one fix with /kanban/board; these three go together",
        expires="2026-09-15",
    ),
    "/api/v1/kanban/workload": LaneFailure(
        owner="HARSH",
        reason=f"same default-board write path as /kanban/board — {_WRITE_ON_READ}",
        fix="one fix with /kanban/board; these three go together",
        expires="2026-09-15",
    ),
    "/api/v1/kanban/rules/premade": LaneFailure(
        owner="HARSH",
        reason="premade template ids ('template-001') are not UUIDs and the payload omits "
               "org_id/is_active/target_board_id vs its response_model. NOT environmental: "
               "the ids are static, so this fails on any database",
        fix="either widen the response model's id to str, or give the premade templates "
            "real UUIDs. Independently re-found by a page-by-page QA sweep on 2026-08-01",
        expires="2026-09-15",
    ),
    "/api/v1/nlp/correlation/intake/{intake_id}": LaneFailure(
        owner="HARSH",
        reason="select() is given the IntakeItem CLASS rather than a column expression",
        fix="one line — pass the column, or select(IntakeItem) if the whole row is wanted",
        expires="2026-09-15",
    ),
    "/api/v1/rag/documents": LaneFailure(
        owner="htreinen",
        reason="reaches SeaweedFS at seaweedfs:8333 and surfaces the connection error as a "
               "500",
        fix="degrade to 503 when the object store is absent, as every Redis-backed endpoint "
            "already does. Needs a decision on whether an absent store is degraded or fatal",
        expires="2026-09-30",
    ),
}

#: Write endpoints permitted to 5xx. Keyed by (method, path) — the write walk records why
#: the method is part of the key, and it is not optional.
WRITE_FAILURES: dict[tuple[str, str], LaneFailure] = {
    ("POST", "/api/v1/kanban/board/view"): LaneFailure(
        owner="HARSH",
        reason=f"writes a default board on read — {_WRITE_ON_READ}. Same root cause the "
               "GET walk records for /kanban/board",
        fix="one fix with the three GET entries above",
        expires="2026-09-15",
    ),
    # RELEASED 2026-08-04 (FS-430). The recorded fix — "bind the tenant session before the
    # INSERT" — was exactly right: `correlation_integration.py` took `Depends(get_db)`, the
    # unscoped session, and `actionable_registries` is FORCE RLS, so every INSERT was refused.
    #
    # THE ENTRY UNDERSTATED IT. All THREE write-bearing endpoints in that module had it —
    # /analyze and /test-integration as well — and only this one was probed, so the other two
    # failed the same way with nothing recording them. A single allowlist line can be the
    # visible corner of a module-wide defect.
    #
    # Proven under the conditions that apply: as a NON-superuser the old code returns 500 and
    # writes zero rows, the fix returns 200 and writes 46. As a superuser both "pass", which
    # is why the first attempt at verifying this proved nothing — FORCE RLS does not apply to
    # a superuser, and a throwaway container's default role is one.
    ("POST", "/api/v1/engines/correlation/generate"): LaneFailure(
        owner="HARSH",
        reason="correlation_ai_engine returns 500 on an empty scenario body rather than 422",
        fix="validate the scenario body; an empty POST is the caller's mistake",
        expires="2026-09-30",
    ),
    ("DELETE", "/api/v1/rag/documents/{doc_id}"): LaneFailure(
        owner="htreinen",
        reason="reaches SeaweedFS and surfaces the connection error; same root cause as the "
               "GET walk's /api/v1/rag/documents",
        fix="degrade to 503 with the GET entry. Note this route also takes `doc_id: str`, "
            "so a literal path segment reaches it (recorded separately as FS-266)",
        expires="2026-09-30",
    ),
}
