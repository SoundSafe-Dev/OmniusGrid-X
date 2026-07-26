"""A heuristic must not be presented as a model inference.

`CorrelationAIEngine.analyze_scenario` tries Gemma and, on failure OR when
`CORRELATION_MODEL_ENABLED` is false (**the default**), substitutes
`_simulate_analysis`. That substitution was invisible:

  - the simulated output carried `confidence: 0.85` — the same value the real
    inference path reports;
  - its `model_version` was `"gemma-4-placeholder"`, which looks like a model;
  - the caller then logged `correlation_analysis_complete` with a risk score.

So every correlation the product showed was a heuristic labelled as an AI result, and
nothing in the payload, the UI or the logs could tell the difference. The AI tab was
unfalsifiable — the specific failure this codebase keeps producing, in the one place
where a confident wrong answer is most persuasive.

The heuristic is fine and useful. Presenting it as an inference is not. These tests
assert the distinction is carried in the payload, so a consumer can label it.

`correlation_ai_engine.py` is Harsh's area. The change under test is deliberately
minimal — a flag, a reason, and a confidence value — and touches no scoring or model
logic. This file exists so the property cannot quietly regress while that work
continues.
"""

from __future__ import annotations

import inspect

from app.services.correlation_ai_engine import CorrelationAIEngine


def _source(fn) -> str:
    return inspect.getsource(fn)


class TestSimulatedOutputIsLabelled:
    def test_the_simulated_analysis_declares_itself(self):
        source = _source(CorrelationAIEngine._simulate_analysis)
        assert '"simulated": True' in source, (
            "the heuristic fallback does not mark itself as simulated, so a caller "
            "cannot tell it from a Gemma inference"
        )

    def test_it_explains_why_it_is_simulated(self):
        """A bare boolean makes a UI say "simulated" with no reason. The distinction
        that matters to an operator is "the model is off" versus "the model failed"."""
        source = _source(CorrelationAIEngine._simulate_analysis)
        assert "simulation_reason" in source

    def test_it_no_longer_claims_inference_grade_confidence(self):
        """0.85 was what the real path reports. A heuristic reporting the same number
        is the whole problem in one field."""
        source = _source(CorrelationAIEngine._simulate_analysis)
        assert '"confidence": 0.85' not in source, (
            "the simulated analysis still reports 0.85 confidence, identical to a real "
            "inference"
        )

    def test_the_chat_fallback_is_labelled_too(self):
        """The conversational path has its own fallback, and it was equally silent."""
        source = _source(CorrelationAIEngine.__init__.__globals__["CorrelationAIEngine"])
        assert source.count('"simulated": True') >= 2, (
            "only one fallback path declares itself simulated; both must"
        )


class TestTheRealPathIsAlsoExplicit:
    def test_a_genuine_inference_says_simulated_false(self):
        """Present on BOTH paths, so a consumer can rely on the key rather than
        inferring "real" from its absence — absence is indistinguishable from an older
        payload, or from a bug."""
        source = inspect.getsource(CorrelationAIEngine)
        assert '"simulated": False' in source


class TestTheLogLineIsHonest:
    def test_analysis_complete_reports_whether_it_was_simulated(self):
        """`correlation_analysis_complete` with a risk score reads as a model result.
        It was emitted for heuristics too, so anyone auditing the logs to see whether
        the model was actually running could not find out."""
        source = _source(CorrelationAIEngine.analyze_scenario)
        assert "simulated=" in source, (
            "the completion log does not record whether the analysis was simulated"
        )
        assert "model_version=" in source


class TestTheDefaultMakesThisTheNormalCase:
    def test_the_correlation_model_is_disabled_by_default(self):
        """Not a criticism of the default — shipping disabled is sensible. It is why
        the labelling matters: with the model off, the SIMULATED path is what every
        deployment runs until someone explicitly enables it and provides an adapter.
        """
        from app.core.config import settings

        assert settings.CORRELATION_MODEL_ENABLED is False, (
            "if this is now enabled by default, confirm the adapter ships and is "
            "loadable — otherwise every analysis silently falls back"
        )
