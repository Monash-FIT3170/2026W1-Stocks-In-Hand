"""Focused tests for Queue A contracts and the API producer."""

from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from app.api.deps import require_admin_investor
from app.messages import QueueAMessage, QueueBMessage
from app.schemas.investor import InvestorUpdate
from app.services import scrape_queue
from app.status import ScrapeRunStatus


def test_queue_a_normalises_ticker_and_serialises_identifiers() -> None:
    run_id = uuid4()
    message = QueueAMessage(
        scrape_run_id=run_id,
        ticker="csl",
        source_url="https://investors.csl.com/investors/asx-announcements",
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
            document_url="https://example.com/announcement.pdf",
            canonical_url="https://example.com/announcement.pdf",
            metadata={"headers": {"authorization": "do-not-send"}},
        )


def test_queue_messages_forbid_uncontracted_document_content() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        QueueAMessage(
            scrape_run_id=uuid4(),
            ticker="CSL",
            source_url="https://investors.csl.com/investors/asx-announcements",
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
    )

    assert scrape_queue.enqueue_discovery(message) == "message-123"
    call = client.send_message.call_args.kwargs
    assert call["QueueUrl"] == "queue-url"
    assert '"ticker":"CSL"' in call["MessageBody"]


def _run(status: str = ScrapeRunStatus.ENQUEUEING) -> MagicMock:
    run = MagicMock()
    run.id = uuid4()
    run.status = status
    run.queued_at = datetime.now(timezone.utc)
    return run


def test_scrape_endpoint_creates_run_and_enqueues(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run()
    get_or_create = MagicMock(return_value=(run, True))
    enqueue = MagicMock(return_value="message-id")
    monkeypatch.setattr(main.scrape_run_crud, "get_or_create_queued_run", get_or_create)
    mark_queued = MagicMock(return_value=run)
    monkeypatch.setattr(
        main.scrape_run_crud,
        "mark_run_queued_if_enqueueing",
        mark_queued,
    )
    monkeypatch.setattr(main.scrape_queue, "enqueue_discovery", enqueue)
    monkeypatch.setattr(main.settings, "SUPPORTED_TICKERS", ["CSL"])

    result = main.scrape_ticker(
        ticker_symbol="csl",
        idempotency_key="browser-request-1",
        db=MagicMock(),
    )

    assert result == {
        "status": ScrapeRunStatus.QUEUED,
        "ticker": "CSL",
        "scrape_run_id": run.id,
    }
    assert enqueue.call_args.args[0].scrape_run_id == run.id
    assert (
        get_or_create.call_args.kwargs["idempotency_key"]
        == "scrape:CSL:browser-request-1"
    )
    mark_queued.assert_called_once_with(get_or_create.call_args.args[0], run.id)


def test_duplicate_active_request_returns_same_run_without_second_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(ScrapeRunStatus.DISCOVERING)
    monkeypatch.setattr(
        main.scrape_run_crud,
        "get_or_create_queued_run",
        MagicMock(return_value=(run, False)),
    )
    enqueue = MagicMock()
    monkeypatch.setattr(main.scrape_queue, "enqueue_discovery", enqueue)
    monkeypatch.setattr(main.settings, "SUPPORTED_TICKERS", ["CSL"])

    result = main.scrape_ticker(
        ticker_symbol="CSL",
        idempotency_key="same-request",
        db=MagicMock(),
    )

    assert result["scrape_run_id"] == run.id
    assert result["status"] == ScrapeRunStatus.DISCOVERING
    enqueue.assert_not_called()


def test_duplicate_enqueueing_request_resends_queue_a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(ScrapeRunStatus.ENQUEUEING)
    monkeypatch.setattr(
        main.scrape_run_crud,
        "get_or_create_queued_run",
        MagicMock(return_value=(run, False)),
    )
    mark_queued = MagicMock(return_value=run)
    monkeypatch.setattr(
        main.scrape_run_crud,
        "mark_run_queued_if_enqueueing",
        mark_queued,
    )
    enqueue = MagicMock(return_value="message-id")
    monkeypatch.setattr(main.scrape_queue, "enqueue_discovery", enqueue)
    monkeypatch.setattr(main.settings, "SUPPORTED_TICKERS", ["CSL"])

    result = main.scrape_ticker(
        ticker_symbol="CSL",
        idempotency_key="retry-enqueueing",
        db=MagicMock(),
    )

    assert result["status"] == ScrapeRunStatus.QUEUED
    enqueue.assert_called_once()
    mark_queued.assert_called_once()


def test_queue_send_failure_marks_run_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    monkeypatch.setattr(
        main.scrape_run_crud,
        "get_or_create_queued_run",
        MagicMock(return_value=(run, True)),
    )
    mark_failed = MagicMock()
    monkeypatch.setattr(main.scrape_run_crud, "mark_run_discovery_failed", mark_failed)
    monkeypatch.setattr(
        main.scrape_queue,
        "enqueue_discovery",
        MagicMock(side_effect=RuntimeError("SQS unavailable")),
    )
    monkeypatch.setattr(main.settings, "SUPPORTED_TICKERS", ["CSL"])

    with pytest.raises(HTTPException) as exc_info:
        main.scrape_ticker(
            ticker_symbol="CSL",
            idempotency_key="failed-request",
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 503
    mark_failed.assert_called_once()


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


def test_scrape_route_requires_admin_dependency() -> None:
    route = next(
        route
        for route in main.app.routes
        if getattr(route, "path", None) == "/scrape/{ticker_symbol}"
    )

    assert require_admin_investor in {
        dependency.call for dependency in route.dependant.dependencies
    }


def test_direct_scrape_run_mutation_requires_admin_dependency() -> None:
    route = next(
        route
        for route in main.scrape_run.router.routes
        if getattr(route, "path", None) == "/scrape-runs/"
        and "POST" in getattr(route, "methods", set())
    )

    assert require_admin_investor in {
        dependency.call for dependency in route.dependant.dependencies
    }


def test_api_has_no_startup_scrape_or_reddit_jobs() -> None:
    assert main.app.router.on_startup == []


def test_investor_mutations_require_admin_dependency() -> None:
    mutation_routes = [
        route
        for route in main.investor.router.routes
        if getattr(route, "path", "").startswith("/investors")
        and set(getattr(route, "methods", set())) & {"POST", "PATCH", "DELETE"}
    ]

    assert mutation_routes
    for route in mutation_routes:
        assert require_admin_investor in {
            dependency.call for dependency in route.dependant.dependencies
        }


def test_investor_update_rejects_role_escalation_fields() -> None:
    with pytest.raises(ValidationError):
        InvestorUpdate(hashed_password="attacker-controlled")
