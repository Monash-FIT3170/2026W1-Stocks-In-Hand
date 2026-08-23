from __future__ import annotations

import io
import math
import os
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
from typing import Any

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from lambdas.common import PermanentDocumentError
from lambdas.download_validation import DocumentFormat
from parsing.classifier import classify


@dataclass(frozen=True)
class ParsedDocument:
    raw_text: str
    page_count: int
    category: str
    category_confidence: float
    extracted_data: dict[str, Any]


@dataclass(frozen=True)
class AnalysisOutput:
    parsed: ParsedDocument
    summary: dict[str, str] | None
    summary_model: str | None
    summary_prompt_version: str | None
    sentiment: dict[str, Any]


@lru_cache(maxsize=1)
def _ocr_engine():
    # Imported lazily so ordinary text PDFs do not pay the OCR startup cost.
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def _ocr_pdf(
    content: bytes,
    *,
    page_count: int,
    max_ocr_pages: int,
    max_pixels_per_page: int,
) -> str:
    if page_count > max_ocr_pages:
        raise PermanentDocumentError(
            "Scanned PDF exceeds the configured OCR page limit",
            code="ocr_page_limit",
        )

    import pypdfium2 as pdfium

    lines: list[str] = []
    try:
        document = pdfium.PdfDocument(content)
        try:
            for page_index in range(page_count):
                page = document[page_index]
                try:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        continue
                    scale = min(
                        2.0,
                        math.sqrt(max_pixels_per_page / (width * height)),
                    )
                    bitmap = page.render(scale=max(scale, 0.25))
                    try:
                        result, _elapsed = _ocr_engine()(bitmap.to_numpy())
                    finally:
                        bitmap.close()
                    if result:
                        lines.extend(
                            str(item[1]).strip()
                            for item in result
                            if len(item) > 1 and str(item[1]).strip()
                        )
                finally:
                    page.close()
        finally:
            document.close()
    except PermanentDocumentError:
        raise
    except Exception as exc:
        raise PermanentDocumentError(
            "Scanned PDF could not be rendered for OCR",
            code="ocr_failed",
        ) from exc
    return "\n".join(lines).replace("\x00", "").strip()


