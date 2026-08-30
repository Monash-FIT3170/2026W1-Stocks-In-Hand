from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from botocore.exceptions import ClientError
from pypdf import PdfWriter

from app.messages import (
    NotificationMessage,
    PublicDiscussionAnalysisMessage,
    QueueAMessage,
    QueueBMessage,
)
from lambdas import analysis, common, discovery, download
from lambdas.common import PermanentDocumentError
from lambdas.download_validation import (
    DownloadedDocument,
    download_document,
    download_pdf,
    validate_document_content,
    validate_download_url,
)
from parsing import analysis as parsing_analysis
from parsing.analysis import (
    AnalysisOutput,
    ParsedDocument,
    analyse_public_discussion_text,
    extract_pdf,
)
from scrapers.base import Announcement
from scrapers.companies.csl import CSLScraper


def test_runtime_configuration_loads_public_discussion_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_PARAMETER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY_PARAMETER", raising=False)
    parameter_values = {
        "/test/reddit-client-id": "reddit-id",
        "/test/reddit-client-secret": "reddit-secret",
        "/test/public-discussion-feed-urls": "https://example.test/feed.xml",
    }
    parameter_variables = {
        "REDDIT_CLIENT_ID": "REDDIT_CLIENT_ID_PARAMETER",
        "REDDIT_CLIENT_SECRET": "REDDIT_CLIENT_SECRET_PARAMETER",
        "PUBLIC_DISCUSSION_FEED_URLS": "PUBLIC_DISCUSSION_FEED_URLS_PARAMETER",
    }
    for value_variable, parameter_variable in parameter_variables.items():
        monkeypatch.delenv(value_variable, raising=False)
        parameter_name = f"/test/{parameter_variable.removesuffix('_PARAMETER').lower().replace('_', '-')}"
        monkeypatch.setenv(parameter_variable, parameter_name)

    ssm = MagicMock()
    ssm.get_parameter.side_effect = lambda *, Name, WithDecryption: {
        "Parameter": {"Value": parameter_values[Name]}
    }
    monkeypatch.setattr(common.boto3, "client", lambda service: ssm)
    monkeypatch.setattr(common, "_RUNTIME_CONFIGURATION_LOADED", False)

    common.load_runtime_configuration()

    assert common.os.environ["REDDIT_CLIENT_ID"] == "reddit-id"
    assert common.os.environ["REDDIT_CLIENT_SECRET"] == "reddit-secret"
    assert common.os.environ["PUBLIC_DISCUSSION_FEED_URLS"] == (
        "https://example.test/feed.xml"
    )


def test_missing_optional_public_discussion_parameters_disable_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_PARAMETER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY_PARAMETER", raising=False)
    parameter_variables = {
        "REDDIT_CLIENT_ID": "REDDIT_CLIENT_ID_PARAMETER",
        "REDDIT_CLIENT_SECRET": "REDDIT_CLIENT_SECRET_PARAMETER",
        "PUBLIC_DISCUSSION_FEED_URLS": "PUBLIC_DISCUSSION_FEED_URLS_PARAMETER",
    }
    for value_variable, parameter_variable in parameter_variables.items():
        monkeypatch.delenv(value_variable, raising=False)
        monkeypatch.setenv(parameter_variable, f"/test/{value_variable.lower()}")

    ssm = MagicMock()
    ssm.get_parameter.side_effect = ClientError(
        {"Error": {"Code": "ParameterNotFound", "Message": "missing"}},
        "GetParameter",
    )
    monkeypatch.setattr(common.boto3, "client", lambda service: ssm)
    monkeypatch.setattr(common, "_RUNTIME_CONFIGURATION_LOADED", False)

    common.load_runtime_configuration()

    assert all(common.os.environ[variable] == "" for variable in parameter_variables)


def sqs_record(body: str) -> dict:
    return {
        "messageId": "message-1",
        "body": body,
        "attributes": {"ApproximateReceiveCount": "1"},
    }


