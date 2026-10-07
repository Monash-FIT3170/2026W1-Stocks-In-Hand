"""How source adapters reach a company's website.

Adapters take a fetcher instead of opening connections themselves, so tests
can replace the live web with recorded responses (``RecordedFetcher``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

import httpx

if TYPE_CHECKING:
    from lambdas.download_validation import DownloadedDocument

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class Fetcher(Protocol):
    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        """GET a JSON document."""

    async def download(
        self,
        url: str,
        *,
        hosts: frozenset[str],
        referer: str,
        max_bytes: int,
    ) -> DownloadedDocument:
        """Download and validate one document from an allowed host."""


class HttpFetcher:
    """The live web over plain HTTP."""

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"},
        ) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()

    async def download(
        self,
        url: str,
        *,
        hosts: frozenset[str],
        referer: str,
        max_bytes: int,
    ) -> DownloadedDocument:
        from lambdas.download_validation import download_document

        return await asyncio.to_thread(
            download_document,
            url,
            hosts=hosts,
            referer=referer,
            max_bytes=max_bytes,
        )


class RecordedFetcher:
    """Answers from recorded responses, for tests and offline experiments.

    ``responses`` maps a URL to its JSON payload, the bytes of a PDF, or an
    exception to raise. Every request is kept in ``requests``.
    """

    def __init__(self, responses: Mapping[str, object]) -> None:
        self.responses = dict(responses)
        self.requests: list[dict[str, object]] = []

    def _answer(self, url: str, **request: object) -> object:
        self.requests.append({"url": url, **request})
        if url not in self.responses:
            raise httpx.ConnectError(f"No recorded response for {url}")
        answer = self.responses[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        return self._answer(url, params=dict(params or {}), headers=dict(headers or {}))

    async def download(
        self,
        url: str,
        *,
        hosts: frozenset[str],
        referer: str,
        max_bytes: int,
    ) -> DownloadedDocument:
        from lambdas.download_validation import validate_download_url, validated_document

        validate_download_url(url, hosts=hosts)
        content = self._answer(url, referer=referer)
        return validated_document(
            content,  # type: ignore[arg-type]
            declared_content_type="application/pdf",
            final_url=url,
            max_bytes=max_bytes,
        )
