"""Source-specific document resolution for sites that require a browser session."""

from __future__ import annotations

import asyncio
import hashlib
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

from app.messages import QueueBMessage
from app.sources import SourceAdapter
from lambdas.common import PermanentDocumentError
from lambdas.download_validation import (
    DOCUMENT_CONTENT_TYPES,
    DownloadedDocument,
    download_document,
    validate_document_content,
    validate_download_url,
)

_ADAPTER_HOSTS: dict[SourceAdapter, frozenset[str]] = {
    "anz": frozenset(
        {
            "www.anz.com",
            "anz.com",
            "www.anz.com.au",
            "anz.com.au",
            "yourir.info",
        }
    ),
    "bhp": frozenset({"www.bhp.com", "bhp.com"}),
    "cba": frozenset(
        {"www.commbank.com.au", "commbank.com.au", "yourir.info"}
    ),
    "csl": frozenset({"investors.csl.com"}),
    "wes": frozenset({"www.wesfarmers.com.au", "wesfarmers.com.au"}),
}
_YOURIR_BASES = {
    "anz": "https://yourir.info/resources/4d216b570d08af30/announcements",
    "cba": "https://yourir.info/resources/e381e7bfa5abbe55/announcements",
}
_RETRYABLE_HTTP_STATUSES = {408, 409, 425, 429}


def _validated_url(adapter: SourceAdapter, url: str) -> str:
    return validate_download_url(url, hosts=_ADAPTER_HOSTS[adapter])