def s3_record(*, bucket: str, key: str) -> dict:
    body = {
        "Records": [
            {
                "eventName": "ObjectCreated:Put",
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                },
            }
        ]
    }
    return sqs_record(json.dumps(body))


def docx_bytes(text: str = "Revenue increased strongly.") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<?xml version="1.0"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                "</Types>"
            ),
        )
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>"
                "</w:document>"
            ),
        )
    return output.getvalue()


def test_url_validation_rejects_non_https_and_unapproved_hosts():
    with pytest.raises(PermanentDocumentError, match="allowlisted"):
        validate_download_url("http://investors.csl.com/report.pdf")
    with pytest.raises(PermanentDocumentError, match="allowlisted"):
        validate_download_url("https://example.com/report.pdf")
    with pytest.raises(PermanentDocumentError, match="allowlisted"):
        validate_download_url("https://user:password@investors.csl.com/report.pdf")


def test_download_validates_redirects_size_type_and_magic_bytes():
    content = b"%PDF-1.7\nsmall document"

    def valid_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=content,
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(valid_response)) as client:
        result = download_pdf(
            "https://investors.csl.com/report.pdf",
            max_bytes=1024,
            client=client,
            resolve_hosts=False,
        )
    assert result.content == content
    assert result.checksum == hashlib.sha256(content).hexdigest()

    def unsafe_redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://example.com/report.pdf"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(unsafe_redirect)) as client:
        with pytest.raises(PermanentDocumentError) as error:
            download_pdf(
                "https://investors.csl.com/report.pdf",
                max_bytes=1024,
                client=client,
                resolve_hosts=False,
            )
    assert error.value.code == "invalid_document_url"

    def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf", "content-length": "2048"},
            content=content,
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(oversized)) as client:
        with pytest.raises(PermanentDocumentError) as error:
            download_pdf(
                "https://investors.csl.com/report.pdf",
                max_bytes=1024,
                client=client,
                resolve_hosts=False,
            )
    assert error.value.code == "document_too_large"

    def wrong_magic(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"<html>not a PDF</html>",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(wrong_magic)) as client:
        with pytest.raises(PermanentDocumentError) as error:
            download_pdf(
                "https://investors.csl.com/report.pdf",
                max_bytes=1024,
                client=client,
                resolve_hosts=False,
            )
    assert error.value.code == "content_type_mismatch"


@pytest.mark.parametrize(
    ("content", "content_type", "expected_format"),
    [
        (b"%PDF-1.7\ncontent", "application/pdf", "pdf"),
        (b"Revenue increased.\n", "text/plain; charset=utf-8", "txt"),
        (
            b"<!doctype html><html><body>Results</body></html>",
            "text/html",
            "html",
        ),
        (
            docx_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        ),
    ],
)
def test_download_document_detects_supported_format(
    content: bytes,
    content_type: str,
    expected_format: str,
):
    def response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": content_type},
            content=content,
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        downloaded = download_document(
            "https://investors.csl.com/document",
            max_bytes=1024 * 1024,
            client=client,
            resolve_hosts=False,
        )

    assert downloaded.document_format == expected_format
    assert downloaded.extension == expected_format
    assert downloaded.checksum == hashlib.sha256(content).hexdigest()


def test_document_validation_rejects_mime_mismatch_and_unsafe_docx():
    with pytest.raises(PermanentDocumentError) as mismatch:
        validate_document_content(
            b"<!doctype html><html></html>",
            declared_content_type="application/pdf",
            final_url="https://investors.csl.com/report.pdf",
        )
    assert mismatch.value.code == "content_type_mismatch"

    with pytest.raises(PermanentDocumentError) as expanded:
        validate_document_content(
            docx_bytes("x" * 2_000),
            declared_content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            final_url="https://investors.csl.com/report.docx",
            max_docx_uncompressed_bytes=1_000,
        )
    assert expanded.value.code == "document_too_large"


