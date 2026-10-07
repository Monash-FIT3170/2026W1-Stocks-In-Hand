"""The raw document store, in memory and against LocalStack S3."""

import os
import uuid

import httpx
import pytest

from app.sources import SOURCES
from lambdas.common import PermanentDocumentError
from lambdas.download_validation import validated_document
from lambdas.raw_documents import (
    KEY_PREFIX,
    InMemoryBucket,
    RawDocumentStore,
    S3Bucket,
    StoredObject,
    locate,
)
from tools.template_model import template_model

PDF = b"%PDF-1.7\nhalf year results"


def _document(content: bytes = PDF, content_type: str = "application/pdf"):
    return validated_document(
        content,
        declared_content_type=content_type,
        final_url="https://investors.csl.com/report.pdf",
        max_bytes=1024,
    )


@pytest.fixture()
def store() -> RawDocumentStore:
    return RawDocumentStore(InMemoryBucket("raw-documents"))


def test_stored_document_reads_back_and_its_key_names_it(store: RawDocumentStore) -> None:
    artifact_id = uuid.uuid4()

    stored = store.put(ticker="CSL", artifact_id=artifact_id, document=_document())

    location = locate(store.name, stored.location.key)
    assert location == stored.location
    assert location.ticker == "CSL"
    assert location.artifact_id == artifact_id
    assert location.document_format == "pdf"
    assert stored.size == len(PDF)
    assert store.read(location) == PDF
    assert store.holds(store.name, location.key)


def test_the_notification_filter_matches_every_stored_key(store: RawDocumentStore) -> None:
    [notification] = template_model().bucket_queue_notifications("RawDocumentBucket")

    stored = store.put(ticker="CSL", artifact_id=uuid.uuid4(), document=_document())

    assert notification["Filter"] == {
        "S3Key": {"Rules": [{"Name": "prefix", "Value": KEY_PREFIX}]}
    }
    assert stored.location.key.startswith(KEY_PREFIX)


def test_a_repeat_put_keeps_the_first_copy(store: RawDocumentStore) -> None:
    artifact_id = uuid.uuid4()
    first = store.put(ticker="CSL", artifact_id=artifact_id, document=_document())

    again = store.put(ticker="CSL", artifact_id=artifact_id, document=_document())

    assert again == first
    assert list(store.bucket.objects) == [first.location.key]


@pytest.mark.parametrize("ticker", sorted(SOURCES))
def test_every_catalogue_ticker_has_a_key(store: RawDocumentStore, ticker: str) -> None:
    stored = store.put(ticker=ticker, artifact_id=uuid.uuid4(), document=_document())

    assert locate(store.name, stored.location.key).ticker == ticker


def test_each_format_round_trips(store: RawDocumentStore) -> None:
    text = _document(b"Revenue increased.\n", "text/plain")

    stored = store.put(ticker="BHP", artifact_id=uuid.uuid4(), document=text)

    assert stored.location.document_format == "txt"
    assert store.read(stored.location) == b"Revenue increased.\n"


@pytest.mark.parametrize(
    "key",
    [
        "raw/XYZ/123e4567-e89b-42d3-a456-426614174000/" + "a" * 64 + ".pdf",
        "raw/CSL/not-a-uuid/" + "a" * 64 + ".pdf",
        "raw/CSL/123e4567-e89b-42d3-a456-426614174000/" + "a" * 64 + ".exe",
        "documents/CSL/123e4567-e89b-42d3-a456-426614174000/" + "a" * 64 + ".pdf",
    ],
    ids=["unknown ticker", "bad artifact id", "unsupported format", "outside raw/"],
)
def test_a_key_outside_the_layout_is_rejected(key: str) -> None:
    with pytest.raises(PermanentDocumentError) as error:
        locate("raw-documents", key)

    assert error.value.code == "invalid_object_key"


def test_holds_only_objects_in_its_own_bucket(store: RawDocumentStore) -> None:
    stored = store.put(ticker="CSL", artifact_id=uuid.uuid4(), document=_document())

    assert not store.holds("another-bucket", stored.location.key)
    assert not store.holds(store.name, None)
    assert not store.holds(store.name, stored.location.key.replace("raw/CSL", "raw/BHP"))


