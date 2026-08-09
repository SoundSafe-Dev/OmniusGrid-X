"""Every way the buffer loses a message increments a counter (FS-458).

The store-and-forward buffer is the agent's promise that a network outage costs nothing: it
holds telemetry on disk until the cloud acknowledges it. That promise has three exits, and
every one of them destroys data that was captured and never delivered — rows leave `messages`
on success via `mark_sent`, so anything still there is undelivered by definition.

    move_exhausted_to_dead_letter   retries exhausted        -> counted, warned
    enforce_size_limit              disk cap reached         -> counted, warned
    cleanup_old_messages            retention window passed  -> NOT COUNTED, logged at info

The third is the one that matters most and was the one nobody could see. Dead-lettering and
size pruning happen on a healthy device under load. Expiry happens when the device has been
**unable to reach the cloud for longer than the retention window** — the exact scenario the
buffer exists for, failing — and its only trace was an INFO line in a log file on a box that,
by construction, cannot ship logs either.

So the operator's view of a week-long outage was: a gauge of pending messages that stops
rising, and nothing else. Nothing distinguished "the buffer is holding steady" from "the
buffer is deleting the oldest hour every hour."

WHY THE ASSERTION IS STRUCTURAL. Naming the three exits in a test would leave a fourth
uncounted the day someone adds it, which is precisely how the third one came to be missed —
two were written together and the third was written elsewhere, months apart. So this walks
`store_forward.py` for methods that DELETE from `messages` and requires each to have a
counter wired at the call site.
"""

from __future__ import annotations

import ast
import os
from datetime import datetime, timezone
import pathlib
import unittest

from opsgrid_agent import metrics

AGENT_DIR = pathlib.Path(__file__).resolve().parent.parent / "opsgrid_agent"
STORE_FORWARD = AGENT_DIR / "buffer" / "store_forward.py"
MAIN = AGENT_DIR / "main.py"

#: Deletions that are not a loss of undelivered data and need no counter, each with the
#: reason. An entry here is a claim, so keep it short enough to check.
NOT_A_LOSS = {
    # Removes rows the cloud has ACKNOWLEDGED. The delivery is the point; the delete is
    # bookkeeping.
    "mark_sent": "the cloud acknowledged these",
    # `_prune_oldest_sync` WAS HERE, and the reason was wrong (FS-504). It read "emergency
    # space reclamation; the hourly path counts the steady state" — but `enforce_size_limit`
    # counts `cursor.rowcount`, rows its own DELETE removed, so anything the disk-full handler
    # had already deleted was gone from the table and counted by nothing. Up to 500
    # undelivered readings per event. It calls `metrics.record_dropped` now, so it belongs in
    # the counted set and not here.
}


def _methods_recording_their_own_loss() -> set[str]:
    """Methods in store_forward.py that call `metrics.record_*` in their own body.

    The three periodic cleanups are counted by their caller in `main.py`; a method reached
    from inside `store()` cannot be, so it counts itself instead. Both are honest — what is
    not honest is a deletion counted by neither.
    """
    found: set[str] = set()
    tree = ast.parse(STORE_FORWARD.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr.startswith("record_")
            ):
                found.add(node.name)
    return found


