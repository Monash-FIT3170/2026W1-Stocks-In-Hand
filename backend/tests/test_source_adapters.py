"""Focused contracts for the five minimal ASX source adapters."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import textwrap
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

import main
from app.messages import QueueAMessage, QueueBMessage
from app.sources import SOURCES
from lambdas import discovery, source_download
from lambdas.common import PermanentDocumentError
from lambdas.download_validation import DownloadedDocument
from scrapers.base import Announcement
from scrapers.companies.anz import ANZScraper
from scrapers.companies.bhp import BHPScraper
from scrapers.companies.cba import CBAScraper
from scrapers.companies.csl import CSLScraper
from scrapers.companies.wes import WESScraper
from scrapers.registry import discover


SCRAPERS = {
    "ANZ": ANZScraper,
    "BHP": BHPScraper,
    "CBA": CBAScraper,
    "CSL": CSLScraper,
    "WES": WESScraper,
}


def _sqs_record(body: str) -> dict:
    return {
        "messageId": "message-1",
        "body": body,
        "attributes": {"ApproximateReceiveCount": "1"},
    }


@pytest.mark.parametrize(("ticker", "source"), SOURCES.items())
def test_queue_contract_supports_each_ticker_adapter_pair(ticker, source) -> None:
    message = QueueAMessage(
        scrape_run_id=uuid4(),
        ticker=ticker.lower(),
        source_url=source.source_url,
        source_adapter=source.adapter,
    )

    assert message.ticker == ticker
    assert message.source_adapter == source.adapter


def test_queue_contract_rejects_mismatched_ticker_and_adapter() -> None:
    with pytest.raises(ValidationError, match="does not match ticker"):
        QueueAMessage(
            scrape_run_id=uuid4(),
            ticker="ANZ",
            source_url=SOURCES["ANZ"].source_url,
            source_adapter="csl",
        )


def test_anz_feed_preserves_yourir_document_identity() -> None:
    announcements = ANZScraper()._parse_feed(
        {
            "items": {
                "heading": ["2026 Third Quarter Trading Update"],
                "time": ["2026-08-13 07:30:09"],
                "fileID": ["3A698699"],
            }
        }
    )

    assert len(announcements) == 1
    announcement = announcements[0]
    assert announcement.ticker == "ANZ"
    assert announcement.date == datetime(2026, 8, 13)
    assert announcement.metadata == {
        "yourir_id": "3A698699",
        "source_id": "3A698699",
    }
    assert str(announcement.pdf_url) == (
        "https://yourir.info/resources/4d216b570d08af30/announcements/anz.asx/"
        "3A698699/ANZ_2026_Third_Quarter_Trading_Update.pdf"
    )


def test_anz_feed_rejects_missing_parallel_item_arrays() -> None:
    with pytest.raises(ValueError, match="invalid item schema"):
        ANZScraper()._parse_feed({"items": {"heading": ["Results"]}})


@pytest.mark.parametrize("scraper_type", SCRAPERS.values())
def test_discovery_implementations_contain_no_file_or_download_calls(
    scraper_type,
) -> None:
    """Keep document I/O out of fetch_announcements as adapters evolve."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(scraper_type.fetch_announcements)))
    forbidden_calls = {
        "download_pdf",
        "expect_download",
        "save_as",
        "write_bytes",
        "_download_by_click",
        "_download_via_browser",
    }
    called_names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert called_names.isdisjoint(forbidden_calls)


@pytest.mark.parametrize(("ticker", "scraper_type"), SCRAPERS.items())
def test_registry_discover_does_not_call_download(
    monkeypatch: pytest.MonkeyPatch,
    ticker: str,
    scraper_type,
) -> None:
    announcement = Announcement(
        ticker=ticker,
        title="Results",
        date=datetime(2026, 1, 1),
        pdf_url=SOURCES[ticker].source_url,
        source_url=SOURCES[ticker].source_url,
    )

    async def fake_fetch(_self):
        return [announcement]

    async def forbidden_download(_self, _announcement):
        raise AssertionError("discovery called download_pdf")

    monkeypatch.setattr(scraper_type, "fetch_announcements", fake_fetch)
    monkeypatch.setattr(scraper_type, "download_pdf", forbidden_download)

    assert asyncio.run(discover(ticker)) == [announcement]


