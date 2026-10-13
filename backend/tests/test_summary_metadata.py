"""Regression tests for structured summary persistence and recovery."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.summary_metadata import split_combined_summary_text


def test_combined_summary_recovery_rejects_ambiguous_text() -> None:
    assert split_combined_summary_text("Only one paragraph") == {}
    assert split_combined_summary_text("One\n\nTwo\n\nThree") == {}
