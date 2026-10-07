"""Contracts every source adapter keeps with the queue messages and hosts."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.messages import QueueAMessage, QueueBMessage
from app.sources import SOURCES
from lambdas import download
from lambdas.common import PermanentDocumentError
from scrapers.adapter import DocumentRequest
from scrapers.registry import adapter_for


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


@pytest.mark.parametrize(("ticker", "source"), SOURCES.items())
def test_download_worker_accepts_each_canonical_pair(ticker, source) -> None:
    message = QueueBMessage(
        scrape_run_id=uuid4(),
        artifact_id=uuid4(),
        ticker=ticker,
        source_url=source.source_url,
        document_url=source.source_url,
        canonical_url=source.source_url,
        source_adapter=source.adapter,
    )

    parsed = download._parse_message(_sqs_record(message.model_dump_json()))

    assert parsed.ticker == ticker
    assert parsed.source_adapter == source.adapter


def test_download_worker_rejects_mismatched_ticker_and_adapter() -> None:
    source = SOURCES["ANZ"]
    body = json.dumps(
        {
            "schema_version": 1,
            "scrape_run_id": str(uuid4()),
            "artifact_id": str(uuid4()),
            "ticker": "ANZ",
            "source_url": source.source_url,
            "document_url": source.source_url,
            "canonical_url": source.source_url,
            "source_adapter": "csl",
        }
    )

    with pytest.raises(PermanentDocumentError) as error:
        download._parse_message(_sqs_record(body))

    assert error.value.code == "invalid_message"


@pytest.mark.parametrize("ticker", sorted(SOURCES))
def test_each_adapter_may_contact_its_own_announcements_page(ticker: str) -> None:
    adapter = adapter_for(ticker)

    assert urlsplit(adapter.source_url).hostname in adapter.hosts


def test_download_rejects_a_document_outside_the_companys_hosts() -> None:
    with pytest.raises(PermanentDocumentError) as error:
        asyncio.run(
            adapter_for("BHP").fetch_document(
                DocumentRequest(document_url="https://example.com/report.pdf"),
                max_bytes=1024,
            )
        )

    assert error.value.code == "invalid_document_url"
