from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from botocore.exceptions import ClientError
from pypdf import PdfWriter

from app.messages import (
    NotificationMessage,
    PublicDiscussionAnalysisMessage,
)
from lambdas import analysis, common
from lambdas.common import PermanentDocumentError
from lambdas.download_validation import (
    DownloadedDocument,
    download_document,
    validate_document_content,
    validate_download_url,
    validated_document,
)
from parsing import analysis as parsing_analysis
from parsing.analysis import (
    AnalysisOutput,
    ParsedDocument,
    analyse_news_text,
    analyse_public_discussion_text,
    extract_pdf,
)


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


def test_runtime_configuration_loads_marketaux_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_PARAMETER", raising=False)
    monkeypatch.delenv("MARKETAUX_API_TOKEN", raising=False)
    monkeypatch.setenv(
        "MARKETAUX_API_TOKEN_PARAMETER",
        "/test/marketaux-api-token",
    )
    ssm = MagicMock()
    ssm.get_parameter.return_value = {
        "Parameter": {"Value": "marketaux-test-token"}
    }
    monkeypatch.setattr(common.boto3, "client", lambda service: ssm)
    monkeypatch.setattr(common, "_RUNTIME_CONFIGURATION_LOADED", False)

    common.load_runtime_configuration()

    assert common.os.environ["MARKETAUX_API_TOKEN"] == "marketaux-test-token"
    ssm.get_parameter.assert_called_once_with(
        Name="/test/marketaux-api-token",
        WithDecryption=True,
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
        result = download_document(
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
            download_document(
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
            download_document(
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
            download_document(
                "https://investors.csl.com/report.pdf",
                max_bytes=1024,
                client=client,
                resolve_hosts=False,
            )
    assert error.value.code == "content_type_mismatch"


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (200, None),
        (404, "document_not_found"),
        (403, "document_rejected"),
        (410, "document_rejected"),
        (429, RuntimeError),
        (408, RuntimeError),
        (503, RuntimeError),
        (304, RuntimeError),
    ],
)
def test_document_responses_classify_their_status(status: int, outcome) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.7\ncontent",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        def download():
            return download_document(
                "https://investors.csl.com/report.pdf",
                max_bytes=1024,
                client=client,
                resolve_hosts=False,
            )

        if outcome is None:
            assert download().document_format == "pdf"
        elif outcome is RuntimeError:
            with pytest.raises(RuntimeError, match=str(status)):
                download()
        else:
            with pytest.raises(PermanentDocumentError) as error:
                download()
            assert error.value.code == outcome


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


def test_only_validation_builds_a_downloaded_document():
    content = b"%PDF-1.7\ncontent"

    document = validated_document(
        content,
        declared_content_type="application/octet-stream",
        final_url="https://investors.csl.com/report.pdf",
        max_bytes=1024,
    )

    assert document.document_format == "pdf"
    assert document.content_type == "application/pdf"
    assert document.checksum == hashlib.sha256(content).hexdigest()
    with pytest.raises(TypeError, match="validated_document"):
        DownloadedDocument(
            content=content,
            final_url="https://investors.csl.com/report.pdf",
            document_format="pdf",
        )
    with pytest.raises(PermanentDocumentError) as too_large:
        validated_document(
            content,
            declared_content_type="application/pdf",
            final_url="https://investors.csl.com/report.pdf",
            max_bytes=8,
        )
    assert too_large.value.code == "document_too_large"


def test_document_validation_rejects_mime_mismatch_and_unsafe_docx():
    with pytest.raises(PermanentDocumentError) as mismatch:
        validate_document_content(
            b"<!doctype html><html></html>",
            declared_content_type="application/pdf",
        )
    assert mismatch.value.code == "content_type_mismatch"

    with pytest.raises(PermanentDocumentError) as expanded:
        validate_document_content(
            docx_bytes("x" * 2_000),
            declared_content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            max_docx_uncompressed_bytes=1_000,
        )
    assert expanded.value.code == "document_too_large"

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
    [("false", "positive"), ("true", "unknown"), ("true", None)],
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


def test_analysis_handler_dispatches_bounded_summary_field_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repair = MagicMock(return_value={"updated": 4, "missing_after": 82})
    monkeypatch.setattr(analysis, "_resummarise_missing_fields", repair)

    result = analysis.handler(
        {
            "operation": "resummarise_missing_fields",
            "apply": True,
            "confirmation": "RESUMMARISE_MISSING_FIELDS",
            "limit": 4,
        },
        None,
    )

    assert result == {"updated": 4, "missing_after": 82}
    repair.assert_called_once_with(apply=True, limit=4)


def test_analysis_handler_requires_confirmation_for_summary_repair_apply() -> None:
    with pytest.raises(ValueError, match="requires confirmation"):
        analysis.handler(
            {
                "operation": "resummarise_missing_fields",
                "apply": True,
                "limit": 4,
            },
            None,
        )


def test_summary_values_preserve_display_clarity_and_prompt_fields() -> None:
    output = SimpleNamespace(
        summary={
            "summary": "The company announced an update.",
            "about": "The filing covers the update.",
            "changed": "A new program was announced.",
            "matters": "The program may affect investors.",
            "confirmed_facts": ["The program was announced."],
            "speculation": ["The program may affect investors."],
        },
        summary_model="bedrock:test-model",
        summary_prompt_version="llm-announcement-summary-v3",
    )

    result = analysis._summary_values(output)

    assert result == {
        "summary_text": (
            "The company announced an update.\n\n"
            "The filing covers the update.\n\n"
            "A new program was announced.\n\n"
            "The program may affect investors."
        ),
        "model_used": "bedrock:test-model",
        "prompt_version": "llm-announcement-summary-v3",
        "summary": "The company announced an update.",
        "about": "The filing covers the update.",
        "changed": "A new program was announced.",
        "matters": "The program may affect investors.",
        "confirmed_facts": ["The program was announced."],
        "speculation": ["The program may affect investors."],
    }


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
    monkeypatch.setattr("app.services.llm.summarise_public_discussion", summarise)
    monkeypatch.setattr(
        "app.services.llm.active_model_name",
        lambda: "bedrock:test-model",
    )

    output = analyse_public_discussion_text(
        title="$BHP earnings outlook",
        raw_text="I think profit will rise next year.",
        source_type="reddit",
    )

    assert output.parsed.category == "USER_DISCUSSION"
    assert output.sentiment["sentiment_label"] == "positive"
    assert output.summary_model == "bedrock:test-model"
    analyse_sentiment.assert_called_once_with(
        "$BHP earnings outlook\n\nI think profit will rise next year."
    )
    summarise.assert_called_once_with(
        title="$BHP earnings outlook",
        raw_text="I think profit will rise next year.",
        source_type="reddit",
    )


def test_news_analysis_uses_source_text_and_news_prompt(
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
            "summary": "BHP reported stronger copper production.",
            "about": "The article covers BHP production.",
            "changed": "Reported copper production increased.",
            "matters": "Higher output may affect revenue expectations.",
        }
    )
    monkeypatch.setattr("app.services.sentiment.analyse_text", analyse_sentiment)
    monkeypatch.setattr("app.services.llm.summarise_news_article", summarise)
    monkeypatch.setattr(
        "app.services.llm.active_model_name",
        lambda: "bedrock:test-model",
    )

    output = analyse_news_text(
        title="BHP production update",
        raw_text="BHP reported stronger copper production.",
        source_name="Publisher",
    )

    assert output.parsed.category == "NEWS_ARTICLE"
    assert output.sentiment["sentiment_label"] == "positive"
    assert output.summary_model == "bedrock:test-model"
    analyse_sentiment.assert_called_once_with(
        "BHP production update\n\nBHP reported stronger copper production."
    )
    summarise.assert_called_once_with(
        title="BHP production update",
        source_name="Publisher",
        raw_text="BHP reported stronger copper production.",
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
        summary_model="bedrock:test-model",
        summary_prompt_version="llm-public-discussion-summary-v2",
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


def test_analysis_worker_persists_news_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_id = uuid4()
    output = AnalysisOutput(
        parsed=ParsedDocument(
            raw_text="BHP reported stronger copper production.",
            page_count=1,
            category="NEWS_ARTICLE",
            category_confidence=1.0,
            extracted_data={},
        ),
        summary={
            "summary": "BHP reported stronger copper production.",
            "about": "The article covers BHP production.",
            "changed": "Reported copper production increased.",
            "matters": "Higher output may affect revenue expectations.",
        },
        summary_model="bedrock:test-model",
        summary_prompt_version="llm-news-summary-v2",
        sentiment={
            "sentiment_label": "positive",
            "label": "bullish",
            "confidence_score": 0.8,
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
            "run_id": None,
            "title": "BHP production update",
            "raw_text": "BHP reported stronger copper production.",
            "source_type": "news",
            "source_name": "Publisher",
        },
    )
    monkeypatch.setattr(
        analysis,
        "analyse_news_text",
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
    assert calls["stored"]["metadata"]["category"] == "news_article"
    assert calls["stored"]["summary"]["changed"] == (
        "Reported copper production increased."
    )
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