def test_discovery_handler_never_downloads_or_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    run_id = uuid4()
    artifact_id = uuid4()
    message = QueueAMessage(
        scrape_run_id=run_id,
        ticker="CSL",
        source_url="https://investors.csl.com/investors/asx-announcements",
    )
    announcement = Announcement(
        ticker="CSL",
        title="Half Year Results",
        date=datetime.now(timezone.utc),
        pdf_url="https://investors.csl.com/pdf/report.pdf",
        source_url=str(message.source_url),
    )
    duplicate_announcement = Announcement(
        ticker="CSL",
        title="Duplicate link",
        date=announcement.date,
        pdf_url=f"{announcement.pdf_url}?utm_source=duplicate",
        source_url=announcement.source_url,
    )
    calls: dict[str, object] = {}

    async def fake_discover(_self):
        return [announcement, duplicate_announcement]

    async def forbidden_download(_self, _announcement):
        raise AssertionError("discovery called download_pdf")

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(CSLScraper, "fetch_announcements", fake_discover)
    monkeypatch.setattr(CSLScraper, "download_pdf", forbidden_download)
    monkeypatch.setattr(discovery, "database_session", fake_session)
    monkeypatch.setattr(
        "app.crud.scrape_run.get_scrape_run",
        # Downstream work may advance this aggregate status before Queue A is
        # acknowledged. Discovery must still finish queuing every document.
        lambda _db, _id: SimpleNamespace(status="analyzing"),
    )
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_run_discovery_started",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.crud.scrape_run.get_or_create_artifact",
        lambda *_args, **_kwargs: (
            SimpleNamespace(id=artifact_id, scrape_run_id=run_id),
            True,
        ),
    )
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_run_discovery_completed",
        lambda *_args, **kwargs: calls.setdefault("items_found", kwargs["items_found"]),
    )

    class FakeSqs:
        def send_message(self, **kwargs):
            calls.setdefault("queue_bodies", []).append(kwargs["MessageBody"])

    monkeypatch.setattr(discovery.boto3, "client", lambda service: FakeSqs())
    monkeypatch.setenv("DOWNLOAD_QUEUE_URL", "https://sqs.example/queue-b")
    before = list(tmp_path.iterdir())

    result = discovery.handler({"Records": [sqs_record(message.model_dump_json())]}, None)

    assert result == {"processed": 1}
    assert list(tmp_path.iterdir()) == before
    assert calls["items_found"] == 1
    assert len(calls["queue_bodies"]) == 1
    queued = QueueBMessage.model_validate_json(calls["queue_bodies"][0])
    assert queued.artifact_id == artifact_id
    assert str(queued.document_url) == announcement.pdf_url


def test_discovery_filters_old_documents_and_sorts_newest_first(
    monkeypatch: pytest.MonkeyPatch,
):
    now = datetime.now(timezone.utc)
    recent = Announcement(
        ticker="CSL",
        title="Recent",
        date=now - timedelta(days=1),
        pdf_url="https://investors.csl.com/recent.pdf",
        source_url="https://investors.csl.com/investors/asx-announcements",
    )
    newer = Announcement(
        ticker="CSL",
        title="Newer",
        date=now,
        pdf_url="https://investors.csl.com/newer.pdf",
        source_url=recent.source_url,
    )
    old = Announcement(
        ticker="CSL",
        title="Old",
        date=now - timedelta(days=31),
        pdf_url="https://investors.csl.com/old.pdf",
        source_url=recent.source_url,
    )
    monkeypatch.setenv("DISCOVERY_LOOKBACK_DAYS", "30")

    bounded = discovery._bounded_announcements([recent, old, newer])

    assert [announcement.title for announcement in bounded] == ["Newer", "Recent"]


