"""Tests for title normalisation shared by all company sources."""

import pytest

from app.services.title_normalization import MAX_TITLE_LENGTH, normalise_title


@pytest.mark.parametrize("ticker", ["ANZ", "BHP", "CBA", "CSL", "WES"])
def test_all_supported_company_titles_have_a_safe_length(ticker: str) -> None:
    raw_title = f"{ticker} operational update " + ("descriptive card content " * 20)

    result = normalise_title(raw_title)

    assert len(result) <= MAX_TITLE_LENGTH
    assert result.endswith("…")


def test_descriptive_url_slug_extracts_headline_from_wrapped_card() -> None:
    raw_title = (
        "EXCHANGE RELEASES 20 January 2026 "
        "BHP Operational Review for the half year ended 31 December 2025 "
        "BHP delivered another half of very strong performance."
    )
    url = (
        "https://www.bhp.com/news/releases/"
        "bhp-operational-review-for-the-half-year-ended-31-december-2025"
    )

    assert normalise_title(raw_title, url) == (
        "BHP Operational Review for the half year ended 31 December 2025"
    )


def test_marketaux_title_is_also_length_limited() -> None:
    result = normalise_title(
        "Market news headline " + ("additional context " * 20),
        "https://publisher.example/article/12345",
    )

    assert len(result) <= MAX_TITLE_LENGTH
    assert result.startswith("Market news headline")
