"""201 broad handlers swallow a failure; 11 of them count it. Both numbers ratchet (FS-539).

THE MEASUREMENT. 283 handlers in `app/` catch `Exception`, `BaseException` or bare. **201 of
them never re-raise** — the failure ends there, and in 190 of those cases nothing increments a
counter, so the only record is a log line that aggregates nowhere.

WHY A RATCHET AND NOT A SWEEP. Most of these are correct. A background task that must not die,
a best-effort cache warm, a notification that is nice to have — swallowing is the right call in
each, and a file demanding 201 fixes would be argued with and then ignored. What is not correct
is that the number can grow without anyone noticing, and that a swallow on a path that matters
looks identical to a swallow on one that does not.

So two numbers, each moving one way only:

    MAX_SWALLOWING   201  may only go DOWN — a new uncounted swallow fails the build
    MIN_COUNTED       11  may only go UP   — hardening a handler is recorded, not lost

The pair matters more than either alone. A count cap by itself is satisfied by deleting a
handler; a counted floor by itself is satisfied by adding handlers that count. Together the
only way to move both in the right direction is to make an existing failure visible.

WHAT IT ALREADY COST, THREE TIMES. FS-504: a buffer prune dropped 500 undelivered readings and
counted none. FS-537: alarm rule evaluation failed silently, so the alerting was off while
telemetry flowed. FS-536: **the audit trail was silently empty on real deployments while every
write appeared to succeed** — the schema still carries that post-mortem. In all three the
swallow was right and the silence was the defect, and in all three it was found by accident.

FILES ALREADY AT ZERO stay at zero, named individually below. `ingestion.py` and `audit.py`
were hardened by FS-537 and FS-536; a regression there is a specific loss, not a change in a
total, and the total is far too coarse to show it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from tests.test_every_swallowed_side_effect_is_counted import (
    UNCOUNTED as _COUNTED_VIA_HELPER,
)

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: Broad handlers that never re-raise. **Only ever goes down.** Measured 2026-08-08.
MAX_SWALLOWING = 201

#: Swallowing handlers that increment a counter. **Only ever goes up.** Measured 2026-08-08.
#: Eleven, not the ten a body-only scan reports: `ingestion.py`'s top-level handler counts
#: through `_dead_letter`. Set to the exact figure — a floor one below the real number is
#: a free regression nobody would see.
#:
#: RAISED TO 13 with the Hridyansh merge. His two new swallows are both RIGHT to continue —
#: a rollout whose command cannot be cancelled must not abort the other cancellations, and a
#: dispatch iteration that raises must not kill the orchestrator — so they were counted
#: (`opsgrid_ota_rollout_failures_total`) rather than narrowed. The total stayed at 201
#: because two websocket sends were narrowed from `except Exception` in exchange, which is
#: what this file means by "lower some other allowance first".
MIN_COUNTED = 13

#: Files whose swallows are all counted, and must stay that way. A regression here is a
#: specific failure going dark again, which the totals above cannot show: swapping a counted
#: handler in `ingestion.py` for an uncounted one somewhere quiet leaves both numbers intact.
FULLY_COUNTED_FILES = {
    "app/workers/ingestion.py": (
        "FS-537. Six swallowed side effects, including alarm rule evaluation — whose "
        "failure means the alerting is off while telemetry flows and dashboards update."
    ),
    "app/middleware/audit.py": (
        "FS-536. This trail has already been silently empty on real deployments while every "
        "write appeared to succeed; `db/models.py:1561-1567` carries the post-mortem."
    ),
}

#: Substrings that mark a handler as counting its own failure.
_COUNTER_MARKERS = ("_FAILED.labels", "_FAILURES.labels", ".inc()")

#: Handlers that count through a HELPER, so the increment is not in the handler body.
#:
#: The name is imported at the top from the FS-537 guard rather than restated: the two files
#: share the same detector limitation, and a second copy of the reason is a second thing to
#: keep true — the shape FS-492 named. `ingestion.py`'s top-level handler calls `_dead_letter`,
#: which increments INGESTION_DEAD_LETTERED and INGESTION_DEAD_LETTER_FAILED, both alerted on.
_HELPER_COUNTED_NAMES = _COUNTED_VIA_HELPER


def _handlers() -> list[tuple[str, int, bool]]:
    """(relative path, line, counts-its-own-failure) for every swallowing broad handler.

    Only broad catches. `except ValueError:` around a parse is a known case being handled,
    which is the opposite of this class — narrowing a catch is how you *fix* one of these,
    and counting them would punish the fix.
    """
    root = APP.parent
    found = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = ast.unparse(node.type) if node.type else "bare"
            if caught not in {"Exception", "BaseException", "bare"}:
                continue
            if any(isinstance(n, ast.Raise) for n in ast.walk(node)):
                continue  # re-raises: the caller sees it
            body = ast.unparse(node)
            found.append(
                (
                    str(path.relative_to(root)),
                    node.lineno,
                    any(marker in body for marker in _COUNTER_MARKERS)
                    or any(name in body for name in _HELPER_COUNTED_NAMES),
                )
            )
    return found


class TestTheDetectorIsHonest:
    def test_it_finds_a_plausible_number(self):
        """Vacuity in both directions. Zero means the walk broke; the whole file count
        means it stopped distinguishing re-raising from swallowing."""
        handlers = _handlers()
        assert 50 < len(handlers) < 400, (
            f"{len(handlers)} swallowing handlers found. Outside this range the AST walk is "
            f"broken rather than the codebase transformed."
        )

    def test_a_reraising_handler_is_not_counted(self):
        """`except Exception: raise HTTPException(...)` is the common correct shape and must
        not be in the population, or the ratchet punishes translating an error properly."""
        source = "try:\n    x()\nexcept Exception as e:\n    raise ValueError(e)\n"
        handlers = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ExceptHandler)
            and not any(isinstance(n, ast.Raise) for n in ast.walk(node))
        ]
        assert not handlers


class TestTheSurfaceOnlyShrinks:
    def test_the_swallow_count_has_not_grown(self):
        handlers = _handlers()
        assert len(handlers) <= MAX_SWALLOWING, (
            f"{len(handlers)} broad handlers swallow a failure, up from {MAX_SWALLOWING}. "
            f"Either narrow the catch, re-raise, or count the failure — and if the new one "
            f"is deliberate, lower some other allowance first. This number only goes down.\n"
            f"New since the baseline are the ones to look at; the rest were measured on "
            f"2026-08-08."
        )

    def test_the_counted_count_has_not_shrunk(self):
        counted = sum(1 for _, _, counts in _handlers() if counts)
        assert counted >= MIN_COUNTED, (
            f"only {counted} swallowing handlers increment a counter, down from "
            f"{MIN_COUNTED}. A handler that stopped counting is a failure that went dark: "
            f"the log line remains and nothing aggregates it, which is how FS-504, FS-536 "
            f"and FS-537 each happened."
        )

    def test_the_baseline_is_not_slack(self):
        """A ratchet set well above the real figure allows growth while reading as a
        constraint — the failure `contract_ratchet.py` names in its own header."""
        handlers = _handlers()
        assert MAX_SWALLOWING - len(handlers) <= 10, (
            f"the allowance is {MAX_SWALLOWING} and the real count is {len(handlers)}, a "
            f"slack of {MAX_SWALLOWING - len(handlers)}. Lower it: a floor nobody can fall "
            f"through is not a claim about anything."
        )


class TestTheHardenedFilesStayHardened:
    @pytest.mark.parametrize("path,reason", sorted(FULLY_COUNTED_FILES.items()))
    def test_every_swallow_in_it_is_counted(self, path: str, reason: str):
        uncounted = [
            f"{p}:{line}" for p, line, counts in _handlers() if p == path and not counts
        ]
        assert not uncounted, (
            f"{uncounted} swallow a failure without counting it, in a file that was fully "
            f"hardened.\n\n{reason}\n\nThe totals above cannot show this: swapping a counted "
            f"handler here for an uncounted one somewhere quiet leaves both numbers intact."
        )

    @pytest.mark.parametrize("path", sorted(FULLY_COUNTED_FILES))
    def test_the_file_still_has_swallows_to_check(self, path: str):
        """If the handlers were all removed the test above passes over an empty list, and a
        file with nothing left to guard should be dropped from the set deliberately rather
        than quietly satisfying it."""
        assert any(p == path for p, _, _ in _handlers()), (
            f"{path} has no broad swallowing handlers at all any more. Genuine improvement "
            f"or a moved file — either way remove it from FULLY_COUNTED_FILES so this stops "
            f"reading as an enforced property."
        )
