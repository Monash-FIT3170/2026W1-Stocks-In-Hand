"""Unit tests for the versioned SQS message contracts in app/messages.py.

Queue A (Discovery) and Queue B (Download) messages are the actual
payloads that cross the wire on DiscoveryQueue and DownloadQueue. The
wiring tests in test_queue_wiring.py confirm the queues/consumers/
producers in infra/template.yaml are connected correctly; these tests
confirm the *messages themselves* stay valid -- correct schema_version,
no accidental leakage of secrets/raw document bytes into metadata, no
silent schema drift via unexpected extra fields, and consistent
ticker/adapter pairing. Pure unit tests: no AWS, no network, no queue.
"""

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from pydantic import ValidationError

from app.messages import QueueAMessage, QueueBMessage

BHP_SOURCE_URL = "https://www.bhp.com/investor-hub/market-announcements"
CSL_SOURCE_URL = "https://investors.csl.com/investors/asx-announcements"
CSL_DOCUMENT_URL = "https://investors.csl.com/documents/example.pdf"


def _queue_a(**overrides: object) -> QueueAMessage:
    fields: dict[str, object] = {
        "scrape_run_id": uuid4(),
        "ticker": "BHP",
        "source_url": BHP_SOURCE_URL,
        "source_adapter": "bhp",
    }
    fields.update(overrides)
    return QueueAMessage(**fields)


def _queue_b(**overrides: object) -> QueueBMessage:
    fields: dict[str, object] = {
        "scrape_run_id": uuid4(),
        "artifact_id": uuid4(),
        "ticker": "CSL",
        "source_url": CSL_SOURCE_URL,
        "document_url": CSL_DOCUMENT_URL,
        "canonical_url": CSL_DOCUMENT_URL,
        "source_adapter": "csl",
    }
    fields.update(overrides)
    return QueueBMessage(**fields)


# ---------------------------------------------------------------------------
# Queue A (Discovery) messages
# ---------------------------------------------------------------------------

def test_queue_a_message_normalizes_ticker_case_and_whitespace() -> None:
    message = _queue_a(ticker="  bhp ")
    assert message.ticker == "BHP"


def test_queue_a_message_defaults_schema_version_to_one() -> None:
    message = _queue_a()
    assert message.schema_version == 1


def test_queue_a_message_requested_at_defaults_to_timezone_aware_now() -> None:
    message = _queue_a()
    assert message.requested_at.tzinfo is not None


def test_queue_a_message_rejects_adapter_that_does_not_match_ticker() -> None:
    # BHP's registered adapter is "bhp" (see app/sources.py); pairing it
    # with a different adapter must fail validation rather than silently
    # scraping the wrong source.
    with pytest.raises(ValidationError):
        _queue_a(ticker="BHP", source_adapter="wes")


def test_queue_a_message_rejects_forbidden_metadata_key_at_top_level() -> None:
    with pytest.raises(ValidationError):
        _queue_a(metadata={"auth_token": "irrelevant", "token": "leaked"})


def test_queue_a_message_rejects_forbidden_metadata_key_nested_in_dict() -> None:
    with pytest.raises(ValidationError):
        _queue_a(metadata={"request": {"headers": {"cookie": "leaked"}}})


def test_queue_a_message_rejects_forbidden_metadata_key_nested_in_list() -> None:
    with pytest.raises(ValidationError):
        _queue_a(metadata={"attempts": [{"note": "ok"}, {"password": "leaked"}]})


def test_queue_a_message_allows_ordinary_metadata() -> None:
    message = _queue_a(metadata={"retry_count": 1, "note": "first pass"})
    assert message.metadata == {"retry_count": 1, "note": "first pass"}


def test_queue_a_message_rejects_unknown_fields() -> None:
    # extra="forbid" is what catches producer/consumer schema drift at
    # commit time instead of as a silent runtime surprise in Lambda.
    with pytest.raises(ValidationError):
        _queue_a(some_field_nobody_agreed_on="oops")


# ---------------------------------------------------------------------------
# Queue B (Download) messages
# ---------------------------------------------------------------------------

def test_queue_b_message_optional_fields_default_to_none() -> None:
    message = _queue_b()
    assert message.source_id is None
    assert message.title is None
    assert message.published_at is None


def test_queue_b_message_rejects_adapter_that_does_not_match_ticker() -> None:
    with pytest.raises(ValidationError):
        _queue_b(ticker="CSL", source_adapter="anz")


def test_queue_b_message_rejects_forbidden_metadata_key() -> None:
    with pytest.raises(ValidationError):
        _queue_b(metadata={"raw_text": "the whole document, leaked"})


def test_queue_b_message_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _queue_b(unexpected="oops")


def test_queue_b_message_round_trips_through_json_unchanged() -> None:
    # This is the exact serialize/deserialize path DownloadFunction uses
    # when it reads a Queue B message off the SQS event.
    original = _queue_b(title="Quarterly report", metadata={"retry_count": 0})

    restored = QueueBMessage.model_validate_json(original.model_dump_json())

    assert restored.scrape_run_id == original.scrape_run_id
    assert restored.artifact_id == original.artifact_id
    assert restored.ticker == original.ticker
    assert restored.source_adapter == original.source_adapter
    assert restored.title == original.title
    assert restored.metadata == original.metadata