def test_discovery_queues_at_most_three_new_documents(
    monkeypatch: pytest.MonkeyPatch,
):
    run_id = uuid4()
    source_url = "https://investors.csl.com/investors/asx-announcements"
    message = QueueAMessage(
        scrape_run_id=run_id,
        ticker="CSL",
        source_url=source_url,
    )
    now = datetime.now(timezone.utc)
    announcements = [
        Announcement(
            ticker="CSL",
            title=f"Document {index}",
            date=now - timedelta(minutes=index),
            pdf_url=f"https://investors.csl.com/document-{index}.pdf",
            source_url=source_url,
        )
        for index in range(5)
    ]
    queued_bodies: list[str] = []

    async def fake_discover(_ticker):
        return announcements

    @contextmanager
    def fake_session():
        yield object()

    def fake_artifact(*_args, **_kwargs):
        return SimpleNamespace(id=uuid4(), scrape_run_id=run_id), True

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
    monkeypatch.setattr(
        "app.crud.scrape_run.get_or_create_artifact",
        fake_artifact,
    )
    completed = MagicMock()
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_run_discovery_completed",
        completed,
    )

    class FakeSqs:
        def send_message(self, **kwargs):
            queued_bodies.append(kwargs["MessageBody"])

    monkeypatch.setattr(discovery.boto3, "client", lambda _service: FakeSqs())
    monkeypatch.setenv("DOWNLOAD_QUEUE_URL", "https://sqs.example/queue-b")
    monkeypatch.setenv("MAX_DOCUMENTS_PER_RUN", "3")

    discovery.handler({"Records": [sqs_record(message.model_dump_json())]}, None)

    assert len(queued_bodies) == 3
    assert [
        QueueBMessage.model_validate_json(body).title for body in queued_bodies
    ] == ["Document 0", "Document 1", "Document 2"]
    assert completed.call_args.kwargs["items_found"] == 3


def test_downloader_uses_content_addressed_key_and_never_sends_queue_c(
    monkeypatch: pytest.MonkeyPatch,
):
    run_id = uuid4()
    artifact_id = uuid4()
    content = b"%PDF-1.7\ncontent"
    checksum = hashlib.sha256(content).hexdigest()
    message = QueueBMessage(
        scrape_run_id=run_id,
        artifact_id=artifact_id,
        ticker="CSL",
        source_url="https://investors.csl.com/investors/asx-announcements",
        document_url="https://investors.csl.com/pdf/report.pdf",
        canonical_url="https://investors.csl.com/pdf/report.pdf",
        title="Results",
    )
    calls: dict[str, object] = {}

    @contextmanager
    def fake_session():
        yield object()

    class FakeS3:
        def put_object(self, **kwargs):
            calls["put"] = kwargs

    monkeypatch.setattr(
        download,
        "_load_artifact",
        lambda _message: {"status": "pending", "s3_bucket": None, "s3_key": None},
    )
    monkeypatch.setattr(download, "database_session", fake_session)
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_artifact_download_started",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_artifact_stored",
        lambda *_args, **kwargs: calls.setdefault("stored", kwargs),
    )
    monkeypatch.setattr(
        download,
        "_resolve_download",
        lambda *_args, **_kwargs: DownloadedDocument(
            content=content,
            checksum=checksum,
            final_url=str(message.document_url),
            content_type="application/pdf",
        ),
    )
    monkeypatch.setattr(download.boto3, "client", lambda service: FakeS3())
    monkeypatch.setenv("RAW_DOCUMENT_BUCKET", "private-raw-documents")

    download.handler({"Records": [sqs_record(message.model_dump_json())]}, None)

    expected_key = f"raw/CSL/{artifact_id}/{checksum}.pdf"
    assert calls["put"]["Key"] == expected_key
    assert calls["put"]["IfNoneMatch"] == "*"
    assert calls["put"]["Metadata"]["document-format"] == "pdf"
    assert calls["stored"]["s3_key"] == expected_key


