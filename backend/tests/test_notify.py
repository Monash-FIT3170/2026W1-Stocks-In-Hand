"""Contracts for the Brevo watchlist notification worker.

How the worker delivers alerts is tested through its handler on Postgres in
``test_alert_delivery.py``. These tests cover the message parser, the image
and the cold-start order.
"""

# pylint: disable=protected-access

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from lambdas import notify


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _enable_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the enabled worker unless a test explicitly selects dark mode."""
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True, raising=False)
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")


def _message_body(**overrides: object) -> dict[str, object]:
    """Return one valid, versioned notification message body."""
    body: dict[str, object] = {
        "schema_version": 1,
        "artifact_id": str(uuid4()),
        "ticker": "BHP",
        "scrape_run_id": str(uuid4()),
        "sentiment_label": "negative",
        "confidence_score": 0.82,
    }
    body.update(overrides)
    return body


def _sqs_record(message_id: str = "notification-1", **overrides: object) -> dict:
    """Wrap a notification body in the SQS event-record shape."""
    return {
        "messageId": message_id,
        "body": json.dumps(_message_body(**overrides)),
        "attributes": {"ApproximateReceiveCount": "1"},
    }


def test_notification_message_parser_accepts_the_versioned_contract() -> None:
    """A valid producer payload should reach the worker as typed values."""
    artifact_id = uuid4()
    scrape_run_id = uuid4()

    message = notify.parse_notification_record(
        _sqs_record(
            artifact_id=str(artifact_id),
            scrape_run_id=str(scrape_run_id),
            ticker=" bhp ",
            confidence_score="0.7500",
        )
    )

    assert message.schema_version == 1
    assert message.artifact_id == artifact_id
    assert message.scrape_run_id == scrape_run_id
    assert message.ticker == "BHP"
    assert message.sentiment_label == "negative"
    assert Decimal(str(message.confidence_score)) == Decimal("0.7500")


@pytest.mark.parametrize(
    "body",
    [
        "not-json",
        json.dumps({}),
        json.dumps(_message_body(schema_version=2)),
        json.dumps(_message_body(confidence_score=-0.01)),
        json.dumps(_message_body(confidence_score=1.01)),
        json.dumps(_message_body(sentiment_label="unknown")),
        json.dumps(_message_body(extra_field="must be rejected")),
    ],
)
def test_notification_message_parser_rejects_poison_payloads(body: str) -> None:
    """Malformed queue messages are permanent failures, not retry candidates."""
    record = _sqs_record()
    record["body"] = body

    with pytest.raises(ValueError) as raised:
        notify.parse_notification_record(record)

    assert getattr(raised.value, "code", None) == "invalid_notification_message"


def test_handler_acknowledges_poison_messages() -> None:
    """A malformed message should leave SQS instead of cycling into the DLQ."""
    record = _sqs_record("poison-message")
    record["body"] = "not-json"

    assert notify.handler({"Records": [record]}, None) == {
        "batchItemFailures": []
    }


def test_api_image_packages_the_notification_worker() -> None:
    """The shared API image must contain the Lambda module named in SAM."""
    dockerfile = (
        REPOSITORY_ROOT / "backend" / "Dockerfile.api"
    ).read_text(encoding="utf-8")

    lambda_copy = next(
        line for line in dockerfile.splitlines() if line.startswith("COPY lambdas/")
    )
    assert "lambdas/notify.py" in lambda_copy
    assert "requirements-analysis.txt" not in dockerfile


def test_runtime_configuration_load_precedes_configured_imports() -> None:
    """Cold starts must resolve SSM before settings and DB code are imported."""
    source = (
        REPOSITORY_ROOT / "backend" / "lambdas" / "notify.py"
    ).read_text(encoding="utf-8")

    load_position = source.index("\nload_runtime_configuration()\n")
    settings_position = source.index("\nfrom app.core.config import settings")
    sender_position = source.index("\nfrom app.services import email_sender")

    assert load_position < settings_position < sender_position