def _tamper(store: RawDocumentStore, key: str, *, content: bytes | None = None, **fields):
    stored, body = store.bucket.objects[key]
    store.bucket.objects[key] = (
        StoredObject(
            content_type=fields.get("content_type", stored.content_type),
            size=fields.get("size", stored.size),
            metadata=stored.metadata,
        ),
        body if content is None else content,
    )


@pytest.mark.parametrize(
    ("tampering", "code"),
    [
        ({"content": b"%PDF-1.7\nsomething else"}, "checksum_mismatch"),
        ({"content_type": "text/html"}, "content_type_mismatch"),
        ({"size": 50 * 1024 * 1024}, "document_too_large"),
    ],
)
def test_read_rejects_an_object_that_is_not_what_its_key_names(
    store: RawDocumentStore,
    tampering: dict,
    code: str,
) -> None:
    stored = store.put(ticker="CSL", artifact_id=uuid.uuid4(), document=_document())
    _tamper(store, stored.location.key, **tampering)

    with pytest.raises(PermanentDocumentError) as error:
        store.read(stored.location)

    assert error.value.code == code


def test_verify_describes_the_object_without_reading_it(store: RawDocumentStore) -> None:
    stored = store.put(ticker="CSL", artifact_id=uuid.uuid4(), document=_document())

    assert store.verify(stored.location) == stored


def test_verify_rejects_an_object_whose_metadata_names_another_document(
    store: RawDocumentStore,
) -> None:
    other = store.put(ticker="CSL", artifact_id=uuid.uuid4(), document=_document())
    claimed = locate(
        store.name,
        other.location.key.replace(str(other.location.artifact_id), str(uuid.uuid4())),
    )
    store.bucket.objects[claimed.key] = store.bucket.objects[other.location.key]

    with pytest.raises(PermanentDocumentError) as error:
        store.verify(claimed)

    assert error.value.code == "artifact_identity_mismatch"


def test_verify_rejects_an_oversized_object(store: RawDocumentStore) -> None:
    stored = store.put(ticker="CSL", artifact_id=uuid.uuid4(), document=_document())
    _tamper(store, stored.location.key, size=50 * 1024 * 1024)

    with pytest.raises(PermanentDocumentError) as error:
        store.verify(stored.location)

    assert error.value.code == "document_too_large"


def test_verify_retries_an_object_that_is_not_visible_yet(store: RawDocumentStore) -> None:
    missing = locate(
        store.name,
        f"{KEY_PREFIX}CSL/{uuid.uuid4()}/{'a' * 64}.pdf",
    )

    with pytest.raises(RuntimeError, match="not visible"):
        store.verify(missing)


def _localstack_s3():
    endpoint = os.getenv("LOCALSTACK_ENDPOINT_URL", "http://localhost:4566")
    try:
        httpx.get(f"{endpoint}/_localstack/health", timeout=1.0).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"LocalStack is not available at {endpoint}")
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="ap-southeast-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def test_store_on_localstack_s3() -> None:
    client = _localstack_s3()
    bucket = f"raw-documents-{uuid.uuid4().hex[:12]}"
    client.create_bucket(
        Bucket=bucket,
        CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
    )
    store = RawDocumentStore(S3Bucket(client, bucket))
    artifact_id = uuid.uuid4()

    stored = store.put(ticker="CSL", artifact_id=artifact_id, document=_document())
    store.put(ticker="CSL", artifact_id=artifact_id, document=_document())

    described = store.bucket.head(stored.location.key)
    assert described == StoredObject(
        content_type="application/pdf",
        size=len(PDF),
        metadata={
            "artifact-id": str(artifact_id),
            "sha256": stored.location.checksum,
            "ticker": "CSL",
            "document-format": "pdf",
        },
    )
    assert store.verify(stored.location) == stored
    assert store.read(stored.location) == PDF
    assert store.holds(bucket, stored.location.key)
    assert store.bucket.head(f"{KEY_PREFIX}missing") is None
