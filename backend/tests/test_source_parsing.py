"""Date and de-duplication helpers shared by the source adapters."""

from datetime import datetime

from scrapers.miraqle import clean_title
from scrapers.parsing import (
    DAY_MONTH_YEAR,
    ISO,
    MONTH_DAY_YEAR,
    SLASHED,
    date_text,
    first_date,
    parse_date,
    unique,
)


def test_unique_keeps_the_first_of_each_key() -> None:
    assert unique(["a1", "b1", "a2"], key=lambda item: item[0]) == ["a1", "b1"]


def test_parse_date_tries_formats_then_iso() -> None:
    assert parse_date(" 31 July 2026 ", ("%d %B %Y",)) == datetime(2026, 7, 31)
    assert parse_date("2026-07-31T08:00:00Z", ("%d %B %Y",)) is None
    assert parse_date(
        "2026-07-31T08:00:00Z", ("%d %B %Y",), iso_fallback=True
    ).year == 2026


def test_date_text_needs_whole_words() -> None:
    assert date_text("Results\n29 September 2026", (DAY_MONTH_YEAR, SLASHED)) == (
        "29 September 2026"
    )
    # Hidden text run together, as innerText gives it, has no whole date.
    assert date_text("29 September 202629/09/2026", (DAY_MONTH_YEAR, SLASHED, ISO)) is None


def test_first_date_skips_a_match_that_does_not_parse() -> None:
    formats = ("%B %d, %Y", "%d %B %Y")

    assert first_date("Week 99, 2026 then 3 May 2026", (MONTH_DAY_YEAR, DAY_MONTH_YEAR), formats) == (
        datetime(2026, 5, 3)
    )


def test_miraqle_titles_drop_screen_reader_labels() -> None:
    assert clean_title("Results\nOpens in a new Window", "", "x.pdf") == "Results"
    assert clean_title("", "Results View PDF 1 May 2026", "x.pdf") == "Results"
    assert clean_title("", "", "https://a/b/Annual-report_2026.pdf") == "Annual report 2026"