def test_s3_event_contract_and_analysis_duplicate_are_idempotent(monkeypatch):
    artifact_id = UUID("123e4567-e89b-42d3-a456-426614174000")
    checksum = "a" * 64
    key = f"raw/CSL/{artifact_id}/{checksum}.pdf"
    record = s3_record(bucket="private-raw-documents", key=key)

    assert analysis.parse_s3_notifications(record) == [
        ("private-raw-documents", key, "CSL", artifact_id, checksum, "pdf")
    ]

    monkeypatch.setattr(
        analysis,
        "_artifact_state",
        lambda **_kwargs: {"completed": True, "run_id": uuid4()},
    )

    class ForbiddenS3:
        def get_object(self, **_kwargs):
            raise AssertionError("completed artifact was downloaded again")

    analysis._analyse_object(
        s3=ForbiddenS3(),
        bucket="private-raw-documents",
        key=key,
        artifact_id=artifact_id,
        checksum=checksum,
        ticker="CSL",
        document_format="pdf",
        correlation="message-1",
        attempt=2,
    )


def test_s3_event_accepts_supported_non_pdf_key_and_rejects_unknown_ticker():
    artifact_id = UUID("123e4567-e89b-42d3-a456-426614174000")
    checksum = "d" * 64
    key = f"raw/BHP/{artifact_id}/{checksum}.docx"

    assert analysis.parse_s3_notifications(
        s3_record(bucket="private-raw-documents", key=key)
    ) == [
        (
            "private-raw-documents",
            key,
            "BHP",
            artifact_id,
            checksum,
            "docx",
        )
    ]

    with pytest.raises(PermanentDocumentError) as error:
        analysis.parse_s3_notifications(
            s3_record(
                bucket="private-raw-documents",
                key=f"raw/XYZ/{artifact_id}/{checksum}.pdf",
            )
        )
    assert error.value.code == "invalid_object_key"


def test_s3_event_reconciles_an_uploaded_object_before_downloader_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    artifact_id = uuid4()
    run_id = uuid4()
    checksum = "c" * 64
    bucket = "private-raw-documents"
    key = f"raw/CSL/{artifact_id}/{checksum}.pdf"
    calls: dict[str, object] = {}

    @contextmanager
    def fake_session():
        yield object()

    class FakeS3:
        def head_object(self, **kwargs):
            assert kwargs == {"Bucket": bucket, "Key": key}
            return {
                "ContentLength": 512,
                "ContentType": "application/pdf",
                "Metadata": {
                    "artifact-id": str(artifact_id),
                    "sha256": checksum,
                    "ticker": "CSL",
                    "document-format": "pdf",
                },
            }

    artifact = SimpleNamespace(
        source_adapter="csl",
        scrape_run_id=run_id,
        title="Results",
        download_status="downloading",
        analysis_status="pending",
        s3_bucket=None,
        s3_key=None,
        checksum_sha256=None,
        ticker=SimpleNamespace(symbol="CSL"),
    )
    monkeypatch.setattr(analysis, "database_session", fake_session)
    monkeypatch.setattr("app.crud.artifact.get_artifact", lambda *_args: artifact)

    def fake_mark_stored(*_args, **kwargs):
        calls["stored"] = kwargs
        return artifact

    monkeypatch.setattr(
        "app.crud.scrape_run.mark_artifact_stored",
        fake_mark_stored,
    )

    state = analysis._artifact_state(
        s3=FakeS3(),
        artifact_id=artifact_id,
        bucket=bucket,
        key=key,
        checksum=checksum,
        ticker="CSL",
        document_format="pdf",
    )

    assert state["run_id"] == run_id
    assert calls["stored"]["s3_key"] == key
    assert calls["stored"]["file_size_bytes"] == 512


