from __future__ import annotations

import hashlib
import io
import ipaddress
import os
import socket
import zipfile
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx

from lambdas.common import PermanentDocumentError

PDF_MAGIC = b"%PDF-"
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
REDIRECT_CODES = {301, 302, 303, 307, 308}
DEFAULT_ALLOWED_HOSTS = (
    "investors.csl.com",
    "announcements.asx.com.au",
    "wcsecure.weblink.com.au",
)
DocumentFormat = Literal["pdf", "txt", "html", "docx"]
DOCUMENT_EXTENSIONS: dict[DocumentFormat, str] = {
    "pdf": "pdf",
    "txt": "txt",
    "html": "html",
    "docx": "docx",
}
DOCUMENT_CONTENT_TYPES: dict[DocumentFormat, str] = {
    "pdf": "application/pdf",
    "txt": "text/plain",
    "html": "text/html",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
FORMAT_CONTENT_TYPES: dict[DocumentFormat, frozenset[str]] = {
    "pdf": frozenset({"application/pdf", "application/octet-stream"}),
    "txt": frozenset({"text/plain"}),
    "html": frozenset(
        {"text/html", "application/xhtml+xml", "application/octet-stream"}
    ),
    "docx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/zip",
            "application/octet-stream",
        }
    ),
}
SUPPORTED_CONTENT_TYPES = frozenset().union(*FORMAT_CONTENT_TYPES.values())


@dataclass(frozen=True)
class DownloadedDocument:
    content: bytes
    checksum: str
    final_url: str
    content_type: str
    document_format: DocumentFormat = "pdf"

    @property
    def extension(self) -> str:
        return DOCUMENT_EXTENSIONS[self.document_format]


# Kept as a source-compatible name for existing worker tests and callers.
DownloadedPdf = DownloadedDocument


def allowed_hosts() -> frozenset[str]:
    configured = os.getenv("DOWNLOAD_ALLOWED_HOSTS", "")
    hosts = configured.split(",") if configured else DEFAULT_ALLOWED_HOSTS
    return frozenset(host.strip().lower().rstrip(".") for host in hosts if host.strip())


def validate_download_url(url: str, hosts: frozenset[str] | None = None) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as exc:
        raise PermanentDocumentError(
            "Document URL contains an invalid port",
            code="invalid_document_url",
        ) from exc
    if (
        parsed.scheme.lower() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or host not in (hosts or allowed_hosts())
    ):
        raise PermanentDocumentError(
            "Document URL is not an allowlisted HTTPS URL",
            code="invalid_document_url",
        )
    return url


def _reject_private_resolution(url: str) -> None:
    """Defence in depth for configurable host allowlists."""
    host = urlsplit(url).hostname
    if not host:
        raise PermanentDocumentError("Document URL has no host", code="invalid_document_url")
    try:
        addresses = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise httpx.ConnectError(f"Could not resolve {host}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise PermanentDocumentError(
                "Document host resolved to a non-public address",
                code="unsafe_document_host",
            )


def _content_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _looks_like_html(content: bytes) -> bool:
    try:
        prefix = content[:8192].decode("utf-8-sig").lstrip().lower()
    except UnicodeDecodeError:
        return False
    return (
        prefix.startswith("<!doctype html")
        or prefix.startswith("<html")
        or "<html" in prefix[:4096]
    )


def _validate_utf8_text(content: bytes) -> None:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PermanentDocumentError(
            "Plain text document is not UTF-8",
            code="invalid_text_encoding",
        ) from exc
    if "\x00" in text:
        raise PermanentDocumentError(
            "Plain text document contains binary data",
            code="invalid_text",
        )
    sample = text[:8192]
    disallowed = sum(
        1
        for character in sample
        if ord(character) < 32 and character not in "\n\r\t\f"
    )
    if sample and disallowed / len(sample) > 0.01:
        raise PermanentDocumentError(
            "Plain text document contains binary control characters",
            code="invalid_text",
        )


def _validate_docx_archive(content: bytes, *, max_uncompressed_bytes: int) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 2_000:
                raise PermanentDocumentError(
                    "DOCX archive contains too many entries",
                    code="unsafe_docx",
                )
            if any(member.flag_bits & 0x1 for member in members):
                raise PermanentDocumentError(
                    "Encrypted DOCX files are not supported",
                    code="encrypted_docx",
                )
            if sum(member.file_size for member in members) > max_uncompressed_bytes:
                raise PermanentDocumentError(
                    "Expanded DOCX is larger than the configured limit",
                    code="document_too_large",
                )
            names = {member.filename for member in members}
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                raise PermanentDocumentError(
                    "ZIP file is not a DOCX document",
                    code="invalid_docx",
                )
    except PermanentDocumentError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise PermanentDocumentError(
            "DOCX archive could not be parsed",
            code="invalid_docx",
        ) from exc


