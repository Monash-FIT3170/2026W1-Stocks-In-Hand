"""How source adapters reach a company's website.

An adapter's work is split in two: a thin fetch step that asks a web
session for pages and documents, and a pure parse step over the returned
HTML or JSON. Adapters open a session from the fetcher they were given, so
tests can swap the live web (``LiveFetcher``: plain HTTP plus a lazily
started Chromium) for recorded responses (``RecordedFetcher``).
``RecordingFetcher`` records a live session into a fixture directory.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol

import httpx

if TYPE_CHECKING:
    from lambdas.download_validation import DownloadedDocument

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Page:
    """A fetched page: the URL it ended at and its HTML."""

    url: str
    html: str


@dataclass(frozen=True)
class Render:
    """How to load one page in the browser before reading its HTML."""

    wait_until: str = "domcontentloaded"
    timeout_ms: int = 60_000
    # Wait for this selector; ``required`` decides whether giving up fails.
    wait_for: str | None = None
    wait_for_timeout_ms: int = 15_000
    required: bool = False
    # Click the first of these that exists when ``wait_for`` never appears,
    # then wait ``click_wait_ms`` for it again.
    click_if_missing: tuple[str, ...] = ()
    click_wait_ms: int = 15_000
    settle_ms: int = 0
    # Read the first frame whose URL contains all of these, not the page.
    frame_url_contains: tuple[str, ...] = ()


# Marks what CSS decides for each element (see scrapers.html), so parsing the
# serialised page sees the same line breaks and hidden text as a browser.
_MARK_DISPLAY = """(blockTags) => {
    const blockTags_ = new Set(blockTags);
    const blockish = new Set([
        "block", "flex", "grid", "table", "list-item", "flow-root",
        "table-row", "table-row-group", "table-header-group",
        "table-footer-group", "table-cell", "table-caption",
    ]);
    for (const element of document.querySelectorAll("body *")) {
        const display = getComputedStyle(element).display;
        let mark = null;
        if (display === "none") {
            mark = "none";
        } else {
            const block = blockish.has(display);
            if (block !== blockTags_.has(element.tagName.toLowerCase())) {
                mark = block ? "block" : "inline";
            }
        }
        if (mark) element.setAttribute("data-display", mark);
    }
}"""


class SourceUnavailableError(RuntimeError):
    """The page could not be fetched (network error, timeout or bad status)."""


class WebSession(Protocol):
    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object: ...

    async def get_page(self, url: str, *, headers: Mapping[str, str] | None = None) -> Page:
        """GET a page over plain HTTP without running its scripts."""

    async def render(self, url: str, render: Render = Render()) -> Page:
        """Load a page in the browser and return the HTML it ends up with."""

    async def request_page(self, url: str) -> Page:
        """GET a page through the browser's network stack and cookies."""

    async def download(
        self,
        url: str,
        *,
        hosts: frozenset[str],
        referer: str,
        max_bytes: int,
    ) -> DownloadedDocument:
        """Download and validate one document over plain HTTP."""

    async def request_document(
        self,
        url: str,
        *,
        hosts: frozenset[str],
        referer: str,
        max_bytes: int,
        seed_url: str | None = None,
    ) -> DownloadedDocument:
        """Download a document through the browser, after visiting ``seed_url``."""

    async def click_download(
        self,
        page_url: str,
        *,
        wait_for: str,
        link_selector: str,
        hosts: frozenset[str],
        max_bytes: int,
    ) -> DownloadedDocument:
        """Open a page, click a link that starts a download and validate it."""


class Fetcher(Protocol):
    def session(self, **options: Any) -> Any:
        """An async context manager yielding a WebSession."""