def test_analysis_stores_results_then_marks_completed(monkeypatch):
    artifact_id = uuid4()
    run_id = uuid4()
    checksum = "b" * 64
    key = f"raw/CSL/{artifact_id}/{checksum}.pdf"
    parsed = ParsedDocument(
        raw_text="Revenue increased.",
        page_count=1,
        category="HalfYearResults",
        category_confidence=1.0,
        extracted_data={},
    )
    output = AnalysisOutput(
        parsed=parsed,
        summary=None,
        summary_model=None,
        summary_prompt_version=None,
        sentiment={
            "sentiment_label": "positive",
            "label": "positive",
            "confidence_score": 0.9,
            "model_used": "ProsusAI/finbert",
        },
    )
    calls: dict[str, object] = {}
    events: list[str] = []

    @contextmanager
    def fake_session():
        events.append("session_enter")
        try:
            yield object()
        finally:
            events.append("session_exit")

    def fake_started(*_args, **_kwargs):
        calls["started"] = True
        events.append("started")

    def fake_stored(*_args, **kwargs):
        calls["stored"] = kwargs
        events.append("stored")

    def fake_completed(*_args, **_kwargs):
        calls["completed"] = True
        events.append("completed")

    def fake_publish(**kwargs):
        calls["published"] = kwargs
        events.append("published")

    monkeypatch.setattr(
        analysis,
        "_artifact_state",
        lambda **_kwargs: {
            "completed": False,
            "run_id": run_id,
            "title": "Half Year Results",
        },
    )
    monkeypatch.setattr(
        analysis,
        "_read_s3_document",
        lambda *_args, **_kwargs: b"%PDF-1.7",
    )
    monkeypatch.setattr(analysis, "analyse_document", lambda *_args, **_kwargs: output)
    monkeypatch.setattr(analysis, "database_session", fake_session)
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setattr(analysis, "_publish_notification", fake_publish)
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_artifact_analysis_started",
        fake_started,
    )
    monkeypatch.setattr(
        "app.crud.artifact.store_artifact_analysis",
        fake_stored,
    )
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_artifact_analysis_completed",
        fake_completed,
    )

    analysis._analyse_object(
        s3=object(),
        bucket="private-raw-documents",
        key=key,
        artifact_id=artifact_id,
        checksum=checksum,
        ticker="CSL",
        document_format="pdf",
        correlation="message-1",
        attempt=1,
    )

    assert calls["started"] is True
    assert calls["stored"]["raw_text"] == "Revenue increased."
    assert calls["stored"]["sentiment"]["sentiment_label"] == "positive"
    assert calls["completed"] is True
    assert calls["published"] == {
        "artifact_id": artifact_id,
        "ticker": "CSL",
        "scrape_run_id": run_id,
        "sentiment": calls["stored"]["sentiment"],
    }
    assert events == [
        "session_enter",
        "started",
        "session_exit",
        "session_enter",
        "stored",
        "session_exit",
        "session_enter",
        "completed",
        "session_exit",
        "published",
    ]


def test_analysis_notification_matches_consumer_contract(monkeypatch):
    artifact_id = uuid4()
    run_id = uuid4()
    sqs = MagicMock()
    client_factory = MagicMock(return_value=sqs)
    monkeypatch.setenv(
        "NOTIFICATION_QUEUE_URL",
        "https://sqs.ap-southeast-2.amazonaws.com/123/notifications",
    )
    monkeypatch.setattr(analysis.boto3, "client", client_factory)
    analysis._notification_sqs_client.cache_clear()

    try:
        for _ in range(2):
            analysis._publish_notification(
                artifact_id=artifact_id,
                ticker="csl",
                scrape_run_id=run_id,
                sentiment={
                    "sentiment_label": "positive",
                    "confidence_score": 0.9,
                },
            )
    finally:
        analysis._notification_sqs_client.cache_clear()

    client_factory.assert_called_once_with("sqs")
    assert sqs.send_message.call_count == 2
    published = sqs.send_message.call_args.kwargs
    assert published["QueueUrl"].endswith("/notifications")
    body = json.loads(published["MessageBody"])
    assert set(body) == {
        "schema_version",
        "artifact_id",
        "ticker",
        "scrape_run_id",
        "sentiment_label",
        "confidence_score",
    }
    message = NotificationMessage.model_validate(body)
    assert message.artifact_id == artifact_id
    assert message.scrape_run_id == run_id
    assert message.ticker == "CSL"
    assert message.sentiment_label == "positive"