def test_bhp_discovery_message_preserves_article_resolution_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    artifact_id = uuid4()
    source = SOURCES["BHP"]
    article_url = "https://www.bhp.com/news/articles/2026/07/results"
    announcement = Announcement(
        ticker="BHP",
        title="Results",
        date=datetime.now(timezone.utc),
        pdf_url=article_url,
        source_url=source.source_url,
        metadata={"article_url": article_url, "source_id": article_url},
    )
    message = QueueAMessage(
        scrape_run_id=run_id,
        ticker="BHP",
        source_url=source.source_url,
        source_adapter="bhp",
    )
    calls: dict[str, object] = {}

    async def fake_discover(_ticker):
        return [announcement]

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(discovery.scraper_registry, "discover", fake_discover)
    monkeypatch.setattr(discovery, "database_session", fake_session)
    monkeypatch.setattr(
        "app.crud.scrape_run.get_scrape_run",
        lambda *_args: SimpleNamespace(status="queued"),
    )
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_run_discovery_started",
        lambda *_args: None,
    )

    def fake_artifact(*_args, **kwargs):
        calls["artifact"] = kwargs
        return SimpleNamespace(id=artifact_id, scrape_run_id=run_id), True

    monkeypatch.setattr(
        "app.crud.scrape_run.get_or_create_artifact",
        fake_artifact,
    )
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_run_discovery_completed",
        lambda *_args, **_kwargs: None,
    )

    class FakeSqs:
        def send_message(self, **kwargs):
            calls["queue_body"] = kwargs["MessageBody"]

    monkeypatch.setattr(discovery.boto3, "client", lambda _service: FakeSqs())
    monkeypatch.setenv("DOWNLOAD_QUEUE_URL", "https://sqs.example/queue-b")

    discovery.handler({"Records": [_sqs_record(message.model_dump_json())]}, None)

    queued = QueueBMessage.model_validate_json(calls["queue_body"])
    assert queued.ticker == "BHP"
    assert queued.source_adapter == "bhp"
    assert str(queued.document_url) == article_url
    assert queued.source_id == article_url
    assert calls["artifact"]["source_adapter"] == "bhp"


def test_api_enqueues_enabled_non_csl_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace(id=uuid4(), status="enqueueing")
    enqueue = MagicMock(return_value="message-id")
    monkeypatch.setattr(main.settings, "SUPPORTED_TICKERS", list(SOURCES))
    monkeypatch.setattr(
        main.scrape_run_crud,
        "get_or_create_queued_run",
        MagicMock(return_value=(run, True)),
    )
    monkeypatch.setattr(
        main.scrape_run_crud,
        "mark_run_queued_if_enqueueing",
        MagicMock(return_value=run),
    )
    monkeypatch.setattr(main.scrape_queue, "enqueue_discovery", enqueue)

    result = main.scrape_ticker(
        ticker_symbol="anz",
        idempotency_key="anz-run-1",
        db=MagicMock(),
    )

    queued = enqueue.call_args.args[0]
    assert result["ticker"] == "ANZ"
    assert queued.source_adapter == "anz"
    assert str(queued.source_url) == SOURCES["ANZ"].source_url


def test_csl_resolver_uses_generic_downloader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"%PDF-1.7\ncontent"
    expected = DownloadedDocument(
        content=content,
        checksum=hashlib.sha256(content).hexdigest(),
        final_url="https://investors.csl.com/report.pdf",
        content_type="application/pdf",
        document_format="pdf",
    )
    generic = MagicMock(return_value=expected)
    monkeypatch.setattr(source_download, "download_document", generic)
    message = QueueBMessage(
        scrape_run_id=uuid4(),
        artifact_id=uuid4(),
        ticker="CSL",
        source_url=SOURCES["CSL"].source_url,
        document_url=expected.final_url,
        canonical_url=expected.final_url,
        source_adapter="csl",
    )

    assert source_download.resolve_download(message, max_bytes=1024) is expected
    generic.assert_called_once_with(expected.final_url, max_bytes=1024)


def test_session_resolver_rejects_untrusted_url_before_browser_launch() -> None:
    with pytest.raises(PermanentDocumentError) as error:
        asyncio.run(
            source_download.resolve_session_download(
                source_adapter="bhp",
                source_url=SOURCES["BHP"].source_url,
                document_url="https://example.com/report.pdf",
                title="Results",
                metadata={},
                max_bytes=1024,
            )
        )

    assert error.value.code == "invalid_document_url"


def test_anz_resolver_downloads_directly_without_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_url = (
        "https://yourir.info/resources/4d216b570d08af30/announcements/"
        "anz.asx/3A698699/ANZ_2026_Third_Quarter_Trading_Update.pdf"
    )
    expected = DownloadedDocument(
        content=b"%PDF-1.7\ncontent",
        checksum="checksum",
        final_url=document_url,
        content_type="application/pdf",
        document_format="pdf",
    )
    direct_download = MagicMock(return_value=expected)
    monkeypatch.setattr(source_download, "download_document", direct_download)

    def forbidden_playwright():
        raise AssertionError("ANZ download launched Playwright")

    monkeypatch.setattr(source_download, "async_playwright", forbidden_playwright)

    result = asyncio.run(
        source_download.resolve_session_download(
            source_adapter="anz",
            source_url=SOURCES["ANZ"].source_url,
            document_url=document_url,
            title="2026 Third Quarter Trading Update",
            metadata={"yourir_id": "3A698699"},
            max_bytes=1024,
        )
    )

    assert result is expected
    direct_download.assert_called_once_with(
        document_url,
        hosts=source_download._ADAPTER_HOSTS["anz"],
        referer=SOURCES["ANZ"].source_url,
        max_bytes=1024,
    )
