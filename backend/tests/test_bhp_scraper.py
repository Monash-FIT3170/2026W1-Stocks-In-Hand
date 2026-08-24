"""Focused tests for BHP announcement title extraction."""

from scrapers.companies.bhp import clean_bhp_title


def test_clean_bhp_title_removes_card_labels_date_and_description() -> None:
    raw_title = (
        "EXCHANGE RELEASES FINANCIAL RESULTS AND OPERATIONAL REVIEWS "
        "20 January 2026 "
        "BHP Operational Review for the half year ended 31 December 2025 "
        "BHP delivered another half of very strong performance with operational "
        "records at our copper and iron ore assets."
    )
    url = (
        "https://www.bhp.com/news/media-centre/releases/2026/01/"
        "bhp-operational-review-for-the-half-year-ended-31-december-2025"
    )

    assert clean_bhp_title(raw_title, url) == (
        "BHP Operational Review for the half year ended 31 December 2025"
    )


def test_clean_bhp_title_uses_descriptive_url_slug_as_fallback() -> None:
    assert clean_bhp_title(
        "Exchange release 20 January 2026",
        "https://www.bhp.com/news/releases/bhp-announces-copper-investment",
    ) == "BHP announces copper investment"
