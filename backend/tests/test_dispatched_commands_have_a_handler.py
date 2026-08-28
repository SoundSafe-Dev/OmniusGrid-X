"""Every command the cloud dispatches has a handler on the agent (FS-505).

THE DEFECT. `rollout_orchestrator._dispatch` picks the action by artifact type:

    action_id = "model_update" if release.artifact_type == "model" else "agent_update"

The edge agent registers its handlers in `main.py`, and registers exactly one:
`OTAUpdateExecutor.register` binds **`agent_update`** (`edge-agent/opsgrid_agent/ota/executor.py:68`).
`ModelUpdateExecutor.register` binds `model_update`
(`edge-agent/opsgrid_agent/ota/model_executor.py:68-70`) and **the class is never instantiated**
— `grep ModelUpdateExecutor` finds only its own definition.

So a model rollout is dispatched by the cloud, reaches the device, and is answered
`{"error": "unknown_action"}` (`edge-agent/opsgrid_agent/commands/consumer.py:149-155`). The
rollout then records a failure for a device that is working perfectly.

AND A COMMENT ASSERTS OTHERWISE. `app/api/health.py:728` says, as a statement of fact, that
"the edge agent registers exactly two command handlers: `agent_update` and `model_update`",
and uses that to justify a decision. It is half true, which is the kind that survives review.

WHY THIS GUARD IS HERE AND NOT IN THE AGENT. Neither side can see the pair. The backend knows
which actions it dispatches; the agent knows which it registers; nothing compared them. That
is the same shape as the truncation-signal sweep (FS-485) and the ERP connector list
(FS-486) — two lists that must agree, and no one place that reads both.

WHAT IS NOT FIXED HERE. Wiring `ModelUpdateExecutor` into `main.py` is three lines, and it is
**not done in this commit**: OTA is another lane, and the executor has no tests at all
(FS-507), so switching an untested 220-line handler into the live command path is not a
defect fix. The exemption below carries that reason and a date, so the gap is visible and
finite rather than silent.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
ORCHESTRATOR = REPO / "backend" / "app" / "services" / "rollout_orchestrator.py"
AGENT_DIR = REPO / "edge-agent" / "opsgrid_agent"
AGENT_MAIN = AGENT_DIR / "main.py"

#: Actions the cloud dispatches that the agent does not handle, with why and until when.
#:
#: An entry here is a device that answers `unknown_action` to a command the product believes
#: it supports — so it is a promise to fix, not a permanent excuse.
UNHANDLED_BY_AGENT = {
    "model_update": (
        "ModelUpdateExecutor (edge-agent/opsgrid_agent/ota/model_executor.py) is fully "
        "written and binds this action in `register()`, but main.py never constructs it, so "
        "the agent answers `unknown_action` to every model rollout. "
        "\n\n"
        "OWNER: Hamad since 2026-08-28, when the OTA lane moved. Acting on it found the "
        "entry's own remedy to be WRONG, which is why this text is longer than it was. "
        "\n\n"
        "THE 'WIRING IS ~3 LINES' CLAIM WAS TRUE AND MISLEADING. Registering the executor "
        "is three lines, and doing only that would be worse than the present bug. Nothing "
        "on the agent consumes a model artifact: there is no inference runtime, `analytics/` "
        "is statistical (anomaly detection, OEE), and no module outside the executor reads "
        "`active_model_path` — grep it. So the executor's `swap_callback` would be None, "
        "`_swap` would return immediately, and the handler would report SUCCESS for a file "
        "nothing will ever load. `unknown_action` is currently a truthful failure against "
        "working hardware; wiring alone converts it into a false success, and the fleet view "
        "would show a model live on every device that cannot run it. A loud wrong answer is "
        "worth more than a quiet one. "
        "\n\n"
        "WHAT IS ACTUALLY MISSING is a device-side consumer, not a registration. When one "
        "exists, wiring is safe and cheap: the executor is no longer untested — "
        "`edge-agent/tests/test_model_executor.py` (2026-08-28) covers apply, checksum and "
        "signature refusal, all six required parameters against what "
        "`rollout_orchestrator` actually sends, the concurrency lock, and the property that "
        "matters most, that a failed hot-swap restores the previous model rather than "
        "stranding the device. This entry stays open, and it is now about the runtime "
        "rather than about three lines. "
        "\n\n"
        "(The '(FS-507)' this text used to carry was a MIS-CITATION, copied into three "
        "places from DELIVERY-LOG.md:5889. FS-507 is the HTTP-collector slice at "
        "DELIVERY-LOG.md:5938 and was closed by the 2026-08-28 OTA merge. The model "
        "executor being untested was recorded beside it and never had a number. A wrong "
        "reference in an allowlist sends the next reader to the wrong slice, which is "
        "worse than no reference.)"
    ),
}


def _values_of(node: ast.expr) -> set[str]:
    """The string literals an expression can evaluate TO — not the ones it tests against.

    The orchestrator's assignment is a ternary:

        action_id = "model_update" if release.artifact_type == "model" else "agent_update"

    A regex over that line returns `model` as well, which is an artifact type, not an action.
    Descending into `body`/`orelse` and never into `test` is the difference between reading
    what the code sends and reading what it asks about — and the first version of this reader
    got it wrong, which would have reported a phantom unhandled action forever.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _values_of(node.body) | _values_of(node.orelse)
    if isinstance(node, ast.BoolOp):
        return set().union(*(_values_of(v) for v in node.values))
    # A DICT LOOKUP WITH A DEFAULT, which is what the ternary became on 2026-08-08:
    #
    #     action_id = {"model": "model_update",
    #                  "agent": "agent_self_update"}.get(release.artifact_type, "agent_update")
    #
    # The reachable actions are the dict's VALUES plus the default — never its keys, which
    # are artifact types and exactly the confusion the ternary version already had to avoid.
    # Reading only `Constant` and `IfExp` made this return nothing, and a reader that finds
    # nothing reports every action handled: the guard would have gone quiet on the same day
    # the code grew a third action.
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        values: set[str] = set()
        if isinstance(node.func.value, ast.Dict):
            for v in node.func.value.values:
                values |= _values_of(v)
        for arg in node.args[1:]:
            values |= _values_of(arg)
        return values
    if isinstance(node, ast.Dict):
        return set().union(*(_values_of(v) for v in node.values)) if node.values else set()
    return set()


