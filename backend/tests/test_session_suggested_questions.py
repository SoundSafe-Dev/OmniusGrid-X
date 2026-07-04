"""Tests for suggested questions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.session_suggested_questions import generate_suggested_questions


def test_cross_tab_growth_question():
    sources = [
        {
            "file_name": "ops.xlsx",
            "processed_data": {
                "type": "spreadsheet",
                "filename": "ops.xlsx",
                "linking_metadata": {
                    "distinct_lines": ["Line 1"],
                    "year_labels": [2022, 2023, 2024],
                },
                "tabs": [
                    {
                        "name": "Finance",
                        "column_names": ["date", "revenue", "cost", "margin"],
                    },
                    {
                        "name": "Production_Operations",
                        "column_names": ["date", "production_line", "planned_units", "actual_units"],
                    },
                ],
            },
        }
    ]
    result = generate_suggested_questions(sources, limit=3)
    questions = result["questions"]
    assert len(questions) == 3
    joined = " ".join(questions).lower()
    assert "growth" in joined or "prepare" in joined or "bottleneck" in joined
    assert "finance" in joined or "production" in joined


def test_pdf_cross_reference_question():
    sources = [
        {
            "file_name": "ops.xlsx",
            "processed_data": {
                "type": "spreadsheet",
                "tabs": [
                    {
                        "name": "Production",
                        "column_names": ["line", "planned_units", "actual_units"],
                    }
                ],
                "linking_metadata": {"distinct_lines": ["Line A"]},
            },
        },
        {
            "file_name": "plan.pdf",
            "data_type": "report",
            "processed_data": {
                "type": "report",
                "subtype": "pdf",
                "pages": [{"text": "High season planning for Q4 orders and production capacity."}],
                "shared_keys": ["Q4"],
            },
        },
    ]
    result = generate_suggested_questions(sources, limit=3)
    joined = " ".join(result["questions"]).lower()
    assert "plan.pdf" in joined or "cross-reference" in joined or "high season" in joined