def _methods_deleting_messages() -> dict[str, int]:
    """Method name -> line, for every method that deletes from the `messages` table."""
    found: dict[str, int] = {}
    tree = ast.parse(STORE_FORWARD.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                sql = " ".join(inner.value.split()).upper()
                if "DELETE FROM MESSAGES" in sql:
                    found[node.name] = node.lineno
    return found


class TestTheSweepIsNotVacuous(unittest.TestCase):
    def test_it_finds_the_deleting_methods(self):
        methods = _methods_deleting_messages()
        self.assertGreaterEqual(
            len(methods),
            3,
            f"only {len(methods)} deleting methods found in {STORE_FORWARD.name}; the SQL "
            f"scan is broken and every assertion below would pass over nothing",
        )

    def test_the_exemptions_still_name_real_methods(self):
        methods = _methods_deleting_messages()
        stale = sorted(set(NOT_A_LOSS) - set(methods))
        self.assertEqual(
            stale,
            [],
            f"these methods are exempted from needing a counter and no longer delete from "
            f"`messages`: {stale}. An exemption that names nothing hides the next one.",
        )


class TestEveryLossPathIsCounted(unittest.TestCase):
    def test_each_deleting_method_has_a_counter_at_its_call_site(self):
        """The counter must read THIS call's return value, not merely sit nearby.

        The first version of this test searched a 400-character window after the buffer
        call for `metrics.record_`. It passed with the fix removed, because the window
        reached down into the NEXT loss path's counter — a guard that is green whether or
        not the defect is present, which is worse than no guard at all. Found by mutating
        the fix out and watching this stay green.

        So: bind the variable. `deleted = await self.buffer.cleanup_old_messages()` must be
        followed by a `metrics.record_*(deleted)` naming that exact variable.
        """
        tree = ast.parse(MAIN.read_text())

        #: variable name -> buffer method it was assigned from
        assigned: dict[str, str] = {}
        #: variable names passed to a metrics.record_* call
        counted: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                value = node.value
                if isinstance(value, ast.Await):
                    value = value.value
                if (
                    isinstance(target, ast.Name)
                    and isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                ):
                    assigned[target.id] = value.func.attr
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("record_")
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Name):
                        counted.add(arg.id)

        # A METHOD MAY ALSO COUNT ITSELF (FS-504). The original model was "main.py calls it
        # and passes the return value to metrics.record_*", which is how the three periodic
        # cleanups work. `_prune_oldest_sync` is called from inside `store()` on the
        # disk-full path — main.py never sees it — so under that model the only way to
        # satisfy the guard was to be excused by NOT_A_LOSS, which is how it came to carry a
        # reason that was not true. Counting at the point of deletion is the better shape,
        # and the guard now recognises it.
        self_counting = _methods_recording_their_own_loss()

        uncounted = []
        for name, line in sorted(_methods_deleting_messages().items()):
            if name in NOT_A_LOSS or name in self_counting:
                continue
            variables = [v for v, method in assigned.items() if method == name]
            if not variables:
                uncounted.append(
                    f"{name} (store_forward.py:{line}) — main.py never calls it, and it does "
                    f"not call metrics.record_* itself"
                )
            elif not any(v in counted for v in variables):
                uncounted.append(
                    f"{name} (store_forward.py:{line}) — its return value {variables} "
                    f"reaches no metrics.record_* call"
                )

        self.assertEqual(
            uncounted,
            [],
            "these buffer methods delete undelivered telemetry and nothing increments a "
            "Prometheus counter when they do:\n  "
            + "\n  ".join(uncounted)
            + "\nA loss visible only in a log file is invisible on a device that cannot "
            "reach the network — which is the only condition under which it happens.",
        )

    def test_the_expiry_counter_exists_and_moves(self):
        before = metrics.buffer_expired_total._value.get()
        metrics.record_expired(3)
        self.assertEqual(
            metrics.buffer_expired_total._value.get(),
            before + 3,
            "record_expired did not increment edge_buffer_expired_total",
        )

    def test_recording_zero_does_not_move_it(self):
        """A cleanup cycle that deleted nothing must not look like data loss — the counter
        is read as a rate, and a no-op that ticks it makes every quiet hour an incident."""
        before = metrics.buffer_expired_total._value.get()
        metrics.record_expired(0)
        self.assertEqual(metrics.buffer_expired_total._value.get(), before)