@pytest.mark.parametrize(
    ("enabled", "label"),
    [("false", "positive"), ("true", "neutral")],
)
def test_analysis_notification_prefilter_skips_publish(monkeypatch, enabled, label):
    publish = MagicMock()
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", enabled)
    monkeypatch.setattr(analysis, "_publish_notification", publish)

    analysis._try_publish_notification(
        artifact_id=uuid4(),
        ticker="CSL",
        scrape_run_id=uuid4(),
        sentiment={"sentiment_label": label, "confidence_score": 0.9},
        correlation="message-1",
        attempt=1,
    )

    publish.assert_not_called()


def test_analysis_notification_publish_failure_never_raises(monkeypatch, caplog):
    artifact_id = uuid4()
    run_id = uuid4()
    private_detail = "private queue detail"
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")

    def fail_publish(**_kwargs):
        raise RuntimeError(private_detail)

    monkeypatch.setattr(analysis, "_publish_notification", fail_publish)

    with caplog.at_level(logging.ERROR):
        analysis._try_publish_notification(
            artifact_id=artifact_id,
            ticker="CSL",
            scrape_run_id=run_id,
            sentiment={
                "sentiment_label": "negative",
                "confidence_score": 0.8,
            },
            correlation="message-1",
            attempt=2,
        )

    assert private_detail not in caplog.text
    event = json.loads(caplog.records[-1].message)
    assert event == {
        "stage": "analysis",
        "event": "notification_publish_failed",
        "correlation_id": "message-1",
        "run_id": str(run_id),
        "artifact_id": str(artifact_id),
        "attempt": 2,
        "error_code": "RuntimeError",
    }


def test_analysis_worker_parses_public_discussion_message() -> None:
    message = PublicDiscussionAnalysisMessage(artifact_id=uuid4())

    parsed = analysis.parse_public_discussion_message(
        sqs_record(message.model_dump_json())
    )

    assert parsed == message
    assert analysis.parse_public_discussion_message(
        s3_record(bucket="raw", key="raw/invalid")
    ) is None


def test_analysis_handler_dispatches_public_discussion_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_id = uuid4()
    analyse = MagicMock()
    monkeypatch.setattr(analysis, "_analyse_public_discussion_artifact", analyse)
    message = PublicDiscussionAnalysisMessage(artifact_id=artifact_id)

    result = analysis.handler(
        {"Records": [sqs_record(message.model_dump_json())]},
        None,
    )

    assert result == {"processed": 1}
    analyse.assert_called_once_with(
        artifact_id=artifact_id,
        correlation="message-1",
        attempt=1,
    )


def test_public_discussion_analysis_uses_source_text_and_discussion_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyse_sentiment = MagicMock(
        return_value={
            "sentiment_label": "positive",
            "label": "bullish",
            "confidence_score": 0.8,
            "model_used": "test-finbert",
        }
    )
    summarise = MagicMock(
        return_value={
            "summary": "The author expects BHP earnings to rise.",
            "about": "The post discusses BHP earnings.",
            "changed": "The author claims the outlook improved.",
            "matters": "The claim may affect investor expectations.",
        }
    )
    monkeypatch.setattr("app.services.sentiment.analyse_text", analyse_sentiment)
    monkeypatch.setattr("app.services.groq.summarise_public_discussion", summarise)
    monkeypatch.setattr("app.services.groq.active_model_name", lambda: "test-groq")

    output = analyse_public_discussion_text(
        title="$BHP earnings outlook",
        raw_text="I think profit will rise next year.",
        source_type="reddit",
    )

    assert output.parsed.category == "USER_DISCUSSION"
    assert output.sentiment["sentiment_label"] == "positive"
    assert output.summary_model == "test-groq"
    analyse_sentiment.assert_called_once_with(
        "$BHP earnings outlook\n\nI think profit will rise next year."
    )
    summarise.assert_called_once_with(
        title="$BHP earnings outlook",
        raw_text="I think profit will rise next year.",
        source_type="reddit",
    )


