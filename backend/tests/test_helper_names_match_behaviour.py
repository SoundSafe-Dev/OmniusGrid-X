"""A helper called `_create_*` or `_send_*` must actually create or send something.

THE DEFECT CLASS. A name asserting a side effect, over a body that only logs. The
call site then reads exactly as though the work happened, and nothing at runtime
contradicts it. This is the sibling of `subscribe_to_events` returning `True` for a
subscription it never created — but where that one lied in a return value, this one
lies in the identifier, which no log-scanning or response-shape guard would catch.

FOUND FIRST IN ERP. `sap_webhook_integration` had `_create_alert_for_po_anomaly`,
`_create_alert_for_po_status_change` and `_create_alert_for_low_inventory`. None
created an alert; each was a single `logger.warning` under a comment reading *"This
would integrate with the alarm/alert system."* What made it genuinely misleading is
that `_create_task_for_work_order`, in the same class twenty lines away, **does**
create a `Task`. A reader who checked one had every reason to assume the others
matched. Those three are now `_log_*`.

THEN SWEPT ACROSS `app/`, WHICH FOUND A WORSE ONE. 129 claiming helpers; two bodies
that only log. `utils/signed_urls._emit_fallback_warning` is honest — emitting a
warning *is* logging, and it is excluded below by name. The other was
`tactical_engine._send_command`, in the autonomous control path:

    await self._send_command(decision)          # built a dict, logged at DEBUG
    logger.info("tactical_decision_executed")   # ...for a command never sent
    return True                                 # docstring: "True if executed"

The two safety gates directly above it — maintenance-mode and the 0.7 confidence
floor — are implemented properly, the first even failing SAFE under a comment reading
*"a broken control command is worse than a skipped one."* Same trap as the SAP case,
with actuation of industrial assets behind it. It is now `_dispatch_command`, returns
False, and `execute_decision` returns False with it.

THE RULE. A helper whose name claims a side effect must produce one, or be named for
what it does. Refusing loudly is fine; claiming silently is not.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Iterator, List, Tuple

import pytest

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "app"

#: Verbs that assert a side effect beyond logging.
CLAIMING_PREFIXES = (
    "_create_", "create_", "_persist_", "persist_", "_store_", "store_",
    "_send_", "send_", "_write_", "write_", "_save_", "save_",
    "_publish_", "publish_", "_emit_", "emit_",
)

#: Helpers whose object IS a log line. `_emit_fallback_warning` emits a warning, and a
#: warning is a log — the name is accurate, so flagging it would be the false positive.
NAMES_WHOSE_OBJECT_IS_A_LOG = re.compile(r"_(warning|warn|error|log|message|notice)$")

#: Calls that are themselves logging.
LOGGING_CALLS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}

#: Calls that compute rather than act, so they do not rescue a log-only body.
PURE_CALLS = {
    "get", "format", "join", "len", "str", "int", "float", "bool", "isoformat",
    "append", "keys", "values", "items", "strip", "lower", "upper", "split", "sorted",
}


def only_logs(fn) -> bool:
    """Does this function do nothing but log?

    PRECISE ON PURPOSE, AND THE OPPOSITE QUESTION DOES NOT WORK. The first version of
    this check asked "does it call something from a list of doing-verbs?" and produced
    three false positives immediately, in three flavours of delegation it could not
    see: `create_from_config` constructs an object, `_persist_rotated_refresh_token`
    calls an injected callable, `_send_alert` calls a notification service. All three
    are honest; the detector was not.

    Asking "is logging ALL it does?" needs no list of approved verbs, so delegation of
    any shape passes — while still catching the defect exactly, because the real ones
    were a `logger.warning` and nothing else.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in LOGGING_CALLS or name in PURE_CALLS:
            continue
        return False  # it calls something real
    return True


def _functions() -> Iterator[Tuple[pathlib.Path, ast.AST]]:
    for path in sorted(APP_ROOT.glob("**/*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # an unparseable module is another test's problem
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield path, node


CLAIMERS: List[Tuple[pathlib.Path, ast.AST]] = [
    (path, fn)
    for path, fn in _functions()
    if fn.name.startswith(CLAIMING_PREFIXES)
    and not NAMES_WHOSE_OBJECT_IS_A_LOG.search(fn.name)
]


class TestTheGuardIsNotVacuous:
    def test_it_finds_claiming_helpers_to_check(self):
        """A rename, a moved package or a broken glob would otherwise make every
        assertion below pass while checking nothing — which is how the originals
        survived in the first place."""
        assert len(CLAIMERS) >= 80, (
            f"only {len(CLAIMERS)} create/send/persist helpers discovered across app/; "
            f"the sweep is not reaching them and would pass vacuously"
        )

    def test_it_reaches_more_than_one_package(self):
        packages = {p.relative_to(APP_ROOT).parts[0] for p, _fn in CLAIMERS}
        assert len(packages) >= 3, f"sweep confined to {packages}"

    def test_the_detector_recognises_real_work(self):
        """`_create_task_for_work_order` genuinely creates a `Task`. If the detector
        cannot see that, every assertion in this file is meaningless."""
        real = [fn for _p, fn in CLAIMERS if fn.name == "_create_task_for_work_order"]
        assert real, "_create_task_for_work_order not found; has it been renamed?"
        assert not only_logs(real[0]), "the detector cannot see a function that really works"

    def test_the_detector_catches_a_log_only_helper(self):
        """Reconstructs the exact shape that shipped, so the check is proven able to
        fail rather than merely passing today."""
        tree = ast.parse(
            "async def _create_alert_for_po_anomaly(self, db, po, result):\n"
            "    logger.warning('po_anomaly_alert', po_number=po.get('po_number'))\n"
        )
        assert only_logs(tree.body[0]), "the detector no longer catches a log-only helper"

    def test_the_detector_is_not_fooled_by_a_dict_of_data(self):
        """`_send_command` built a full command dict before logging. Assembling the
        payload must not read as sending it — that is precisely how it looked wired."""
        tree = ast.parse(
            "async def _send_command(self, decision):\n"
            "    command = {'asset_id': decision.asset_id,\n"
            "               'timestamp': decision.timestamp.isoformat()}\n"
            "    logger.debug('command_queued', command=command)\n"
        )
        assert only_logs(tree.body[0]), "payload assembly is being mistaken for dispatch"


@pytest.mark.parametrize(
    "path,fn",
    CLAIMERS,
    ids=[f"{p.stem}.{f.name}" for p, f in CLAIMERS],
)
def test_a_helper_that_claims_a_side_effect_produces_one(path, fn):
    assert not only_logs(fn), (
        f"{path.name}::{fn.name} (line {fn.lineno}) is named as though it creates, "
        f"sends or persists something, but its body only logs. The call site reads as "
        f"though the work happened — that is the defect, not the missing feature. "
        f"Either implement it, or rename it for what it does and make the caller see "
        f"the refusal (see _log_po_anomaly in sap_webhook_integration.py, and "
        f"_dispatch_command in tactical_engine.py, which returns False)."
    )