class TestExpiryIsReportedAsLoss(unittest.TestCase):
    def test_it_is_logged_at_warning(self):
        """INFO is for housekeeping. Deleting telemetry that never arrived is not
        housekeeping, and the two sibling paths in the same file both warn."""
        tree = ast.parse(STORE_FORWARD.read_text())
        levels = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "old_messages_cleaned"
            ):
                levels.add(node.func.attr)
        self.assertEqual(
            levels,
            {"warning"},
            f"the retention-expiry log is emitted at {levels or 'nothing'}; it deletes "
            f"undelivered telemetry and belongs at warning like its two siblings",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestEveryLossCounterIsAlertedOn(unittest.TestCase):
    """A counter nobody is paged on is invisible for a different reason (FS-458).

    Wiring the counter closes half the gap. The other half is that Prometheus scrapes it
    into a time series nobody looks at: `edge_buffer_dead_lettered_total` and
    `edge_buffer_dropped_total` each have an alert, and a third counter without one would
    be exactly as unnoticed as the log line it replaced — while looking, on the dashboard,
    like it had been handled.
    """

    ALERTS = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "infra"
        / "prometheus"
        / "alerts.yml"
    )

    def _loss_counters(self) -> set[str]:
        """Counter names declared in metrics.py that record a LOSS of messages."""
        tree = ast.parse((AGENT_DIR / "metrics.py").read_text())
        names = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Counter"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                name = node.args[0].value
                if name.startswith("edge_buffer_") and name.endswith("_total"):
                    names.add(name)
        return names

    def test_the_scan_finds_the_counters(self):
        self.assertGreaterEqual(
            len(self._loss_counters()), 3, "the metrics.py counter scan is broken"
        )

    def test_the_alerts_file_is_readable(self):
        self.assertTrue(self.ALERTS.exists(), f"{self.ALERTS} not found")
        self.assertIn("opsgrid_edge_collectors", self.ALERTS.read_text())

    def test_each_loss_counter_has_an_alert(self):
        alerts = self.ALERTS.read_text()
        unalerted = sorted(c for c in self._loss_counters() if c not in alerts)
        self.assertEqual(
            unalerted,
            [],
            f"these buffer loss counters are scraped and nothing alerts on them: "
            f"{unalerted}. A counter with no alert is a time series nobody looks at — "
            f"invisible for a different reason than the log line it replaced, while "
            f"looking on the dashboard like it was handled.",
        )



class TheDiskFullPruneActuallyIncrementsTheCounter(unittest.TestCase):
    """The structural guard above reads the AST. This drives the code (FS-504).

    A method can call `metrics.record_*` in a branch that never runs, or with a count it
    computed wrongly — the AST cannot tell. Up to 500 undelivered readings go per disk-full
    event, so the number has to be right, not merely present.
    """

    def test_pruning_reports_the_rows_it_deleted(self):
        import tempfile

        from opsgrid_agent import metrics
        from opsgrid_agent.buffer.store_forward import StoreForwardBuffer

        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = StoreForwardBuffer(buffer_path=os.path.join(tmpdir, "b.db"))

            # Six rows in, then prune four of them the way the disk-full handler does.
            for i in range(6):
                buffer._insert_row(
                    datetime.now(timezone.utc), f"a{i}", "telemetry", {"v": i}, i
                )

            recorded: list[int] = []
            original = metrics.record_dropped
            metrics.record_dropped = lambda n: recorded.append(n)
            try:
                pruned = buffer._prune_oldest_sync(4)
            finally:
                metrics.record_dropped = original

            self.assertEqual(pruned, 4, "the method did not report how many it deleted")
            self.assertEqual(
                recorded,
                [4],
                "the disk-full prune deleted undelivered rows and the dropped counter did "
                "not move by that amount. Before FS-504 it moved by nothing at all, and the "
                "allowlist excused it by claiming the hourly size-limit path counted them — "
                "which counts only rows its own DELETE removes.",
            )

    def test_pruning_nothing_reports_nothing(self):
        """The other direction: an empty buffer must not inflate the loss counter."""
        import tempfile

        from opsgrid_agent import metrics
        from opsgrid_agent.buffer.store_forward import StoreForwardBuffer

        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = StoreForwardBuffer(buffer_path=os.path.join(tmpdir, "b.db"))

            recorded: list[int] = []
            original = metrics.record_dropped
            metrics.record_dropped = lambda n: recorded.append(n)
            try:
                pruned = buffer._prune_oldest_sync(500)
            finally:
                metrics.record_dropped = original

            self.assertEqual(pruned, 0)
            self.assertEqual(recorded, [], "nothing was deleted, so nothing should be counted")