def _response_content_type(headers: Mapping[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _raise_for_status(status: int, url: str) -> None:
    if status == 404:
        raise PermanentDocumentError(
            "Document no longer exists",
            code="document_not_found",
        )
    if 400 <= status < 500 and status not in _RETRYABLE_HTTP_STATUSES:
        raise PermanentDocumentError(
            f"Document request was permanently rejected ({status})",
            code="document_rejected",
        )
    if status >= 400:
        raise RuntimeError(f"Document request failed with HTTP {status}: {url}")


def _build_downloaded_document(
    content: bytes,
    *,
    declared_content_type: str,
    final_url: str,
    max_bytes: int,
) -> DownloadedDocument:
    if len(content) > max_bytes:
        raise PermanentDocumentError(
            "Document is larger than the configured limit",
            code="document_too_large",
        )
    document_format = validate_document_content(
        content,
        declared_content_type=declared_content_type,
        final_url=final_url,
    )
    return DownloadedDocument(
        content=content,
        checksum=hashlib.sha256(content).hexdigest(),
        final_url=final_url,
        content_type=DOCUMENT_CONTENT_TYPES[document_format],
        document_format=document_format,
    )


async def _request_document(
    context: BrowserContext,
    *,
    adapter: SourceAdapter,
    url: str,
    referer: str,
    max_bytes: int,
) -> DownloadedDocument:
    requested_url = _validated_url(adapter, url)
    response: APIResponse = await context.request.get(
        requested_url,
        headers={"Referer": referer},
        timeout=120_000,
    )
    final_url = _validated_url(adapter, response.url)
    _raise_for_status(response.status, final_url)

    declared_length = response.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > max_bytes:
                raise PermanentDocumentError(
                    "Document is larger than the configured limit",
                    code="document_too_large",
                )
        except ValueError:
            pass

    return _build_downloaded_document(
        await response.body(),
        declared_content_type=_response_content_type(response.headers),
        final_url=final_url,
        max_bytes=max_bytes,
    )


def _download_yourir(
    *,
    adapter: SourceAdapter,
    source_url: str,
    document_url: str,
    metadata: Mapping[str, object],
    max_bytes: int,
) -> DownloadedDocument:
    try:
        return download_document(
            _validated_url(adapter, document_url),
            hosts=_ADAPTER_HOSTS[adapter],
            referer=source_url,
            max_bytes=max_bytes,
        )
    except PermanentDocumentError as exc:
        if exc.code != "document_not_found":
            raise
        source_id = metadata.get("yourir_id")
        if not isinstance(source_id, str) or not source_id:
            raise
        fallback_url = f"{_YOURIR_BASES[adapter]}/{source_id}/announcement.pdf"
        return download_document(
            _validated_url(adapter, fallback_url),
            hosts=_ADAPTER_HOSTS[adapter],
            referer=source_url,
            max_bytes=max_bytes,
        )


async def _resolve_bhp_document_url(
    context: BrowserContext,
    *,
    article_url: str,
) -> str:
    response = await context.request.get(article_url, timeout=60_000)
    final_article_url = _validated_url("bhp", response.url)
    _raise_for_status(response.status, final_article_url)
    html = await response.text()

    absolute = re.search(
        r"""https?://[^"'<>\\\s]+\.pdf(?:\?[^"'<>\\\s]*)?""",
        html,
    )
    if absolute:
        return _validated_url("bhp", absolute.group(0))
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
    source_url: str,
    document_url: str,
    title: str | None,
    metadata: Mapping[str, object],
    max_bytes: int,
) -> DownloadedDocument:
    page = await context.new_page()
    try:
        await page.goto(source_url, wait_until="domcontentloaded", timeout=60_000)
        _validated_url("wes", page.url)
        await page.wait_for_selector(
            "article.asx-announce div.asx-results li",
            timeout=30_000,
        )
        expected_url = _validated_url("wes", document_url)
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

        final_url = _validated_url("wes", browser_download.url)
        raw_temporary_path = await browser_download.path()
        if raw_temporary_path is None:
            raise RuntimeError("Browser did not provide a downloaded file path")
        temporary_path = Path(raw_temporary_path)
        size = temporary_path.stat().st_size
        if size > max_bytes:
            raise PermanentDocumentError(
                "Document is larger than the configured limit",
                code="document_too_large",
            )
        content = temporary_path.read_bytes()
        return _build_downloaded_document(
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


async def resolve_session_download(
    *,
    source_adapter: str,
    source_url: str,
    document_url: str,
    title: str | None,
    metadata: Mapping[str, object],
    max_bytes: int,
) -> DownloadedDocument:
    """Resolve and download one document using a fresh, non-persisted session."""
    if source_adapter not in {"anz", "bhp", "cba", "wes"}:
        raise PermanentDocumentError(
            "Source does not use a browser download session",
            code="unsupported_source",
        )
    adapter: SourceAdapter = source_adapter  # type: ignore[assignment]
    validated_source_url = _validated_url(adapter, source_url)
    validated_document_url = _validated_url(adapter, document_url)

    if adapter in {"anz", "cba"}:
        return _download_yourir(
            adapter=adapter,
            source_url=validated_source_url,
            document_url=validated_document_url,
            metadata=metadata,
            max_bytes=max_bytes,
        )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-http2",
                "--headless=new",
            ],
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
                    article_url=validated_document_url,
                )
                return await _request_document(
                    context,
                    adapter=adapter,
                    url=resolved_url,
                    referer=validated_document_url,
                    max_bytes=max_bytes,
                )
            return await _download_wes(
                context,
                source_url=validated_source_url,
                document_url=validated_document_url,
                title=title,
                metadata=metadata,
                max_bytes=max_bytes,
            )
        finally:
            await browser.close()


def resolve_download(
    message: QueueBMessage,
    *,
    max_bytes: int,
) -> DownloadedDocument:
    """Download one Queue B document using the minimum strategy for its source."""
    if message.source_adapter == "csl":
        return download_document(str(message.document_url), max_bytes=max_bytes)
    return asyncio.run(
        resolve_session_download(
            source_adapter=message.source_adapter,
            source_url=str(message.source_url),
            document_url=str(message.document_url),
            title=message.title,
            metadata=message.metadata,
            max_bytes=max_bytes,
        )
    )
