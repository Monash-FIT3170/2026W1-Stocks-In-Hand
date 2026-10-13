"""Regression tests for structured summary persistence and recovery."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