def extract_pdf(
    content: bytes,
    *,
    max_pages: int,
    max_ocr_pages: int = 20,
    max_ocr_pixels_per_page: int = 8_000_000,
) -> ParsedDocument:
    if not content.startswith(b"%PDF-"):
        raise PermanentDocumentError("S3 object is not a PDF", code="invalid_pdf")
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise PermanentDocumentError(
                "Encrypted PDF cannot be processed",
                code="encrypted_pdf",
            )
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise PermanentDocumentError(
                "PDF exceeds the configured page limit",
                code="too_many_pages",
            )
        raw_text = (
            "\n".join(page.extract_text() or "" for page in reader.pages)
            .replace("\x00", "")
            .strip()
        )
    except PermanentDocumentError:
        raise
    except (PyPdfError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise PermanentDocumentError(
            "PDF could not be parsed",
            code="corrupt_pdf",
        ) from exc

    if not raw_text:
        raw_text = _ocr_pdf(
            content,
            page_count=page_count,
            max_ocr_pages=max_ocr_pages,
            max_pixels_per_page=max_ocr_pixels_per_page,
        )
    if not raw_text:
        raise PermanentDocumentError(
            "PDF contains no text detectable by extraction or OCR",
            code="no_extractable_text",
        )

    # The title is supplied by the artifact in the handler. It is deliberately
    # not inferred from PDF metadata, which is often untrusted or malformed.
    return ParsedDocument(
        raw_text=raw_text,
        page_count=page_count,
        category="UNKNOWN",
        category_confidence=0.0,
        extracted_data={},
    )


def _text_document(raw_text: str) -> ParsedDocument:
    cleaned = raw_text.replace("\x00", "").strip()
    if not cleaned:
        raise PermanentDocumentError(
            "Document contains no extractable text",
            code="no_extractable_text",
        )
    return ParsedDocument(
        raw_text=cleaned,
        page_count=1,
        category="UNKNOWN",
        category_confidence=0.0,
        extracted_data={},
    )


def extract_text(content: bytes) -> ParsedDocument:
    try:
        return _text_document(content.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise PermanentDocumentError(
            "Plain text document is not UTF-8",
            code="invalid_text_encoding",
        ) from exc


class _VisibleHtmlText(HTMLParser):
    _IGNORED = {"script", "style", "noscript", "template", "svg"}
    _BREAKS = {
        "article",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        tag = tag.lower()
        if tag in self._IGNORED:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self._BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._IGNORED and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in self._BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def extract_html(content: bytes) -> ParsedDocument:
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PermanentDocumentError(
            "HTML document is not UTF-8",
            code="invalid_html_encoding",
        ) from exc
    parser = _VisibleHtmlText()
    try:
        parser.feed(source)
        parser.close()
    except (ValueError, TypeError) as exc:
        raise PermanentDocumentError(
            "HTML document could not be parsed",
            code="invalid_html",
        ) from exc
    text = "\n".join(
        cleaned
        for line in "".join(parser.parts).splitlines()
        if (cleaned := " ".join(line.split()))
    )
    return _text_document(text)


def extract_docx(content: bytes) -> ParsedDocument:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
    except (
        KeyError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        DefusedXmlException,
        OSError,
    ) as exc:
        raise PermanentDocumentError(
            "DOCX document could not be parsed",
            code="invalid_docx",
        ) from exc

    parts: list[str] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "t" and element.text:
            parts.append(element.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag in {"br", "cr", "p"}:
            parts.append("\n")
    return _text_document("".join(parts))


def extract_document(
    content: bytes,
    *,
    document_format: DocumentFormat,
    max_pages: int,
    max_ocr_pages: int,
) -> ParsedDocument:
    if document_format == "pdf":
        return extract_pdf(
            content,
            max_pages=max_pages,
            max_ocr_pages=max_ocr_pages,
            max_ocr_pixels_per_page=int(
                os.getenv("MAX_OCR_PIXELS_PER_PAGE", "8000000")
            ),
        )
    if document_format == "txt":
        return extract_text(content)
    if document_format == "html":
        return extract_html(content)
    if document_format == "docx":
        return extract_docx(content)
    raise PermanentDocumentError(
        "Document format is not supported",
        code="unsupported_document_format",
    )


def apply_rules(parsed: ParsedDocument, *, title: str) -> ParsedDocument:
    category, confidence, _ = classify(title, parsed.raw_text)
    extracted_data = category.extract(title, parsed.raw_text) if category else {}
    return ParsedDocument(
        raw_text=parsed.raw_text,
        page_count=parsed.page_count,
        category=category.__name__ if category else "UNKNOWN",
        category_confidence=confidence,
        extracted_data=extracted_data,
    )


def analyse_document(
    content: bytes,
    *,
    title: str,
    max_pages: int,
    document_format: DocumentFormat = "pdf",
    max_ocr_pages: int | None = None,
) -> AnalysisOutput:
    parsed = apply_rules(
        extract_document(
            content,
            document_format=document_format,
            max_pages=max_pages,
            max_ocr_pages=max_ocr_pages
            if max_ocr_pages is not None
            else int(os.getenv("MAX_OCR_PAGES", "5")),
        ),
        title=title,
    )

    # Sentiment is based on deterministic source text. A summary response must
    # not change the FinBERT input on message retries.
    from app.services import sentiment as sentiment_service

    max_chars = int(os.getenv("MAX_ANALYSIS_CHARS", "50000"))
    sentiment_text = f"{title}\n\n{parsed.raw_text}"[:max_chars]
    sentiment = sentiment_service.analyse_text(sentiment_text)

    from app.services import summary as summary_service

    summary: dict[str, str] | None = None
    summary_model: str | None = None
    summary_prompt_version: str | None = None
    try:
        summary = summary_service.summarise_announcement(
            title=title,
            category=parsed.category,
            extracted_data=parsed.extracted_data,
            raw_text=parsed.raw_text,
        )
        summary_model = summary_service.active_model_name()
        summary_prompt_version = summary_service.active_prompt_version()
    except RuntimeError as exc:
        if "not configured" not in str(exc).lower():
            raise

    return AnalysisOutput(
        parsed=parsed,
        summary=summary,
        summary_model=summary_model,
        summary_prompt_version=summary_prompt_version,
        sentiment=sentiment,
    )
