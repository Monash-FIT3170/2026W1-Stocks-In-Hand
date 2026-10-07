"""Focused tests for Queue A contracts and the API producer."""

import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from app.api.deps import require_admin_investor
from app.messages import (
    PublicDiscussionAnalysisMessage,
    QueueAMessage,
    QueueBMessage,
)
from app.schemas.investor import InvestorUpdate
from app.services import analysis_queue, scrape_queue


def test_queue_a_normalises_ticker_and_serialises_identifiers() -> None:
    run_id = uuid4()
    message = QueueAMessage(
        scrape_run_id=run_id,
        ticker="csl",
        source_url="https://investors.csl.com/investors/asx-announcements",
        source_adapter="csl",
    )

    assert message.ticker == "CSL"
    assert message.schema_version == 1
    assert str(run_id) in message.model_dump_json()


def test_queue_b_requires_urls_and_rejects_sensitive_metadata() -> None:
    with pytest.raises(ValidationError, match="cookie"):
        QueueBMessage(
            scrape_run_id=uuid4(),
            artifact_id=uuid4(),
            ticker="CSL",
            source_url="https://investors.csl.com/investors/asx-announcements",
            source_adapter="csl",
            document_url="https://example.com/announcement.pdf",
            canonical_url="https://example.com/announcement.pdf",
            metadata={"cookie": "do-not-send"},
        )

    with pytest.raises(ValidationError, match="authorization"):
        QueueBMessage(
            scrape_run_id=uuid4(),
            artifact_id=uuid4(),
            ticker="CSL",
            source_url="https://investors.csl.com/investors/asx-announcements",
            source_adapter="csl",
            document_url="https://example.com/announcement.pdf",
            canonical_url="https://example.com/announcement.pdf",
            metadata={"headers": {"authorization": "do-not-send"}},
        )


def test_queue_messages_name_their_source_adapter() -> None:
    with pytest.raises(ValidationError, match="source_adapter"):
        QueueAMessage(
            scrape_run_id=uuid4(),
            ticker="CSL",
            source_url="https://investors.csl.com/investors/asx-announcements",
        )


def test_queue_messages_forbid_uncontracted_document_content() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        QueueAMessage(
            scrape_run_id=uuid4(),
            ticker="CSL",
            source_url="https://investors.csl.com/investors/asx-announcements",
            source_adapter="csl",
            raw_text="document content",
        )


def test_enqueue_discovery_sends_validated_json(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.send_message.return_value = {"MessageId": "message-123"}
    monkeypatch.setattr(scrape_queue.settings, "DISCOVERY_QUEUE_URL", "queue-url")
    monkeypatch.setattr(scrape_queue, "_sqs_client", lambda: client)
    message = QueueAMessage(
        scrape_run_id=uuid4(),
        ticker="CSL",
        source_url="https://investors.csl.com/investors/asx-announcements",
        source_adapter="csl",
    )

    assert scrape_queue.enqueue_discovery(message) == "message-123"
    call = client.send_message.call_args.kwargs
    assert call["QueueUrl"] == "queue-url"
    assert '"ticker":"CSL"' in call["MessageBody"]


def test_public_discussion_analysis_message_contains_only_artifact_identity() -> None:
    artifact_id = uuid4()
    message = PublicDiscussionAnalysisMessage(artifact_id=artifact_id)

    assert message.message_type == "public_discussion_analysis"
    assert message.artifact_id == artifact_id
    assert "raw_text" not in message.model_dump_json()


def test_enqueue_stored_artifact_analysis_sends_validated_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.send_message.return_value = {"MessageId": "analysis-message-1"}
    monkeypatch.setattr(analysis_queue.settings, "ANALYSIS_QUEUE_URL", "analysis-url")
    monkeypatch.setattr(analysis_queue, "_sqs_client", lambda: client)
    artifact_id = uuid4()

    assert (
        analysis_queue.enqueue_stored_artifact_analysis(artifact_id)
        == "analysis-message-1"
    )
    call = client.send_message.call_args.kwargs
    assert call["QueueUrl"] == "analysis-url"
    parsed = PublicDiscussionAnalysisMessage.model_validate_json(call["MessageBody"])
    assert parsed.artifact_id == artifact_id


def test_scrape_endpoint_rejects_disabled_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main.settings, "SUPPORTED_TICKERS", ["CSL"])

    with pytest.raises(HTTPException) as exc_info:
        main.scrape_ticker(
            ticker_symbol="BHP",
            idempotency_key="request",
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 404


def test_admin_dependency_rejects_regular_user() -> None:
    investor = MagicMock()
    investor.role = "user"

    with pytest.raises(HTTPException) as exc_info:
        require_admin_investor(investor)

    assert exc_info.value.status_code == 403


def test_admin_dependency_accepts_admin() -> None:
    investor = MagicMock()
    investor.role = "admin"

    assert require_admin_investor(investor) is investor


def test_api_has_no_startup_scrape_or_reddit_jobs() -> None:
    assert main.app.router.on_startup == []


def test_investor_update_rejects_role_escalation_fields() -> None:
    with pytest.raises(ValidationError):
        InvestorUpdate(hashed_password="attacker-controlled")
