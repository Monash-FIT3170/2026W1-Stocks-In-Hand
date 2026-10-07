"""Source-specific document resolution for sites that require a browser session."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import (
    APIResponse,
    BrowserContext,
    Download,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from lambdas.common import PermanentDocumentError
from lambdas.download_validation import (
    DownloadedDocument,
    declared_length,
    download_document,
    ensure_within_size_limit,
    raise_for_document_status,
    validate_download_url,
    validated_document,
)
from scrapers.browser import chromium_launch_options

_BROWSER_REQUEST_ADAPTERS = frozenset(
    {"coh", "col", "mqg", "org", "rio", "tls", "wds"}
)


def _validated_url(hosts: frozenset[str], url: str) -> str:
    return validate_download_url(url, hosts=hosts)


def _response_content_type(headers: Mapping[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


async def _request_document(
    context: BrowserContext,
    *,
    hosts: frozenset[str],
    url: str,
    referer: str,
    max_bytes: int,
) -> DownloadedDocument:
    requested_url = _validated_url(hosts, url)
    response: APIResponse = await context.request.get(
        requested_url,
        headers={"Referer": referer},
        timeout=120_000,
    )
    final_url = _validated_url(hosts, response.url)
    raise_for_document_status(response.status, final_url)

    ensure_within_size_limit(declared_length(response.headers), max_bytes)
    return validated_document(
        await response.body(),
        declared_content_type=_response_content_type(response.headers),
        final_url=final_url,
        max_bytes=max_bytes,
    )


async def _resolve_bhp_document_url(
    context: BrowserContext,
    *,
    hosts: frozenset[str],
    article_url: str,
) -> str:
    response = await context.request.get(article_url, timeout=60_000)
    final_article_url = _validated_url(hosts, response.url)
    raise_for_document_status(response.status, final_article_url)
    html = await response.text()

    absolute = re.search(
        r"""https?://[^"'<>\\\s]+\.pdf(?:\?[^"'<>\\\s]*)?""",
        html,
    )
    if absolute:
        return _validated_url(hosts, absolute.group(0))
    relative = re.search(
        r"""["']([^"'<>]+\.pdf(?:\?[^"'<>]*)?)["']""",
        html,
    )
    if relative:
        return _validated_url(
            "bhp",
            urljoin(final_article_url, relative.group(1)),
        )

    raise PermanentDocumentError(
        "BHP article does not contain a supported document link",
        code="document_link_not_found",
    )


