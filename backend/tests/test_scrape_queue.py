"""Unit tests for app/services/scrape_queue.py -- the producer wrapper
that puts a validated Queue A message on DiscoveryQueue.

Every test here fakes boto3.client, so nothing ever makes a real AWS
call, needs credentials, or touches a real queue. These tests exist to
catch a producer regression (wrong queue URL, a mangled message body, or
the cached client accidentally getting rebuilt on every call) at
commit/PR time -- the same goal as test_queue_wiring.py, but for the
producer's runtime behaviour instead of the CloudFormation wiring.
"""

import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.core.config import settings
from app.messages import QueueAMessage
from app.services import scrape_queue

DISCOVERY_QUEUE_URL = (
    "https://sqs.ap-southeast-2.amazonaws.com/123456789012/discovery-queue"
)


class _FakeSqsClient:
    """Records every send_message call instead of talking to AWS."""

    def __init__(self, message_id: str = "fake-message-id-123") -> None:
        self.message_id = message_id
        self.calls: list[dict[str, object]] = []

    def send_message(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"MessageId": self.message_id}


@pytest.fixture(autouse=True)
def _reset_cached_sqs_client():
    # _sqs_client() is lru_cache'd at module scope; clear it before and
    # after each test so tests can't leak a fake client into each other
    # (or into a real one, if this ever ran outside of test isolation).
    scrape_queue._sqs_client.cache_clear()
    yield
    scrape_queue._sqs_client.cache_clear()


def _sample_message() -> QueueAMessage:
    return QueueAMessage(
        scrape_run_id=uuid4(),
        ticker="BHP",
        source_url="https://www.bhp.com/investor-hub/market-announcements",
        source_adapter="bhp",
    )


def test_enqueue_discovery_raises_when_queue_url_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DISCOVERY_QUEUE_URL", "")

    with pytest.raises(RuntimeError):
        scrape_queue.enqueue_discovery(_sample_message())


def test_enqueue_discovery_sends_to_the_configured_queue_url(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DISCOVERY_QUEUE_URL", DISCOVERY_QUEUE_URL)
    fake_client = _FakeSqsClient()
    monkeypatch.setattr("boto3.client", lambda *a, **kw: fake_client)

    scrape_queue.enqueue_discovery(_sample_message())

    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["QueueUrl"] == DISCOVERY_QUEUE_URL


def test_enqueue_discovery_sends_the_message_as_its_own_validated_json(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DISCOVERY_QUEUE_URL", DISCOVERY_QUEUE_URL)
    fake_client = _FakeSqsClient()
    monkeypatch.setattr("boto3.client", lambda *a, **kw: fake_client)

    message = _sample_message()
    scrape_queue.enqueue_discovery(message)

    sent_body = json.loads(fake_client.calls[0]["MessageBody"])
    assert sent_body == json.loads(message.model_dump_json())


def test_enqueue_discovery_returns_the_aws_message_id(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DISCOVERY_QUEUE_URL", DISCOVERY_QUEUE_URL)
    fake_client = _FakeSqsClient(message_id="abc-999")
    monkeypatch.setattr("boto3.client", lambda *a, **kw: fake_client)

    result = scrape_queue.enqueue_discovery(_sample_message())

    assert result == "abc-999"


def test_sqs_client_is_built_once_and_reused_across_calls(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DISCOVERY_QUEUE_URL", DISCOVERY_QUEUE_URL)
    build_count = 0

    def _fake_boto3_client(*args: object, **kwargs: object) -> _FakeSqsClient:
        nonlocal build_count
        build_count += 1
        return _FakeSqsClient()

    monkeypatch.setattr("boto3.client", _fake_boto3_client)

    scrape_queue.enqueue_discovery(_sample_message())
    scrape_queue.enqueue_discovery(_sample_message())
    scrape_queue.enqueue_discovery(_sample_message())

    assert build_count == 1
