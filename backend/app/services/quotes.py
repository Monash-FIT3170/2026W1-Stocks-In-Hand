"""Quote source: a ticker's current price and previous close.

Quotes are read live when a page asks for them and are never stored, so
there is no market data table behind the price cards. ``YahooQuotes`` reads
Yahoo Finance's chart API and keeps each answer briefly; ``FixedQuotes``
answers from a table, for tests. A quote source answers None when it has
no quote for a symbol, and the page shows "N/A" instead.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.AX"
_TIMEOUT = httpx.Timeout(2.5, connect=1.5)


@dataclass(frozen=True)
class Quote:
    price: float
    previous_close: float

    def day_change(self) -> float | None:
        """The change since the previous close, in percent. None when that close is 0."""
        if self.previous_close == 0:
            return None
        return (self.price - self.previous_close) / self.previous_close * 100


class QuoteSource(Protocol):
    def quote(self, symbol: str) -> Quote | None:
        """The ticker's quote, or None when there is none to show."""


class YahooQuotes:
    """Quotes from Yahoo Finance's chart API for the ticker's ASX listing.

    An unknown symbol, an unreachable Yahoo or an answer without a price and
    previous close gives None. Each instance keeps a quote for ``ttl``
    seconds and a failure for ``failure_ttl``, so a symbol Yahoo cannot
    resolve does not cost a timeout on every page load.
    """

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = 300,
        failure_ttl: float = 60,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._ttl = ttl
        self._failure_ttl = failure_ttl
        # symbol -> (when it was fetched, the quote or None)
        self._cache: dict[str, tuple[float, Quote | None]] = {}

    def quote(self, symbol: str) -> Quote | None:
        now = self._clock()
        cached = self._cache.get(symbol)
        if cached:
            fetched_at, cached_quote = cached
            ttl = self._ttl if cached_quote is not None else self._failure_ttl
            if now - fetched_at < ttl:
                return cached_quote

        quote = self._fetch(symbol)
        self._cache[symbol] = (now, quote)
        return quote

    def _fetch(self, symbol: str) -> Quote | None:
        try:
            with httpx.Client(timeout=_TIMEOUT, transport=self._transport) as client:
                response = client.get(
                    _CHART_URL.format(symbol=symbol),
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            response.raise_for_status()
            result = response.json().get("chart", {}).get("result") or []
            if not result:
                return None

            meta = result[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            previous_close = meta.get("chartPreviousClose") or meta.get(
                "regularMarketPreviousClose"
            )
            if price is None or previous_close is None:
                return None
            return Quote(price=float(price), previous_close=float(previous_close))
        except Exception:
            return None


class FixedQuotes:
    """Quotes from a fixed table, for tests. ``requested`` lists each symbol asked for."""

    def __init__(self, quotes: Mapping[str, Quote | None] | None = None) -> None:
        self._quotes = dict(quotes or {})
        self.requested: list[str] = []

    def quote(self, symbol: str) -> Quote | None:
        self.requested.append(symbol)
        return self._quotes.get(symbol)


# One source for the whole process, so its cache outlives each request.
_LIVE_QUOTES = YahooQuotes()


def live_quotes() -> QuoteSource:
    """The process's Yahoo quote source, as a FastAPI dependency."""
    return _LIVE_QUOTES
