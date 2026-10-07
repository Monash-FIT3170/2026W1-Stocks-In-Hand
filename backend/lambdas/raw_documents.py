"""The raw document store: the immutable copy of every downloaded document.

The download worker puts each validated document here once, and the
analysis worker reads it back. The store owns, for both of them, the object
key layout, the object metadata, "put only if absent" and "read and verify",
so the two workers cannot disagree about any of them.

Keys look like ``raw/{ticker}/{artifact_id}/{sha256}.{ext}``. The bucket's
S3-to-SQS notification filter matches the ``raw/`` prefix, so the layout
must not change.

The store sits on an ``ObjectBucket``: ``S3Bucket`` in AWS and LocalStack,
``InMemoryBucket`` in tests.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

import boto3
from botocore.exceptions import ClientError

from app.sources import SOURCES
from lambdas.common import PermanentDocumentError
from lambdas.download_validation import (
    DOCUMENT_CONTENT_TYPES,
    DOCUMENT_EXTENSIONS,
    DocumentFormat,
    DownloadedDocument,
    document_size_limit,
    ensure_within_size_limit,
    validate_document_content,
)

KEY_PREFIX = "raw/"
_FORMAT_BY_EXTENSION: dict[str, DocumentFormat] = {
    extension: document_format
    for document_format, extension in DOCUMENT_EXTENSIONS.items()
}
_KEY = re.compile(
    rf"^{KEY_PREFIX}(?P<ticker>{'|'.join(map(re.escape, SOURCES))})/"
    r"(?P<artifact_id>[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})/"
    rf"(?P<checksum>[0-9a-f]{{64}})\.(?P<extension>{'|'.join(_FORMAT_BY_EXTENSION)})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocumentLocation:
    """One stored document's bucket and key, and what the key says about it."""

    bucket: str
    key: str
    ticker: str
    artifact_id: UUID
    checksum: str
    document_format: DocumentFormat

    @property
    def content_type(self) -> str:
        return DOCUMENT_CONTENT_TYPES[self.document_format]


def locate(bucket: str, key: str) -> DocumentLocation:
    """Read a document's identity from its key, or reject the key."""
    match = _KEY.fullmatch(key)
    if not match:
        raise PermanentDocumentError(
            "S3 object key does not match the immutable document layout",
            code="invalid_object_key",
        )
    return DocumentLocation(
        bucket=bucket,
        key=key,
        ticker=match.group("ticker").upper(),
        artifact_id=UUID(match.group("artifact_id")),
        checksum=match.group("checksum").lower(),
        document_format=_FORMAT_BY_EXTENSION[match.group("extension").lower()],
    )


@dataclass(frozen=True)
class StoredDocument:
    """A document the store holds, as the artifact row records it."""

    location: DocumentLocation
    size: int

    def artifact_fields(self) -> dict[str, object]:
        """Keyword arguments for ``crud.scrape_run.mark_artifact_stored``."""
        return {
            "checksum_sha256": self.location.checksum,
            "s3_bucket": self.location.bucket,
            "s3_key": self.location.key,
            "content_type": self.location.content_type,
            "file_size_bytes": self.size,
        }


@dataclass(frozen=True)
class StoredObject:
    """What a bucket reports about one object."""

    content_type: str
    size: int
    metadata: Mapping[str, str] = field(default_factory=dict)


class ObjectBucket(Protocol):
    name: str

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        """Write the object unless the key already exists; never overwrite."""

    def head(self, key: str) -> StoredObject | None:
        """Describe the object, or return None when it does not exist."""

    def get(self, key: str, *, max_bytes: int) -> tuple[StoredObject, bytes]:
        """Return the object and at most ``max_bytes + 1`` bytes of its body."""


