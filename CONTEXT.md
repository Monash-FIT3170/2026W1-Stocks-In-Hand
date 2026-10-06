# Stocks In Hand

Stocks In Hand collects ASX company announcements, news and public discussion, analyses them, and turns them into plain-language briefs and alerts for retail investors.

## Language

### Companies and sources

**Ticker**:
An ASX company the product covers, identified by its stored symbol (upper-case, without the `.AX` suffix).
_Avoid_: stock, symbol (when the company is meant), company code

**Ticker catalogue**:
The single list of supported tickers and their facts: name, sector, industry, source adapter, announcements page and whether the weekly schedule includes it by default. Every other list of tickers is generated from it or checked against it.
_Avoid_: supported tickers list, default tickers, registry

**Source adapter**:
The per-company knowledge of how to find and fetch that company's announcements from its own website.
_Avoid_: scraper (for the whole concept), resolver

**Scheduled ticker**:
A ticker the weekly schedule scrapes when no override is configured.
_Avoid_: enabled ticker, default ticker
