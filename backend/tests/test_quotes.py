"""The quote source: Yahoo's chart API behind one interface, and a fixed table.

The Yahoo adapter gets an httpx mock transport and a fake clock, so its
request, its parsing and its cache are checked without the network.
"""

from collections.abc import Callable

import httpx
import pytest

from app.services.quotes import FixedQuotes, Quote, YahooQuotes

Handler = Callable[[httpx.Request], httpx.Response]


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def _chart(**meta: float) -> httpx.Response:
    return httpx.Response(200, json={"chart": {"result": [{"meta": meta}]}})


def _yahoo(handler: Handler, clock: _Clock | None = None) -> tuple[YahooQuotes, list]:
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    quotes = YahooQuotes(transport=httpx.MockTransport(answer), clock=clock or _Clock())
    return quotes, requests


def test_the_adapter_asks_yahoo_for_the_asx_listing() -> None:
    quotes, requests = _yahoo(
        lambda _request: _chart(regularMarketPrice=31.25, chartPreviousClose=30.0)
    )

    assert quotes.quote("CBA") == Quote(price=31.25, previous_close=30.0)
    [request] = requests
    assert request.url == "https://query1.finance.yahoo.com/v8/finance/chart/CBA.AX"
    assert request.headers["User-Agent"] == "Mozilla/5.0"


def test_the_previous_close_falls_back_to_the_regular_market_close() -> None:
    quotes, _requests = _yahoo(
        lambda _request: _chart(regularMarketPrice=12.0, regularMarketPreviousClose=11.5)
    )

    assert quotes.quote("BHP") == Quote(price=12.0, previous_close=11.5)


def _time_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("Yahoo did not answer", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        lambda _request: httpx.Response(200, json={"chart": {"result": []}}),
        lambda _request: _chart(chartPreviousClose=30.0),
        lambda _request: _chart(regularMarketPrice=31.25),
        lambda _request: httpx.Response(500),
        lambda _request: httpx.Response(200, content=b"not json"),
        _time_out,
    ],
    ids=["no result", "no price", "no close", "http 500", "invalid json", "timeout"],
)
def test_no_usable_answer_gives_no_quote(handler: Handler) -> None:
    quotes, _requests = _yahoo(handler)

    assert quotes.quote("CBA") is None


def test_a_quote_is_kept_for_five_minutes() -> None:
    clock = _Clock()
    quotes, requests = _yahoo(
        lambda _request: _chart(regularMarketPrice=31.25, chartPreviousClose=30.0),
        clock,
    )

    quotes.quote("CBA")
    clock.now += 299
    quotes.quote("CBA")
    assert len(requests) == 1

    clock.now += 1
    quotes.quote("CBA")
    assert len(requests) == 2


def test_a_failure_is_tried_again_after_a_minute() -> None:
    clock = _Clock()
    answers = iter([httpx.Response(500), _chart(regularMarketPrice=5.0, chartPreviousClose=4.0)])
    quotes, requests = _yahoo(lambda _request: next(answers), clock)

    assert quotes.quote("CBA") is None
    clock.now += 59
    assert quotes.quote("CBA") is None
    assert len(requests) == 1

    clock.now += 1
    assert quotes.quote("CBA") == Quote(price=5.0, previous_close=4.0)
    assert len(requests) == 2


def test_fixed_quotes_answer_from_their_table_and_record_each_symbol() -> None:
    quotes = FixedQuotes({"CBA": Quote(price=10.0, previous_close=9.0)})

    assert quotes.quote("CBA") == Quote(price=10.0, previous_close=9.0)
    assert quotes.quote("BHP") is None
    assert quotes.requested == ["CBA", "BHP"]


def test_the_day_change_needs_a_previous_close() -> None:
    assert Quote(price=31.25, previous_close=30.0).day_change() == pytest.approx(4.1667, abs=1e-4)
    assert Quote(price=10.0, previous_close=0.0).day_change() is None