def _content_type_for_download(download: Download, content: bytes) -> str:
    suffix = Path(download.suggested_filename).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".docx":
        return (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".txt":
        return "text/plain"
    if content.startswith(b"%PDF-") or content.startswith(b"PK"):
        return "application/octet-stream"
    return "text/plain"


async def _download_wes(
    context: BrowserContext,
    *,
    hosts: frozenset[str],
    source_url: str,
    document_url: str,
    title: str | None,
    metadata: Mapping[str, object],
    max_bytes: int,
) -> DownloadedDocument:
    page = await context.new_page()
    try:
        await page.goto(source_url, wait_until="domcontentloaded", timeout=60_000)
        _validated_url(hosts, page.url)
        await page.wait_for_selector(
            "article.asx-announce div.asx-results li",
            timeout=30_000,
        )
        expected_url = _validated_url(hosts, document_url)
        raw_href = metadata.get("raw_href")
        target = None

        for row in await page.query_selector_all(
            "article.asx-announce div.asx-results li"
        ):
            link = await row.query_selector("a[href]")
            if link is None:
                continue
            href = await link.get_attribute("href")
            link_title = (await link.inner_text()).strip()
            resolved = urljoin(source_url, href or "")
            if (
                resolved == expected_url
                or (isinstance(raw_href, str) and href == raw_href)
                or (title and link_title == title)
            ):
                target = link
                break

        if target is None:
            raise PermanentDocumentError(
                "Wesfarmers document link is no longer listed",
                code="document_link_not_found",
            )

        try:
            async with page.expect_download(timeout=120_000) as download_info:
                await target.click(modifiers=["Alt"])
            browser_download = await download_info.value
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Wesfarmers download did not start") from exc

        final_url = _validated_url(hosts, browser_download.url)
        raw_temporary_path = await browser_download.path()
        if raw_temporary_path is None:
            raise RuntimeError("Browser did not provide a downloaded file path")
        temporary_path = Path(raw_temporary_path)
        ensure_within_size_limit(temporary_path.stat().st_size, max_bytes)
        content = temporary_path.read_bytes()
        return validated_document(
            content,
            declared_content_type=_content_type_for_download(
                browser_download,
                content,
            ),
            final_url=final_url,
            max_bytes=max_bytes,
        )
    finally:
        await page.close()


def _request_referer(
    hosts: frozenset[str],
    source_url: str,
    metadata: Mapping[str, object],
) -> str:
    """Choose one scraper-produced, adapter-scoped page to seed the session."""
    # Prefer an HTML listing over an article URL. Some adapters (notably WDS)
    # represent direct PDF links as their article URL; navigating a page to
    # those links raises Playwright's expected "Download is starting" signal.
    for key in ("feed_url", "listing_url", "article_url"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return _validated_url(hosts, value)
    return _validated_url(hosts, source_url)


async def _download_browser_request(
    context: BrowserContext,
    *,
    hosts: frozenset[str],
    source_url: str,
    document_url: str,
    metadata: Mapping[str, object],
    max_bytes: int,
) -> DownloadedDocument:
    """Recreate the short-lived browser session used by expanded adapters."""
    referer = _request_referer(hosts, source_url, metadata)
    page = await context.new_page()
    try:
        await page.goto(referer, wait_until="domcontentloaded", timeout=60_000)
        _validated_url(hosts, page.url)
    finally:
        await page.close()

    return await _request_document(
        context,
        hosts=hosts,
        url=document_url,
        referer=referer,
        max_bytes=max_bytes,
    )


async def resolve_session_download(
    *,
    source_adapter: str,
    hosts: frozenset[str],
    source_url: str,
    document_url: str,
    title: str | None,
    metadata: Mapping[str, object],
    max_bytes: int,
) -> DownloadedDocument:
    """Resolve and download one document using a fresh, non-persisted session."""
    if source_adapter not in {"bhp", "wes"}.union(_BROWSER_REQUEST_ADAPTERS):
        raise PermanentDocumentError(
            "Source does not use a browser download session",
            code="unsupported_source",
        )
    adapter = source_adapter
    validated_source_url = _validated_url(hosts, source_url)
    validated_document_url = _validated_url(hosts, document_url)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            **chromium_launch_options(extra_args=("--disable-http2",))
        )
        context = await browser.new_context(
            accept_downloads=True,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-AU",
        )
        try:
            if adapter == "bhp":
                resolved_url = await _resolve_bhp_document_url(
                    context,
                    hosts=hosts,
                    article_url=validated_document_url,
                )
                return await _request_document(
                    context,
                    hosts=hosts,
                    url=resolved_url,
                    referer=validated_document_url,
                    max_bytes=max_bytes,
                )
            if adapter in _BROWSER_REQUEST_ADAPTERS:
                return await _download_browser_request(
                    context,
                    hosts=hosts,
                    source_url=validated_source_url,
                    document_url=validated_document_url,
                    metadata=metadata,
                    max_bytes=max_bytes,
                )
            return await _download_wes(
                context,
                hosts=hosts,
                source_url=validated_source_url,
                document_url=validated_document_url,
                title=title,
                metadata=metadata,
                max_bytes=max_bytes,
            )
        finally:
            await browser.close()


async def fetch_document(
    *,
    source_adapter: str,
    hosts: frozenset[str],
    source_url: str,
    document_url: str,
    title: str | None,
    metadata: Mapping[str, object],
    max_bytes: int,
) -> DownloadedDocument:
    """Download one document using the minimum strategy for its source."""
    if source_adapter == "csl":
        return download_document(document_url, max_bytes=max_bytes)
    return await resolve_session_download(
        source_adapter=source_adapter,
        hosts=hosts,
        source_url=source_url,
        document_url=document_url,
        title=title,
        metadata=metadata,
        max_bytes=max_bytes,
    )
