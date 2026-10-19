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