class RawDocumentStore:
    def __init__(self, bucket: ObjectBucket) -> None:
        self.bucket = bucket

    @property
    def name(self) -> str:
        return self.bucket.name

    def put(
        self,
        *,
        ticker: str,
        artifact_id: UUID,
        document: DownloadedDocument,
    ) -> StoredDocument:
        """Store a validated document once; a repeat put keeps the first copy."""
        location = DocumentLocation(
            bucket=self.name,
            key=(
                f"{KEY_PREFIX}{ticker}/{artifact_id}/"
                f"{document.checksum}.{document.extension}"
            ),
            ticker=ticker,
            artifact_id=artifact_id,
            checksum=document.checksum,
            document_format=document.document_format,
        )
        self.bucket.put_if_absent(
            location.key,
            document.content,
            content_type=location.content_type,
            metadata={
                "artifact-id": str(artifact_id),
                "sha256": location.checksum,
                "ticker": ticker,
                "document-format": location.document_format,
            },
        )
        return StoredDocument(location=location, size=len(document.content))

    def holds(self, bucket: str | None, key: str | None) -> bool:
        """Whether this store still has the object an artifact row points at."""
        if not key or bucket != self.name:
            return False
        return self.bucket.head(key) is not None

    def read(self, location: DocumentLocation) -> bytes:
        """Read a stored document and check it is the one its key names."""
        max_bytes = document_size_limit()
        stored, content = self.bucket.get(location.key, max_bytes=max_bytes)
        if stored.content_type != location.content_type:
            raise PermanentDocumentError(
                "Stored document content type does not match its immutable key",
                code="content_type_mismatch",
            )
        ensure_within_size_limit(
            max(stored.size, len(content)),
            max_bytes,
            subject="Stored document",
        )
        if hashlib.sha256(content).hexdigest() != location.checksum:
            raise PermanentDocumentError(
                "Stored document checksum does not match its immutable key",
                code="checksum_mismatch",
            )
        validate_document_content(
            content,
            declared_content_type=location.content_type,
            expected_format=location.document_format,
        )
        return content


def _media_type(value: object) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


class S3Bucket:
    def __init__(self, client, name: str) -> None:
        self.client = client
        self.name = name

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        try:
            self.client.put_object(
                Bucket=self.name,
                Key=key,
                Body=body,
                ContentLength=len(body),
                ContentType=content_type,
                ServerSideEncryption="AES256",
                Metadata=dict(metadata),
                IfNoneMatch="*",
            )
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status == 412 or code in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
            }:
                return
            raise

    def head(self, key: str) -> StoredObject | None:
        try:
            response = self.client.head_object(Bucket=self.name, Key=key)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            # Without s3:ListBucket, S3 answers 403 for a missing key.
            if status in {403, 404}:
                return None
            raise
        return self._described(response)

    def get(self, key: str, *, max_bytes: int) -> tuple[StoredObject, bytes]:
        response = self.client.get_object(Bucket=self.name, Key=key)
        body = response["Body"]
        try:
            content = body.read(max_bytes + 1)
        finally:
            body.close()
        return self._described(response), content

    @staticmethod
    def _described(response: Mapping) -> StoredObject:
        return StoredObject(
            content_type=_media_type(response.get("ContentType")),
            size=int(response.get("ContentLength", 0)),
            metadata={
                str(name).lower(): str(value)
                for name, value in (response.get("Metadata") or {}).items()
            },
        )


class InMemoryBucket:
    """An ObjectBucket held in a dict, for tests and local experiments."""

    def __init__(self, name: str = "raw-documents") -> None:
        self.name = name
        self.objects: dict[str, tuple[StoredObject, bytes]] = {}

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        self.objects.setdefault(
            key,
            (
                StoredObject(
                    content_type=_media_type(content_type),
                    size=len(body),
                    metadata={name.lower(): value for name, value in metadata.items()},
                ),
                body,
            ),
        )

    def head(self, key: str) -> StoredObject | None:
        stored = self.objects.get(key)
        return stored[0] if stored else None

    def get(self, key: str, *, max_bytes: int) -> tuple[StoredObject, bytes]:
        if key not in self.objects:
            raise KeyError(key)
        stored, body = self.objects[key]
        return stored, body[: max_bytes + 1]


def raw_document_store() -> RawDocumentStore:
    """The deployed store: the RAW_DOCUMENT_BUCKET bucket through boto3."""
    return RawDocumentStore(
        S3Bucket(boto3.client("s3"), os.environ["RAW_DOCUMENT_BUCKET"])
    )
