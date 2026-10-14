from __future__ import annotations

import hashlib
import io
import json
import zipfile
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from botocore.exceptions import ClientError
from pypdf import PdfWriter

from app.messages import PublicDiscussionAnalysisMessage
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
from parsing.analysis import extract_pdf


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


CSL_HOSTS = frozenset({"investors.csl.com"})


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
        validate_download_url("http://investors.csl.com/report.pdf", hosts=CSL_HOSTS)
    with pytest.raises(PermanentDocumentError, match="allowlisted"):
        validate_download_url("https://example.com/report.pdf", hosts=CSL_HOSTS)
    with pytest.raises(PermanentDocumentError, match="allowlisted"):
        validate_download_url(
            "https://user:password@investors.csl.com/report.pdf", hosts=CSL_HOSTS
        )


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
            hosts=CSL_HOSTS,
            referer="https://investors.csl.com/",
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
                hosts=CSL_HOSTS,
                referer="https://investors.csl.com/",
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
                hosts=CSL_HOSTS,
                referer="https://investors.csl.com/",
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
                hosts=CSL_HOSTS,
                referer="https://investors.csl.com/",
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
                hosts=CSL_HOSTS,
                referer="https://investors.csl.com/",
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
            hosts=CSL_HOSTS,
            referer="https://investors.csl.com/",
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


def test_analysis_worker_parses_public_discussion_message() -> None:
    message = PublicDiscussionAnalysisMessage(artifact_id=uuid4())

    parsed = analysis.parse_public_discussion_message(
        sqs_record(message.model_dump_json())
    )

    assert parsed == message
    assert analysis.parse_public_discussion_message(
        s3_record(bucket="raw", key="raw/invalid")
    ) is None


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