def validate_document_content(
    content: bytes,
    *,
    declared_content_type: str,
    final_url: str,
    expected_format: DocumentFormat | None = None,
    max_docx_uncompressed_bytes: int | None = None,
) -> DocumentFormat:
    """Identify a supported document from bytes, then verify MIME and structure."""
    if not content:
        raise PermanentDocumentError("Document is empty", code="empty_document")

    content_type = declared_content_type.split(";", 1)[0].strip().lower()
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise PermanentDocumentError(
            "Document response has an unsupported content type",
            code="invalid_content_type",
        )

    detected: DocumentFormat | None = None
    if content.startswith(PDF_MAGIC):
        detected = "pdf"
    elif content.startswith(ZIP_MAGICS):
        _validate_docx_archive(
            content,
            max_uncompressed_bytes=max_docx_uncompressed_bytes
            or int(os.getenv("MAX_DOCX_UNCOMPRESSED_BYTES", "52428800")),
        )
        detected = "docx"
    elif _looks_like_html(content):
        detected = "html"
    elif content_type == "text/plain":
        _validate_utf8_text(content)
        detected = "txt"

    if detected is None:
        raise PermanentDocumentError(
            "Document bytes do not match a supported format",
            code="invalid_document_signature",
        )
    if content_type not in FORMAT_CONTENT_TYPES[detected]:
        raise PermanentDocumentError(
            "Document content type does not match its bytes",
            code="content_type_mismatch",
        )
    if expected_format is not None and detected != expected_format:
        raise PermanentDocumentError(
            "Stored document format does not match its immutable key",
            code="document_format_mismatch",
        )
    return detected


def download_document(
    url: str,
    *,
    max_bytes: int,
    client: httpx.Client | None = None,
    resolve_hosts: bool = True,
) -> DownloadedDocument:
    """Download one bounded, allowlisted document and validate its real format."""
    if max_bytes <= len(PDF_MAGIC):
        raise ValueError("max_bytes must be larger than a document header")

    current_url = validate_download_url(url)
    owned_client = client is None
    http_client = client or httpx.Client(
        follow_redirects=False,
        timeout=httpx.Timeout(60.0, connect=15.0),
        headers={"User-Agent": "Stocks-In-Hand-document-worker/1.0"},
    )

    try:
        for _ in range(6):
            if resolve_hosts:
                _reject_private_resolution(current_url)
            with http_client.stream(
                "GET",
                current_url,
                headers={"Referer": "https://investors.csl.com/"},
            ) as response:
                if response.status_code in REDIRECT_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise PermanentDocumentError(
                            "Redirect response has no Location header",
                            code="invalid_redirect",
                        )
                    current_url = validate_download_url(urljoin(current_url, location))
                    continue

                if response.status_code == 404:
                    raise PermanentDocumentError(
                        "Document no longer exists",
                        code="document_not_found",
                    )
                if (
                    400 <= response.status_code < 500
                    and response.status_code not in {408, 409, 425, 429}
                ):
                    raise PermanentDocumentError(
                        "Document request was permanently rejected",
                        code="document_rejected",
                    )
                response.raise_for_status()

                content_type = _content_type(response)
                if content_type not in SUPPORTED_CONTENT_TYPES:
                    raise PermanentDocumentError(
                        "Document response has an unsupported content type",
                        code="invalid_content_type",
                    )

                length = response.headers.get("content-length")
                if length:
                    try:
                        declared_length = int(length)
                    except ValueError:
                        declared_length = 0
                    if declared_length > max_bytes:
                        raise PermanentDocumentError(
                            "Document is larger than the configured limit",
                            code="document_too_large",
                        )

                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise PermanentDocumentError(
                            "Document is larger than the configured limit",
                            code="document_too_large",
                        )
                    chunks.append(chunk)

                content = b"".join(chunks)
                document_format = validate_document_content(
                    content,
                    declared_content_type=content_type,
                    final_url=current_url,
                )
                return DownloadedDocument(
                    content=content,
                    checksum=hashlib.sha256(content).hexdigest(),
                    final_url=current_url,
                    content_type=DOCUMENT_CONTENT_TYPES[document_format],
                    document_format=document_format,
                )
        raise PermanentDocumentError("Too many redirects", code="too_many_redirects")
    finally:
        if owned_client:
            http_client.close()


def download_pdf(
    url: str,
    *,
    max_bytes: int,
    client: httpx.Client | None = None,
    resolve_hosts: bool = True,
) -> DownloadedDocument:
    """Compatibility wrapper retained for callers that require PDF specifically."""
    downloaded = download_document(
        url,
        max_bytes=max_bytes,
        client=client,
        resolve_hosts=resolve_hosts,
    )
    if downloaded.document_format != "pdf":
        raise PermanentDocumentError(
            "Document does not contain a PDF header",
            code="invalid_pdf",
        )
    return downloaded
