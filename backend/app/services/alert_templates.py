"""Plain Python templates for watchlist alert email content."""

from __future__ import annotations

import math
from html import escape
from typing import SupportsFloat, SupportsIndex
from urllib.parse import urlsplit


def _single_line(value: object, *, fallback: str = "") -> str:
    cleaned = " ".join(str(value or "").splitlines()).strip()
    return cleaned or fallback


def _absolute_url(value: str, *, field: str) -> str:
    cleaned = _single_line(value)
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute HTTP or HTTPS URL")
    return cleaned


ConfidenceValue = str | SupportsFloat | SupportsIndex


def _confidence_percent(value: ConfidenceValue) -> str:
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence_score must be numeric") from exc
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("confidence_score must be between 0 and 1")
    percentage = f"{confidence * 100:.1f}".rstrip("0").rstrip(".")
    return f"{percentage}%"


def render_alert_email(  # pylint: disable=too-many-arguments,too-many-locals
    *,
    ticker_symbol: str,
    company_name: str,
    artifact_title: str | None,
    summary_text: str | None,
    sentiment_label: str,
    confidence_score: ConfidenceValue,
    news_url: str,
    unsubscribe_url: str,
) -> tuple[str, str, str]:
    """Render the subject, HTML body, and plain-text body for one alert."""
    symbol = _single_line(ticker_symbol, fallback="Ticker")
    company = _single_line(company_name, fallback=symbol)
    title = _single_line(artifact_title, fallback="Untitled artifact")
    label = _single_line(sentiment_label, fallback="unknown").lower()
    summary = str(summary_text).strip() if summary_text else ""
    confidence = _confidence_percent(confidence_score)
    safe_news_url = _absolute_url(news_url, field="news_url")
    safe_unsubscribe_url = _absolute_url(
        unsubscribe_url,
        field="unsubscribe_url",
    )

    subject = f"{symbol} watchlist alert: {label} sentiment"
    summary_html = ""
    summary_text_block = ""
    if summary:
        escaped_summary = escape(summary).replace("\n", "<br>\n")
        summary_html = f"<h2>Summary</h2><p>{escaped_summary}</p>"
        summary_text_block = f"\nSummary\n{summary}\n"

    html = f"""<!doctype html>
<html lang="en">
  <body>
    <h1>Watchlist alert for {escape(symbol)}</h1>
    <p><strong>{escape(company)}</strong></p>
    <p>{escape(title)}</p>
    {summary_html}
    <p>
      Sentiment: <strong>{escape(label)}</strong><br>
      Confidence: <strong>{escape(confidence)}</strong>
    </p>
    <p><a href="{escape(safe_news_url, quote=True)}">View {escape(symbol)} news</a></p>
    <hr>
    <p>
      You received this email because alerts are enabled for your watchlist.
      <a href="{escape(safe_unsubscribe_url, quote=True)}">Unsubscribe</a>.
    </p>
  </body>
</html>"""

    text = (
        f"Watchlist alert for {symbol}\n"
        f"{company}\n\n"
        f"{title}\n"
        f"{summary_text_block}\n"
        f"Sentiment: {label}\n"
        f"Confidence: {confidence}\n\n"
        f"View {symbol} news: {safe_news_url}\n\n"
        "You received this email because alerts are enabled for your watchlist.\n"
        f"Unsubscribe: {safe_unsubscribe_url}\n"
    )
    return subject, html, text


def render_rollup_email(
    *,
    ticker_symbol: str,
    company_name: str,
    suppressed_count: int,
    news_url: str,
    unsubscribe_url: str,
) -> tuple[str, str, str]:
    """Render an honest lower-bound summary for capped watchlist alerts."""
    if isinstance(suppressed_count, bool) or suppressed_count < 1:
        raise ValueError("suppressed_count must be at least 1")
    symbol = _single_line(ticker_symbol, fallback="Ticker")
    company = _single_line(company_name, fallback=symbol)
    safe_news_url = _absolute_url(news_url, field="news_url")
    safe_unsubscribe_url = _absolute_url(
        unsubscribe_url,
        field="unsubscribe_url",
    )
    count_text = f"At least {suppressed_count} more matching signal"
    if suppressed_count != 1:
        count_text += "s"
    subject = f"{symbol} watchlist alert: more matching signals"
    html = f"""<!doctype html>
<html lang="en">
  <body>
    <h1>More watchlist alerts for {escape(symbol)}</h1>
    <p><strong>{escape(company)}</strong></p>
    <p>{escape(count_text)} arrived after your per-run email limit.</p>
    <p><a href="{escape(safe_news_url, quote=True)}">View {escape(symbol)} news</a></p>
    <hr>
    <p>
      You received this email because alerts are enabled for your watchlist.
      <a href="{escape(safe_unsubscribe_url, quote=True)}">Unsubscribe</a>.
    </p>
  </body>
</html>"""
    text = (
        f"More watchlist alerts for {symbol}\n"
        f"{company}\n\n"
        f"{count_text} arrived after your per-run email limit.\n\n"
        f"View {symbol} news: {safe_news_url}\n\n"
        "You received this email because alerts are enabled for your watchlist.\n"
        f"Unsubscribe: {safe_unsubscribe_url}\n"
    )
    return subject, html, text
