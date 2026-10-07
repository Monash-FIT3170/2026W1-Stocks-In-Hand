"""The HTML model source adapters parse fetched pages with."""

import pytest

from scrapers.html import nearby_text_levels, parse_html

PAGE = """<html><head><title>Listing</title><script>var x = "<a href='no.pdf'>";</script></head>
<body>
<div class="list-item first"><div class="list-date">07-Oct-2026</div>
<a class="asx-document" href="/d/1.pdf">Half <b>year</b>   results</a></div>
<ul><li>One<li>Two <a href='DownloadFile.axd?id=1'>Doc<span data-display="none">Opens in a new Window</span></a></ul>
<table><tr><td>1 May 2026<td><a id="r1" href="GetPressRelease/?ID=5">Release</a></table>
<p>para<div>inner</div>
<span data-display="block">29 September 2026</span><span>29/09/2026</span>
<iframe src="https://tools.eurolandir.com/x?v=asx2023"></iframe>
</body></html>"""


@pytest.fixture()
def document():
    return parse_html(PAGE)


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("a[href]", ["/d/1.pdf", "DownloadFile.axd?id=1", "GetPressRelease/?ID=5"]),
        ("div.list-item a.asx-document", ["/d/1.pdf"]),
        ("a[href*='DownloadFile.axd']", ["DownloadFile.axd?id=1"]),
        ("a[href^='/d/'], a#r1", ["/d/1.pdf", "GetPressRelease/?ID=5"]),
        ('a[href$=".pdf"]', ["/d/1.pdf"]),
        ("ul li a", ["DownloadFile.axd?id=1"]),
    ],
)
def test_selectors_find_links(document, selector: str, expected: list[str]) -> None:
    assert [link.get("href") for link in document.select(selector)] == expected


def test_text_reads_like_a_browser(document) -> None:
    assert document.select_one("div.list-item").text == "07-Oct-2026\nHalf year results"
    assert [item.text for item in document.select("li")] == ["One", "Two Doc"]
    assert "<a href" not in document.text


def test_closest_finds_the_row_and_implicit_ends_close_elements(document) -> None:
    link = document.select_one("a#r1")

    assert link.closest("tr").text == "1 May 2026\nRelease"
    assert document.select_one("a[href*='DownloadFile']").closest("tr, li").tag == "li"
    assert [paragraph.text for paragraph in document.select("p")] == ["para"]


def test_display_marks_decide_line_breaks_and_hidden_text(document) -> None:
    assert "29 September 2026\n29/09/2026" in document.text
    assert "Opens in a new Window" not in document.text


def test_nearby_levels_start_at_the_narrowest_container() -> None:
    page = parse_html(
        "<div><div><time datetime='2026-07-31T08:00:00'>31 Jul</time>"
        "<p><a href='/r'>Report</a></p></div><p>12 June 2026</p></div>"
    )

    time_value, levels = nearby_text_levels(page.select_one("a"))

    assert time_value == "2026-07-31T08:00:00"
    assert levels[0] == "Report"
    assert levels[1].startswith("31 Jul")
