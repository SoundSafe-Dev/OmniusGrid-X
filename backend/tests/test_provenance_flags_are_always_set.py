"""A response that carries a provenance flag must always set it.

THE SHAPE. `SessionChatResponse.simulated` defaults to `False`, which is a claim: *this
was a genuine inference*. Two of the three constructions in `session_chat` carried the
engine's real value through, with a comment saying so — "never defaulted to False here".
The third was the **exception handler**, and it built the response without those fields
at all. So the one reply that was not an analysis in any sense was the only one asserting
that it was, and it is the live path today because the correlation model and its LoRA
adapter are deliberately not loaded.

WHY A DEFAULT IS THE WRONG PLACE FOR THIS. A default is what you get when nobody thought
about the field, and the moment that matters most — a handler written in a hurry to stop
a 500 — is exactly when nobody thinks about it. `False` is not a neutral value here; it
is the strongest claim the model can make. This guard makes the omission a test failure
instead of a silently confident answer.

SCOPE, AND WHY IT IS SMALL. Exactly one model declares such a field today. That is worth
knowing on its own: the platform has one place where output tells you how much to trust
it, and the OEE numbers (`performance = 1.0`, `quality = 1.0` hardcoded) are a standing
candidate for a second. The guard is written to cover the field NAMES rather than the one
model, so adding `availability_only` or `degraded` anywhere brings it under the rule
automatically.

WHAT IT CANNOT SEE. A construction using `**kwargs`, which is skipped and counted — the
flag could be in the dict or not, and guessing either way would make the count a lie.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Dict, List, Set, Tuple

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: Fields whose value is a statement about how much the result can be trusted.
#: A default for any of these is a claim made on the author's behalf.
PROVENANCE_FIELDS = {
    "simulated",
    "is_simulated",
    "is_mock",
    "degraded",
    "fallback",
    "is_fallback",
    "estimated",
    "partial",
    "availability_only",
}


def _declaring_models() -> Dict[str, Set[str]]:
    """class name -> the provenance fields it annotates."""
    models: Dict[str, Set[str]] = {}
    for path in sorted(APP.glob("**/*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # another test's problem
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            annotated = {
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            }
            declared = annotated & PROVENANCE_FIELDS
            if declared:
                models[node.name] = declared
    return models


MODELS = _declaring_models()


def _constructions() -> Tuple[List[tuple], int]:
    """((file, line, class, missing fields)), plus the count skipped for **kwargs."""
    found: List[tuple] = []
    spread = 0
    for path in sorted(APP.glob("**/*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            declared = MODELS.get(node.func.id)
            if not declared:
                continue
            if any(keyword.arg is None for keyword in node.keywords):
                # `Model(**payload)` — the flag may or may not be in the dict.
                spread += 1
                continue
            given = {keyword.arg for keyword in node.keywords}
            missing = declared - given
            if missing:
                found.append(
                    (
                        str(path.relative_to(APP.parent)),
                        node.lineno,
                        node.func.id,
                        sorted(missing),
                    )
                )
    return found, spread


OMISSIONS, SPREAD_CONSTRUCTIONS = _constructions()


class TestTheSweepIsNotVacuous:
    def test_it_finds_the_models_that_declare_a_flag(self):
        assert MODELS, (
            "no model declares a provenance field. Either the sweep is broken, or "
            f"every one of {sorted(PROVENANCE_FIELDS)} was renamed — in which case this "
            f"guard is protecting nothing and the names need updating"
        )

    def test_the_known_model_is_discovered(self):
        assert "simulated" in MODELS.get("SessionChatResponse", set()), (
            "SessionChatResponse no longer declares `simulated`; the sweep would pass "
            "while the property it exists for had been removed"
        )

    def test_the_detector_can_see_an_omission(self):
        """Proves the check can fail. Built from the same AST walk the sweep uses, so
        a change that breaks the walk breaks this too."""
        module = ast.parse("SessionChatResponse(role='assistant', content='x')")
        call = module.body[0].value
        given = {keyword.arg for keyword in call.keywords}
        assert MODELS["SessionChatResponse"] - given == {"simulated"}

    def test_spread_constructions_are_reported_not_hidden(self, capsys):
        """`Model(**payload)` cannot be read statically. Counted rather than dropped —
        a guard that silently ignores what it cannot parse reports coverage it does not
        have, which is the failure this whole file is about."""
        with capsys.disabled():
            print(
                f"\n  provenance sweep: {len(MODELS)} model(s) with a flag, "
                f"{SPREAD_CONSTRUCTIONS} construction(s) skipped (**kwargs)"
            )
        assert SPREAD_CONSTRUCTIONS <= 3, (
            f"{SPREAD_CONSTRUCTIONS} constructions pass **kwargs and cannot be checked"
        )


class TestEveryConstructionStatesItsProvenance:
    def test_no_construction_relies_on_the_default(self):
        assert not OMISSIONS, (
            "These build a response carrying a provenance flag without setting it, so "
            "the field falls back to its default — and for `simulated` the default is "
            "`False`, the strongest claim the model can make. Set it explicitly, "
            "including on error paths:\n  "
            + "\n  ".join(
                f"{path}:{line} {model} omits {fields}"
                for path, line, model, fields in OMISSIONS
            )
        )


class TestTheFlagIsNotWriteOnly:
    """A flag nobody reads is decoration. These pin the two places that consume it."""

    def test_the_api_carries_the_engine_value_through(self):
        source = (APP / "api" / "analysis_sessions.py").read_text()
        assert 'simulated=bool(analysis_result.get("simulated", False))' in source, (
            "the chat handler no longer reads the engine's flag; it would report every "
            "heuristic as a real inference again"
        )

    def test_the_error_path_marks_itself(self):
        source = (APP / "api" / "analysis_sessions.py").read_text()
        assert "simulated=True," in source, (
            "no construction sets simulated=True. The exception fallback returns a reply "
            "that is not an analysis at all and must say so"
        )


class TestTheFlagReachesAHuman:
    """The chain has four links — engine, handler, TypeScript type, rendered message —
    and it was broken at the third: `SessionChatResponse` in `analysisSessions.ts` did
    not declare these fields, so the server's "do not read this as an inference" was
    dropped by the client that asked for it. A flag the operator never sees is the same
    as no flag, which is the failure this whole class is about.
    """

    FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"

    def test_the_typescript_response_type_declares_it(self):
        source = (self.FRONTEND / "api" / "analysisSessions.ts").read_text()
        assert "simulated?: boolean;" in source, (
            "SessionChatResponse does not declare `simulated`, so the field is dropped "
            "at the client boundary no matter what the server sends"
        )

    def test_the_mock_branch_admits_it_is_a_mock(self):
        """`VITE_USE_MOCK` output is simulated by definition. Reporting `false` there
        would make the demo the most confident surface in the product."""
        source = (self.FRONTEND / "api" / "analysisSessions.ts").read_text()
        assert "simulated: true" in source

    def test_the_chat_pane_renders_the_flag(self):
        source = (self.FRONTEND / "components" / "nlp" / "CorrelationAIPane.tsx").read_text()
        assert "message.simulated" in source, (
            "the chat pane no longer reads `simulated`; heuristic and error-fallback "
            "replies would render identically to a real inference"
        )
        assert "simulation_reason" in source, (
            "the badge shows no reason; 'not an inference' without a why leaves the "
            "operator unable to act on it"
        )
