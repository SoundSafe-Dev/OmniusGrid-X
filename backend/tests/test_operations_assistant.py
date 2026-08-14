"""Focused guards for the Operations Lead approval and evidence handoff."""

from app.api.correlation_evidence import EvidencePreviewRequest
from app.api.operations_assistant import (
    _citation_evidence,
    _evidence_has_confirmed_join,
    _request_has_confirmed_join,
)


def _request(**overrides):
    payload = {
        "intake_ids": ["00000000-0000-0000-0000-000000000001"],
        **overrides,
    }
    return EvidencePreviewRequest(**payload)


def test_operations_questions_require_an_explicitly_confirmed_join_request():
    proposed = {
        "left": {"source_id": "production", "table_name": "Production"},
        "right": {"source_id": "maintenance", "table_name": "Maintenance"},
        "keys": [{"canonical_name": "asset_id", "left_column": "Asset ID", "right_column": "Machine ID", "strategy": "exact"}],
    }

    assert not _request_has_confirmed_join(_request())
    assert not _request_has_confirmed_join(_request(join_plan=proposed))
    assert _request_has_confirmed_join(_request(join_plan=proposed, confirm_join_plan=True))
    assert _request_has_confirmed_join(_request(join_plans=[proposed], confirm_join_plan=True))


def test_operations_questions_only_accept_materialized_confirmed_evidence():
    assert not _evidence_has_confirmed_join({"join_plan": {"approval_state": "proposed"}})
    assert _evidence_has_confirmed_join({"join_plan": {"approval_state": "confirmed"}})
    assert not _evidence_has_confirmed_join({
        "evidence_sets": [
            {"join_plan": {"approval_state": "confirmed"}},
            {"join_plan": {"approval_state": "proposed"}},
        ]
    })
    assert _evidence_has_confirmed_join({
        "evidence_sets": [
            {"join_plan": {"approval_state": "confirmed"}},
            {"join_plan": {"approval_state": "confirmed"}},
        ]
    })


def test_operations_citation_evidence_returns_only_cited_rows():
    evidence = {
        "_operations_source_rows": [
            {
                "evidence_id": "source:safety:1",
                "match_status": "source_row",
                "lineage": [{"source_id": "safety", "table_name": "Safety", "row_number": 1}],
                "fields": {"safety/Safety.incident_count": 3},
            },
            {
                "evidence_id": "source:safety:2",
                "match_status": "source_row",
                "lineage": [{"source_id": "safety", "table_name": "Safety", "row_number": 2}],
                "fields": {"safety/Safety.incident_count": 0},
            },
        ]
    }
    answer = {
        "citations": [{"evidence_id": "source:safety:1"}],
        "checklist": [],
    }

    resolved = _citation_evidence(answer, evidence)

    assert list(resolved) == ["source:safety:1"]
    assert resolved["source:safety:1"]["fields"]["safety/Safety.incident_count"] == 3

