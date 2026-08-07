"""A correlation score says what evidence it rests on (FS-534).

The sibling of FS-533, one layer in. Those were constants presented as measurements; these are
scores that ARE computed — partially — and presented as if completely.

## The root-cause correlation score

`_analyze_root_cause` seeds `correlation_score` at `0.5` with the comment
`# Default moderate correlation`, raises it by `0.15` per critical alarm during the operation
and `0.1` if a similar defect was logged before. Two problems, and the second is the one that
matters:

  * The anomaly term named in its own design is not computed — the source says
    `# Count telemetry anomalies / # (simplified - would do actual anomaly detection)`.
  * **With no asset supplied the function returns 0.5 having queried nothing at all**, and 0.5
    is also what it returns after examining an operation and finding no alarms. Identical
    number, opposite meanings: "we looked and found nothing" and "we never looked".

This is not transient. It is persisted onto `load_quality_logs.manufacturing_correlation_score`
and served from there, so it becomes the number a quality engineer reads months later when
deciding whether a shipping defect came from the line. FS-349 named this exact failure — a
report carrying a `model_version` for a model that was never loaded — and the fix was to say so
in the payload.

**The basis has to outlive the transaction.** The first version of this fix returned `basis`
from `_analyze_root_cause` and the caller passed only the number to the constructor, so the
qualification existed for the length of one function call and the bare 0.5 was still what got
stored. A basis that does not survive the write qualifies nothing. It goes into `meta_data`,
which is the existing home for per-row provenance on this table.

## The shipping-readiness score

`_score_asset_for_shipment` reads PackML state, estimates operation completion, and counts
recent quality issues — all real queries. Then:

    # Check asset OEE (would need actual OEE calculation)
    # For now, use placeholder

and **nothing happens**. There is no placeholder. The comment describes a stand-in that does
not exist, which is worse than either doing the work or omitting it, because a reader takes it
for a known approximation.

`factors` is the function's own explanation of its score and is returned to the caller. It
listed every term that was applied and stayed silent about the one that was not — so a score
built from three of four inputs read as a complete assessment. The omission is now stated
through the mechanism that was already there.
"""

from __future__ import annotations

import inspect

import pytest

from app.services import logistics_correlation_engine as engine_module


def _source(name: str) -> str:
    """The source of a method on whichever class in the module defines it.

    Looked up by name across the module rather than off the engine instance: the first
    version of this file did `engine._analyze_root_cause` and raised AttributeError, because
    the method lives on `LoadQualityCorrelator` and the engine composes it. A test that
    cannot find its own subject reports nothing.
    """
    for obj in vars(engine_module).values():
        if inspect.isclass(obj) and hasattr(obj, name):
            return inspect.getsource(getattr(obj, name))
    raise AssertionError(
        f"no class in {engine_module.__name__} defines {name!r} — this guard has lost its "
        f"subject and every assertion below would be vacuous"
    )


class TestTheGuardFoundItsSubjects:
    @pytest.mark.parametrize(
        "name", ["_analyze_root_cause", "_score_asset_for_shipment", "log_quality_issue"]
    )
    def test_each_method_is_reachable(self, name: str):
        assert _source(name)


class TestTheRootCauseScoreSaysWhatItExamined:
    def test_it_returns_a_basis(self):
        source = _source("_analyze_root_cause")
        assert "'basis'" in source, (
            "the root-cause result no longer carries a basis. 0.5 means both 'examined and "
            "found no alarms' and 'no asset was supplied so nothing was queried', and only "
            "the basis distinguishes them."
        )

    def test_the_no_evidence_case_is_named(self):
        source = _source("_analyze_root_cause")
        assert "no_evidence_examined" in source, (
            "the initial basis is not `no_evidence_examined`. A defect logged with no asset "
            "returns 0.5 having queried nothing, and `# Default moderate correlation` is how "
            "that read for as long as it existed."
        )

    def test_examining_and_finding_nothing_is_distinguishable(self):
        source = _source("_analyze_root_cause")
        assert "no_critical_alarms_during_operation" in source, (
            "the 'we looked and found nothing' case is not distinguished from the 'we never "
            "looked' case, and both produce 0.5"
        )

    def test_the_missing_anomaly_term_is_declared(self):
        source = _source("_analyze_root_cause")
        assert "anomaly_detection_applied" in source, (
            "the result does not declare that the anomaly-detection term named in this "
            "function's own design is not computed"
        )

    def test_the_basis_is_persisted_with_the_score(self):
        """The half that would silently not happen. The score is stored and served; a basis
        that lives only inside one function call qualifies nothing a reader will ever see."""
        source = _source("log_quality_issue")
        assert "correlation_basis" in source, (
            "`manufacturing_correlation_score` is written to the row and its basis is not. "
            "The qualification then exists for the length of one function call, and the bare "
            "number is what a quality engineer reads months later."
        )
        assert "meta_data" in source, (
            "nothing carries the provenance onto the row; `meta_data` is the column for it"
        )


class TestTheReadinessScoreDeclaresWhatItOmits:
    def test_the_placeholder_comment_is_gone(self):
        source = _source("_score_asset_for_shipment")
        assert "For now, use placeholder" not in source, (
            "the comment claiming a placeholder is back. There was no placeholder — the "
            "comment described a stand-in that does not exist, which reads as a known "
            "approximation rather than a missing term."
        )

    def test_the_omission_is_in_the_response(self):
        source = _source("_score_asset_for_shipment")
        assert "terms_omitted" in source, (
            "the readiness result does not declare which terms are missing from it"
        )
        assert "asset_oee" in source

    def test_it_is_stated_in_the_factors_the_caller_reads(self):
        """`factors` is this function's own explanation and is what a UI renders. Declaring
        the omission only in a sibling key would leave the human-readable list still claiming
        to be complete."""
        source = _source("_score_asset_for_shipment")
        assert 'factors.append("OEE not included' in source, (
            "`factors` lists every term that WAS applied and is silent about the one that "
            "was not, so a score from three of four inputs reads as a complete assessment"
        )