def _content_type(headers: Mapping[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


class LiveSession:
    """The live web. Chromium starts on the first request that needs it."""

    def __init__(
        self,
        *,
        disable_http2: bool = False,
        ignore_https_errors: bool = False,
    ) -> None:
        self.disable_http2 = disable_http2
        self.ignore_https_errors = ignore_https_errors
        self._playwright = None
        self._browser = None
        self._context = None

    async def _browser_context(self):
        if self._context is None:
            from playwright.async_api import async_playwright

            from .browser import chromium_launch_options

            self._playwright = await async_playwright().start()
            extra_args = ("--disable-http2",) if self.disable_http2 else ()
            self._browser = await self._playwright.chromium.launch(
                **chromium_launch_options(extra_args=extra_args)
            )
            self._context = await self._browser.new_context(
                accept_downloads=True,
                user_agent=BROWSER_USER_AGENT,
                viewport={"width": 1366, "height": 768},
                locale="en-AU",
                ignore_https_errors=self.ignore_https_errors,
            )
        return self._context

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._playwright = self._browser = self._context = None

    async def get_json(self, url, *, params=None, headers=None) -> object:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"},
        ) as client:
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise SourceUnavailableError(f"Could not fetch {url}: {exc}") from exc
            return response.json()

    async def get_page(self, url, *, headers=None) -> Page:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": BROWSER_USER_AGENT},
        ) as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise SourceUnavailableError(f"Could not fetch {url}: {exc}") from exc
            return Page(url=str(response.url), html=response.text)

    async def render(self, url: str, render: Render = Render()) -> Page:
        from playwright.async_api import Error as PlaywrightError

        context = await self._browser_context()
        page = await context.new_page()
        try:
            try:
                await page.goto(url, wait_until=render.wait_until, timeout=render.timeout_ms)
            except PlaywrightError as exc:
                raise SourceUnavailableError(f"Could not load {url}: {exc}") from exc
            if render.wait_for:
                await self._wait_for(page, render)
            if render.settle_ms:
                await page.wait_for_timeout(render.settle_ms)
            if render.frame_url_contains:
                return await self._frame(page, render.frame_url_contains)
            await _mark_display(page)
            return Page(url=page.url, html=await page.content())
        finally:
            await page.close()

    async def _wait_for(self, page, render: Render) -> None:
        from playwright.async_api import Error as PlaywrightError

        try:
            await page.wait_for_selector(render.wait_for, timeout=render.wait_for_timeout_ms)
            return
        except PlaywrightError:
            pass
        for selector in render.click_if_missing:
            target = await page.query_selector(selector)
            if target is None:
                continue
            try:
                await target.click()
                await page.wait_for_timeout(2_000)
                await page.wait_for_selector(render.wait_for, timeout=render.click_wait_ms)
                return
            except PlaywrightError:
                break
        if render.required:
            raise SourceUnavailableError(
                f"{page.url} never showed {render.wait_for!r}"
            )

    async def _frame(self, page, url_parts: tuple[str, ...]) -> Page:
        for _ in range(12):
            for frame in page.frames:
                if all(part in frame.url for part in url_parts):
                    await _mark_display(frame)
                    return Page(url=frame.url, html=await frame.content())
            await page.wait_for_timeout(500)
        raise SourceUnavailableError(f"{page.url} has no frame from {url_parts!r}")

    async def request_page(self, url: str) -> Page:
        from playwright.async_api import Error as PlaywrightError

        context = await self._browser_context()
        try:
            response = await context.request.get(url, timeout=60_000)
        except PlaywrightError as exc:
            raise SourceUnavailableError(f"Could not fetch {url}: {exc}") from exc
        from lambdas.download_validation import raise_for_document_status

        raise_for_document_status(response.status, response.url)
        return Page(url=response.url, html=await response.text())

    async def download(self, url, *, hosts, referer, max_bytes) -> DownloadedDocument:
        from lambdas.download_validation import download_document

        return await asyncio.to_thread(
            download_document,
            url,
            hosts=hosts,
            referer=referer,
            max_bytes=max_bytes,
        )

    async def request_document(
        self,
        url,
        *,
        hosts,
        referer,
        max_bytes,
        seed_url=None,
    ) -> DownloadedDocument:
        from lambdas.download_validation import (
            declared_length,
            ensure_within_size_limit,
            raise_for_document_status,
            validate_download_url,
            validated_document,
        )

        context = await self._browser_context()
        if seed_url:
            page = await context.new_page()
            try:
                await page.goto(
                    validate_download_url(seed_url, hosts=hosts),
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                validate_download_url(page.url, hosts=hosts)
            finally:
                await page.close()
        response = await context.request.get(
            validate_download_url(url, hosts=hosts),
            headers={"Referer": referer},
            timeout=120_000,
        )
        final_url = validate_download_url(response.url, hosts=hosts)
        raise_for_document_status(response.status, final_url)
        ensure_within_size_limit(declared_length(response.headers), max_bytes)
        return validated_document(
            await response.body(),
            declared_content_type=_content_type(response.headers),
            final_url=final_url,
            max_bytes=max_bytes,
        )

    async def click_download(
        self,
        page_url,
        *,
        wait_for,
        link_selector,
        hosts,
        max_bytes,
    ) -> DownloadedDocument:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        from lambdas.common import PermanentDocumentError
        from lambdas.download_validation import (
            ensure_within_size_limit,
            validate_download_url,
            validated_document,
        )

        context = await self._browser_context()
        page = await context.new_page()
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
            validate_download_url(page.url, hosts=hosts)
            await page.wait_for_selector(wait_for, timeout=30_000)
            link = await page.query_selector(link_selector)
            if link is None:
                raise PermanentDocumentError(
                    "Document link is no longer listed",
                    code="document_link_not_found",
                )
            try:
                async with page.expect_download(timeout=120_000) as download_info:
                    await link.click(modifiers=["Alt"])
                browser_download = await download_info.value
            except PlaywrightTimeoutError as exc:
                raise RuntimeError("Browser download did not start") from exc
            final_url = validate_download_url(browser_download.url, hosts=hosts)
            path = await browser_download.path()
            if path is None:
                raise RuntimeError("Browser did not provide a downloaded file path")
            ensure_within_size_limit(Path(path).stat().st_size, max_bytes)
            content = Path(path).read_bytes()
            return validated_document(
                content,
                declared_content_type=_download_content_type(
                    browser_download.suggested_filename,
                    content,
                ),
                final_url=final_url,
                max_bytes=max_bytes,
            )
        finally:
            await page.close()


async def _mark_display(page_or_frame) -> None:
    from .html import BLOCK_TAGS

    await page_or_frame.evaluate(_MARK_DISPLAY, sorted(BLOCK_TAGS))


def _download_content_type(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".txt":
        return "text/plain"
    if content.startswith(b"%PDF-") or content.startswith(b"PK"):
        return "application/octet-stream"
    return "text/plain"


class LiveFetcher:
    @asynccontextmanager
    async def session(self, **options: Any) -> AsyncIterator[LiveSession]:
        session = LiveSession(**options)
        try:
            yield session
        finally:
            await session.close()


# Recording and replaying ----------------------------------------------------

_STYLE_SVG = re.compile(r"<(style|svg)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_HEAD_TAGS = re.compile(r"<(?:link|meta)\b[^>]*>", re.IGNORECASE)
_STYLE_ATTRIBUTE = re.compile(r"""\sstyle=(?:"[^"]*"|'[^']*')""", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SPACE = re.compile(r"[ \t\r\f\v]*\n\s*")


def _slim(html: str) -> str:
    """Drop what the parsers never read, so recorded pages stay small.

    Scripts, links and metas that mention a PDF stay, because article
    parsers fall back to searching the page source for a document link.
    """
    for pattern in (_SCRIPT, _HEAD_TAGS):
        html = pattern.sub(lambda match: match.group(0) if ".pdf" in match.group(0) else "", html)
    for pattern in (_STYLE_SVG, _STYLE_ATTRIBUTE, _COMMENT):
        html = pattern.sub("", html)
    return _SPACE.sub("\n", html)


def request_key(method: str, url: str) -> str:
    """The key a recorded answer is stored under."""
    return f"{method} {url}"


def _file_name(key: str, suffix: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16] + suffix


class RecordedSession:
    """Replays recorded answers. Every request is kept in ``requests``."""

    def __init__(self, directory: Path | None, answers: Mapping[str, object] | None):
        self.directory = directory
        self.answers: dict[str, object] = dict(answers or {})
        if directory is not None:
            index = json.loads((directory / "index.json").read_text())
            for key, entry in index.items():
                self.answers.setdefault(key, entry)
        self.requests: list[dict[str, object]] = []

    def _answer(self, method: str, url: str, **detail: object) -> object:
        key = request_key(method, url)
        self.requests.append({"method": method, "url": url, **detail})
        if key not in self.answers:
            raise SourceUnavailableError(f"No recorded response for {key}")
        answer = self.answers[key]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, dict) and "file" in answer and self.directory is not None:
            path = self.directory / answer["file"]
            if answer.get("kind") == "page":
                return Page(url=answer["url"], html=path.read_text())
            if answer.get("kind") == "json":
                return json.loads(path.read_text())
            return path.read_bytes()
        return answer

    @staticmethod
    def _page(answer: object, url: str) -> Page:
        return answer if isinstance(answer, Page) else Page(url=url, html=str(answer))

    async def get_json(self, url, *, params=None, headers=None) -> object:
        return self._answer(
            "GET-JSON", url, params=dict(params or {}), headers=dict(headers or {})
        )

    async def get_page(self, url, *, headers=None) -> Page:
        return self._page(self._answer("GET", url, headers=dict(headers or {})), url)

    async def render(self, url: str, render: Render = Render()) -> Page:
        return self._page(self._answer("RENDER", url, render=render), url)

    async def request_page(self, url: str) -> Page:
        return self._page(self._answer("REQUEST", url), url)

    async def _document(self, method: str, url: str, *, hosts, max_bytes, **detail):
        from lambdas.download_validation import validate_download_url, validated_document

        validate_download_url(url, hosts=hosts)
        content = self._answer(method, url, **detail)
        return validated_document(
            content,  # type: ignore[arg-type]
            declared_content_type="application/pdf",
            final_url=url,
            max_bytes=max_bytes,
        )

    async def download(self, url, *, hosts, referer, max_bytes) -> DownloadedDocument:
        return await self._document(
            "DOWNLOAD", url, hosts=hosts, max_bytes=max_bytes, referer=referer
        )

    async def request_document(
        self, url, *, hosts, referer, max_bytes, seed_url=None
    ) -> DownloadedDocument:
        return await self._document(
            "REQUEST-DOCUMENT",
            url,
            hosts=hosts,
            max_bytes=max_bytes,
            referer=referer,
            seed_url=seed_url,
        )

    async def click_download(
        self, page_url, *, wait_for, link_selector, hosts, max_bytes
    ) -> DownloadedDocument:
        return await self._document(
            "CLICK",
            page_url,
            hosts=hosts,
            max_bytes=max_bytes,
            link_selector=link_selector,
        )


class RecordedFetcher:
    """Answers from a fixture directory and/or a mapping of request keys.

    ``answers`` maps ``request_key(method, url)`` to a JSON payload, a
    ``Page``, document bytes or an exception to raise.
    """

    def __init__(
        self,
        directory: Path | None = None,
        answers: Mapping[str, object] | None = None,
    ) -> None:
        self.directory = directory
        self.answers = answers
        self.sessions: list[RecordedSession] = []

    @asynccontextmanager
    async def session(self, **_options: Any) -> AsyncIterator[RecordedSession]:
        session = RecordedSession(self.directory, self.answers)
        self.sessions.append(session)
        yield session

    @property
    def requests(self) -> list[dict[str, object]]:
        return [request for session in self.sessions for request in session.requests]


class RecordingSession(LiveSession):
    """A live session that saves every page and feed it fetches."""

    def __init__(self, directory: Path, **options: Any) -> None:
        super().__init__(**options)
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        index_path = directory / "index.json"
        self.index = json.loads(index_path.read_text()) if index_path.exists() else {}

    def _save(self, key: str, kind: str, body: str, url: str | None = None) -> None:
        name = _file_name(key, ".json" if kind == "json" else ".html")
        (self.directory / name).write_text(body)
        self.index[key] = {"kind": kind, "file": name, **({"url": url} if url else {})}
        (self.directory / "index.json").write_text(json.dumps(self.index, indent=1, sort_keys=True))

    async def get_json(self, url, *, params=None, headers=None) -> object:
        payload = await super().get_json(url, params=params, headers=headers)
        self._save(request_key("GET-JSON", url), "json", json.dumps(payload, indent=1))
        return payload

    async def get_page(self, url, *, headers=None) -> Page:
        page = await super().get_page(url, headers=headers)
        self._save(request_key("GET", url), "page", _slim(page.html), page.url)
        return page

    async def render(self, url: str, render: Render = Render()) -> Page:
        page = await super().render(url, render)
        self._save(request_key("RENDER", url), "page", _slim(page.html), page.url)
        return page

    async def request_page(self, url: str) -> Page:
        page = await super().request_page(url)
        self._save(request_key("REQUEST", url), "page", _slim(page.html), page.url)
        return page


class RecordingFetcher:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @asynccontextmanager
    async def session(self, **options: Any) -> AsyncIterator[RecordingSession]:
        session = RecordingSession(self.directory, **options)
        try:
            yield session
        finally:
            await session.close()
