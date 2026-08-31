"""Regression tests for structured summary persistence and recovery."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crud.artifact import store_artifact_analysis
from app.services.summary_metadata import (
    combine_summary_text,
    has_complete_summary_metadata,
    normalise_summary_metadata,
    split_combined_summary_text,
)


def _structured_summary() -> dict:
    return {
        "summary": "The company announced an update.",
        "about": "The filing covers the update.",
        "changed": "A new program was announced.",
        "matters": "The program may affect investors.",
        "confirmed_facts": ["The company announced the program."],
        "speculation": ["The program may affect investors."],
    }


def test_structured_summary_round_trip_preserves_display_fields() -> None:
    summary = _structured_summary()

    normalised = normalise_summary_metadata(summary)
    combined = combine_summary_text(normalised)

    assert has_complete_summary_metadata(normalised) is True
    assert split_combined_summary_text(combined) == {
        key: summary[key] for key in ("summary", "about", "changed", "matters")
    }


def test_combined_summary_recovery_rejects_ambiguous_text() -> None:
    assert split_combined_summary_text("Only one paragraph") == {}
    assert split_combined_summary_text("One\n\nTwo\n\nThree") == {}


def test_analysis_storage_merges_fields_and_records_prompt_version() -> None:
    artifact_id = uuid4()
    artifact = SimpleNamespace(
        raw_text=None,
        artifact_metadata={"category": "UNKNOWN"},
    )
    summary_row = SimpleNamespace(
        summary_text="old",
        model_used=None,
        prompt_version=None,
        confidence_score=None,
    )
    artifact_query = MagicMock()
    artifact_query.filter.return_value.with_for_update.return_value.first.return_value = (
        artifact
    )
    summary_query = MagicMock()
    summary_query.filter.return_value.first.return_value = summary_row
    db = MagicMock()
    db.query.side_effect = [artifact_query, summary_query]
    summary = {
        **_structured_summary(),
        "summary_text": combine_summary_text(_structured_summary()),
        "model_used": "bedrock:test-model",
        "prompt_version": "llm-announcement-summary-v3",
    }

    result = store_artifact_analysis(
        db,
        artifact_id=artifact_id,
        raw_text="Stored filing text",
        metadata={"page_count": 2},
        summary=summary,
    )

    assert result is artifact
    assert artifact.raw_text == "Stored filing text"
    assert artifact.artifact_metadata["about"] == "The filing covers the update."
    assert artifact.artifact_metadata["confirmed_facts"] == [
        "The company announced the program."
    ]
    assert summary_row.prompt_version == "llm-announcement-summary-v3"
    assert summary_row.model_used == "bedrock:test-model"
    db.commit.assert_called_once()