def test_analysis_worker_persists_public_discussion_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_id = uuid4()
    run_id = uuid4()
    output = AnalysisOutput(
        parsed=ParsedDocument(
            raw_text="Investors discuss $BHP earnings.",
            page_count=1,
            category="USER_DISCUSSION",
            category_confidence=1.0,
            extracted_data={},
        ),
        summary={
            "summary": "Investors discuss BHP earnings.",
            "about": "The post is about BHP.",
            "changed": "No claimed change identified.",
            "matters": "Earnings interest BHP investors.",
        },
        summary_model="test-groq",
        summary_prompt_version="groq-public-discussion-summary-v1",
        sentiment={
            "sentiment_label": "neutral",
            "label": "neutral",
            "confidence_score": 0.9,
            "model_used": "test-finbert",
        },
    )
    calls: dict[str, object] = {}

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(
        analysis,
        "_public_discussion_artifact_state",
        lambda _artifact_id: {
            "completed": False,
            "run_id": run_id,
            "title": "$BHP earnings",
            "raw_text": "Investors discuss $BHP earnings.",
            "source_type": "reddit",
        },
    )
    monkeypatch.setattr(
        analysis,
        "analyse_public_discussion_text",
        lambda **_kwargs: output,
    )
    monkeypatch.setattr(analysis, "database_session", fake_session)
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_inline_artifact_analysis_started",
        lambda *_args, **_kwargs: calls.setdefault("started", True),
    )
    monkeypatch.setattr(
        "app.crud.artifact.store_artifact_analysis",
        lambda *_args, **kwargs: calls.setdefault("stored", kwargs),
    )
    monkeypatch.setattr(
        "app.crud.scrape_run.mark_inline_artifact_analysis_completed",
        lambda *_args, **_kwargs: calls.setdefault("completed", True),
    )

    analysis._analyse_public_discussion_artifact(
        artifact_id=artifact_id,
        correlation="message-1",
        attempt=1,
    )

    assert calls["started"] is True
    assert calls["stored"]["metadata"]["category"] == "user_discussion"
    assert calls["stored"]["sentiment"]["sentiment_label"] == "neutral"
    assert calls["completed"] is True


def test_pdf_page_limit_is_permanent(tmp_path):
    path = tmp_path / "two-pages.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(PermanentDocumentError) as error:
        extract_pdf(path.read_bytes(), max_pages=1)
    assert error.value.code == "too_many_pages"


def test_scanned_pdf_uses_bounded_ocr_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    path = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as output:
        writer.write(output)

    calls: dict[str, int] = {}

    def fake_ocr(_content, *, page_count, max_ocr_pages, max_pixels_per_page):
        calls.update(
            page_count=page_count,
            max_ocr_pages=max_ocr_pages,
            max_pixels_per_page=max_pixels_per_page,
        )
        return "Scanned revenue increased."

    monkeypatch.setattr(parsing_analysis, "_ocr_pdf", fake_ocr)

    parsed = extract_pdf(
        path.read_bytes(),
        max_pages=10,
        max_ocr_pages=3,
        max_ocr_pixels_per_page=1_000_000,
    )

    assert parsed.raw_text == "Scanned revenue increased."
    assert calls == {
        "page_count": 1,
        "max_ocr_pages": 3,
        "max_pixels_per_page": 1_000_000,
    }


def test_scanned_pdf_over_ocr_page_limit_is_permanent(tmp_path):
    path = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(PermanentDocumentError) as error:
        extract_pdf(path.read_bytes(), max_pages=10, max_ocr_pages=1)
    assert error.value.code == "ocr_page_limit"


def test_non_pdf_extractors_return_only_visible_text():
    text = parsing_analysis.extract_text(b"\xef\xbb\xbfRevenue increased.")
    html = parsing_analysis.extract_html(
        b"<!doctype html><html><style>hidden</style><body>"
        b"<h1>Results</h1><script>secret()</script><p>Profit rose.</p>"
        b"</body></html>"
    )
    docx = parsing_analysis.extract_docx(docx_bytes("Cash flow improved."))

    assert text.raw_text == "Revenue increased."
    assert "Results" in html.raw_text
    assert "Profit rose." in html.raw_text
    assert "hidden" not in html.raw_text
    assert "secret" not in html.raw_text
    assert docx.raw_text == "Cash flow improved."