def _dispatched_actions() -> set[str]:
    """Action ids the orchestrator can assign to a command."""
    tree = ast.parse(ORCHESTRATOR.read_text())
    actions: set[str] = set()
    for node in ast.walk(tree):
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign)
            else []
        )
        if any(isinstance(t, ast.Name) and t.id == "action_id" for t in targets):
            actions |= _values_of(node.value)
    assert actions, "no `action_id = ...` assignment found in rollout_orchestrator.py"
    return actions


def _registered_handlers() -> set[str]:
    """Action ids the agent binds, following each executor `main.py` actually constructs.

    Reading `register_handler` calls across the whole package would count handlers on classes
    nothing instantiates — which is precisely the defect, so the walk has to start from what
    `main.py` builds.
    """
    main_source = AGENT_MAIN.read_text()
    constructed = {
        node.func.id
        for node in ast.walk(ast.parse(main_source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    registered: set[str] = set()
    for path in AGENT_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef) or cls.name not in constructed:
                continue
            for call in ast.walk(cls):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "register_handler"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                ):
                    registered.add(call.args[0].value)
    return registered


class TestTheReadersAreNotVacuous:
    def test_the_orchestrator_dispatches_something(self):
        actions = _dispatched_actions()
        assert len(actions) >= 2, (
            f"only {actions} parsed out of rollout_orchestrator.py; the reader is broken and "
            f"the comparison below would pass over an empty set"
        )
        assert "agent_update" in actions

    def test_the_agent_registers_something(self):
        registered = _registered_handlers()
        assert registered, (
            "no command handlers found on any executor main.py constructs. Either the agent "
            "stopped registering handlers entirely, or the AST walk broke — and a broken "
            "walk here reports every dispatched action as unhandled."
        )
        assert "agent_update" in registered, (
            f"agent_update is not registered by anything main.py builds; found {registered}"
        )


class TestEveryDispatchedActionIsHandled:
    def test_no_command_is_dispatched_into_the_void(self):
        unhandled = sorted(_dispatched_actions() - _registered_handlers() - set(UNHANDLED_BY_AGENT))
        assert not unhandled, (
            f"the orchestrator dispatches {unhandled} and no executor that main.py constructs "
            f"registers a handler for it, so the device answers `unknown_action` and the "
            f"rollout records a failure against hardware that is working. Wire the handler, "
            f"or add it to UNHANDLED_BY_AGENT with an owner and a reason."
        )

    @pytest.mark.parametrize("action", sorted(UNHANDLED_BY_AGENT))
    def test_each_exemption_is_still_needed(self, action: str):
        """A stale exemption is how an allowlist stops describing the code and starts
        excusing it — which FS-504 had just cost a buffer counter."""
        assert action not in _registered_handlers(), (
            f"{action} is handled now, so the exemption in UNHANDLED_BY_AGENT is stale. "
            f"Delete it — the gap it describes is closed."
        )

    @pytest.mark.parametrize("action", sorted(UNHANDLED_BY_AGENT))
    def test_each_exemption_is_still_dispatched(self, action: str):
        assert action in _dispatched_actions(), (
            f"{action} is exempted here and the orchestrator no longer dispatches it; the "
            f"entry describes nothing"
        )


class TestTheDocumentedClaimMatchesTheCode:
    def test_health_py_does_not_overstate_the_agents_handlers(self):
        """`api/health.py` justified removing an endpoint by asserting the agent registers
        two handlers. It registers one. A decision resting on a false premise is worth
        catching even when the decision itself was right."""
        source = (REPO / "backend" / "app" / "api" / "health.py").read_text()
        registered = _registered_handlers()
        claimed = re.search(
            r"registers exactly (\w+) command handlers?: ([^\n]+)", source
        )
        if claimed is None:
            return  # the sentence was reworded; nothing to hold to account
        named = set(re.findall(r"`([a-z_]+)`", claimed.group(2)))
        overstated = sorted(named - registered - set(UNHANDLED_BY_AGENT))
        assert not overstated, (
            f"health.py claims the agent registers {sorted(named)}; it registers "
            f"{sorted(registered)}. Overstated: {overstated}"
        )
