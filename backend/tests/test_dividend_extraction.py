"""Dividend amounts preserve the financial value printed in the source."""

import pytest

from parsing.categories.dividend import DividendAnnouncement


@pytest.mark.parametrize(
    ("dollars", "cents"),
    [
        ("0.83000000", "83"),
        ("0.12500000", "12.5"),
        ("0.01500000", "1.5"),
        ("0.01234000", "1.234"),
        ("0.00000001", "0.000001"),
        ("1.00000000", "100"),
        ("0.10000000", "10"),
        ("0.00000000", "0"),
    ],
)
def test_appendix_amount_keeps_fractional_cents(dollars, cents):
    result = DividendAnnouncement.extract(
        "Interim dividend",
        f"Appendix 3A.1\nDistribution Amount\nAUD {dollars}\n",
    )

    assert result["amount_per_share"] == f"{cents} cents"


@pytest.mark.parametrize("amount", ["", "not disclosed", "0.12.5", "..", "-0.125"])
def test_invalid_appendix_amount_is_omitted_without_parsing_a_partial_value(amount):
    result = DividendAnnouncement.extract(
        "Dividend",
        f"Appendix 3A.1\nDistribution Amount\nAUD {amount}\n",
    )

    assert "amount_per_share" not in result


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Declared 12.5 cents per share.", "12.5 cents"),
        ("Declared 0.5 cents per share.", "0.5 cents"),
        ("Declared 83  cents per share.", "83 cents"),
        ("Declared 12.5000 cents per share.", "12.5 cents"),
        ("Declared 1 cent per share.", "1 cents"),
        ("Declared 0 cents per share.", "0 cents"),
        ("For 2026\n12.5 cents per share was declared.", "12.5 cents"),
        ("Declared 12.5\ncents per share.", "12.5 cents"),
        ("Declared 12.5 CENTS PER SHARE.", "12.5 cents"),
    ],
)
def test_prose_amount_preserves_the_complete_number(text, expected):
    assert DividendAnnouncement.extract("Interim dividend", text)["amount_per_share"] == expected


@pytest.mark.parametrize(
    "text",
    [
        "Declared 12..5 cents per share.",
        "Declared -12.5 cents per share.",
        "Declared 12,5 cents per share.",
        "Declared .5 cents per share.",
        "Declared no amount per share.",
    ],
)
def test_prose_does_not_invent_an_amount_from_a_partial_or_unsupported_number(text):
    assert "amount_per_share" not in DividendAnnouncement.extract("Dividend", text)


@pytest.mark.parametrize("format_name", ["appendix", "prose"])
@pytest.mark.parametrize(
    ("percent", "expected"),
    [("75.5000", "75.5%"), ("75.0000", "75%"), ("0.1250", "0.125%"), ("0", "0%"), ("100.0000", "100%")],
)
def test_franking_percent_retains_fractional_precision(format_name, percent, expected):
    text = (
        f"Appendix 3A.1\n3A.3 Percentage of ordinary dividend/distribution that is\nfranked\n{percent} %"
        if format_name == "appendix"
        else f"The dividend is partially franked at {percent}%."
    )

    assert DividendAnnouncement.extract("Dividend", text)["franking_percent"] == expected


@pytest.mark.parametrize("prefix", ["Appendix 3A.1\n", ""])
def test_fully_franked_dividends_keep_the_existing_value(prefix):
    result = DividendAnnouncement.extract("Dividend", prefix + "A fully franked dividend.")

    assert result["franking_percent"] == "100%"


@pytest.mark.parametrize("format_name", ["appendix", "prose"])
@pytest.mark.parametrize("percent", ["75..5", "not disclosed", "-75.5"])
def test_invalid_franking_number_is_omitted(format_name, percent):
    text = (
        f"Appendix 3A.1\nPercentage of ordinary dividend that is\nfranked\n{percent} %"
        if format_name == "appendix"
        else f"Partially franked at {percent}%."
    )

    assert "franking_percent" not in DividendAnnouncement.extract("Dividend", text)
