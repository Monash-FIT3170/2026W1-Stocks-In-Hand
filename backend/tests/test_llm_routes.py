"""The routes that ask an LLM for something, on Postgres.

The admin category route and the investor Reddit digest generate on
request, with a scripted LLM, and answer 503 when no LLM is switched on.
The admin summary routes generated inside the API Lambda's 30 seconds; now
they queue a summary request for the analysis worker and answer 202.
"""

import json
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.api.routes import llm, reddit
from app.core.config import settings
from app.database.connection import get_db
from app.messages import SummaryRequestMessage
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.services import analysis_queue
from app.services.analysis_queue import AnalysisQueueUnavailable
from app.services.generation import providers
from app.services.generation.providers import ScriptedProvider
from app.services.llm_errors import LLMUnavailableError
from app.status import AnalysisStatus

ANNOUNCEMENT_SUMMARY = {
    "summary": "The company confirmed its dividend timetable.",
    "about": "The filing explains dividend timing.",
    "changed": "The payment date was confirmed.",
    "matters": "Investors can plan income timing.",
    "confirmed_facts": ["The payment date is 2 January 2040."],
    "speculation": ["The dividend may affect future income expectations."],
}
NEWS_SUMMARY = {
    "summary": "BHP reported higher copper production.",
    "about": "The story covers BHP's quarterly copper output.",
    "changed": "Reported production increased.",
    "matters": "The increase may affect revenue expectations.",
}
EVERY_WHITESPACE = "".join(
    character for character in map(chr, range(sys.maxunicode + 1)) if character.isspace()
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"Database is not available: {exc}")
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture()
def scripted(monkeypatch: pytest.MonkeyPatch):
    def install(*responses: str | Exception) -> ScriptedProvider:
        provider = ScriptedProvider(list(responses))
        monkeypatch.setattr(providers, "configured_provider", lambda: provider)
        return provider

    return install


@pytest.fixture()
def queue(monkeypatch: pytest.MonkeyPatch) -> list[SummaryRequestMessage]:
    """The requests the summary routes send, with the analysis queue configured."""
    monkeypatch.setattr(settings, "ANALYSIS_QUEUE_URL", "https://sqs.example/analysis")
    return []


def _bhp(db: Session) -> Ticker:
    return db.scalars(select(Ticker).where(Ticker.symbol == "BHP")).one()


def _artifact(db: Session, **values) -> Artifact:
    artifact = Artifact(
        content_hash=f"test-{uuid.uuid4()}",
        published_at=datetime.now(timezone.utc) - timedelta(days=1),
        **values,
    )
    db.add(artifact)
    db.commit()
    return artifact


def _announcement(db: Session, **values) -> Artifact:
    return _artifact(
        db,
        **{
            "source_type": "asx_announcement",
            "artifact_type": "dividend_announcement",
            "ticker_id": _bhp(db).id,
            "title": "Dividend update",
            "raw_text": "The company confirmed a dividend payment date.",
            "artifact_metadata": {
                "category": "DividendAnnouncement",
                "extracted_data": {"payment_date": "2040-01-02"},
            },
            **values,
        },
    )


def _news(db: Session, **values) -> Artifact:
    return _artifact(
        db,
        **{
            "source_type": "news",
            "artifact_type": "news_article",
            "ticker_id": _bhp(db).id,
            "title": "BHP production story",
            "raw_text": "BHP reported an increase in quarterly copper production.",
            "artifact_metadata": {"source_name": "Example News"},
            **values,
        },
    )


def _reddit_post(db: Session, title: str, engagement: int) -> Artifact:
    return _artifact(
        db,
        source_type="reddit",
        artifact_type="reddit_post",
        ticker_id=_bhp(db).id,
        title=title,
        raw_text=f"{title} body",
        artifact_metadata={"score": engagement, "engagement": engagement},
    )


def _requested(sent: list[SummaryRequestMessage]) -> list[uuid.UUID]:
    assert all(isinstance(message, SummaryRequestMessage) for message in sent)
    return [message.artifact_id for message in sent]


def test_the_summary_routes_answer_202() -> None:
    accepted = {
        route.path: route.status_code
        for route in llm.router.routes
        if "/summarise/" in route.path
    }

    assert accepted == {
        "/llm/summarise/ticker/{symbol}": 202,
        "/llm/summarise/artifact/{artifact_id}": 202,
    }


def test_the_artifact_route_queues_one_summary_request(
    db_session: Session,
    queue: list[SummaryRequestMessage],
) -> None:
    announcement = _announcement(db_session)

    result = llm.summarise_artifact(announcement.id, db=db_session, send=queue.append)

    assert result == {"artifact_id": announcement.id, "queued": True}
    assert _requested(queue) == [announcement.id]


@pytest.mark.parametrize(
    ("artifact", "detail"),
    [("missing", "Artifact not found"), ("textless", "Artifact has no text to summarise")],
)
def test_the_artifact_route_answers_404_with_nothing_to_summarise(
    db_session: Session,
    queue: list[SummaryRequestMessage],
    artifact: str,
    detail: str,
) -> None:
    artifact_id = (
        uuid.uuid4() if artifact == "missing" else _announcement(db_session, raw_text=None).id
    )

    with pytest.raises(HTTPException) as error:
        llm.summarise_artifact(artifact_id, db=db_session, send=queue.append)

    assert (error.value.status_code, error.value.detail) == (404, detail)
    assert queue == []


@pytest.mark.parametrize(
    "raw_text",
    ["", "   ", "\n\t\r\n", EVERY_WHITESPACE],
    ids=["empty", "spaces", "line breaks", "every whitespace character"],
)
def test_the_summary_routes_never_queue_text_the_worker_refuses(
    db_session: Session,
    queue: list[SummaryRequestMessage],
    raw_text: str,
) -> None:
    """The analysis worker summarises the text stripped, so blank text has nothing to summarise."""
    blank = _news(db_session, raw_text=raw_text)
    pending = _announcement(db_session)

    with pytest.raises(HTTPException) as error:
        llm.summarise_artifact(blank.id, db=db_session, send=queue.append)
    result = llm.summarise_ticker_artifacts("BHP", db=db_session, send=queue.append)

    assert (error.value.status_code, error.value.detail) == (
        404,
        "Artifact has no text to summarise",
    )
    assert (result["candidates"], result["artifact_ids"]) == (1, [pending.id])
    assert _requested(queue) == [pending.id]


def test_the_ticker_route_queues_only_artifacts_without_a_complete_summary(
    db_session: Session,
    queue: list[SummaryRequestMessage],
) -> None:
    pending = _announcement(db_session)
    _announcement(db_session, artifact_metadata=ANNOUNCEMENT_SUMMARY)
    # News has no clarity lists, so asking for them summarised it again every call.
    _news(db_session, artifact_metadata={"source_name": "Example News", **NEWS_SUMMARY})
    _news(db_session, analysis_status=AnalysisStatus.QUEUED)

    result = llm.summarise_ticker_artifacts("BHP", db=db_session, send=queue.append)

    assert result == {
        "ticker": "BHP",
        "candidates": 4,
        "queued": 1,
        "skipped": 3,
        "artifact_ids": [pending.id],
        "errors": [],
    }
    assert _requested(queue) == [pending.id]


def test_the_ticker_route_lists_a_request_the_queue_refused_and_sends_the_rest(
    db_session: Session,
    queue: list[SummaryRequestMessage],
) -> None:
    announcements = {_announcement(db_session).id, _announcement(db_session).id}
    refused: list[uuid.UUID] = []

    def refuse_the_first(message: SummaryRequestMessage) -> None:
        if not refused:
            refused.append(message.artifact_id)
            raise AnalysisQueueUnavailable("The analysis queue did not accept the request")
        queue.append(message)

    result = llm.summarise_ticker_artifacts("BHP", db=db_session, send=refuse_the_first)

    assert result["errors"] == [
        {
            "artifact_id": str(refused[0]),
            "error": "The analysis queue did not accept the request",
        }
    ]
    assert result["queued"] == 1
    assert {*result["artifact_ids"], *refused} == announcements


@pytest.mark.parametrize(("limit", "status"), [(0, 422), (51, 422), (50, 202)])
def test_the_ticker_route_queues_at_most_50_requests(
    db_session: Session,
    queue: list[SummaryRequestMessage],
    limit: int,
    status: int,
) -> None:
    """Each request is one Bedrock call, and the analysis consumer has no concurrency cap."""
    pending = _announcement(db_session)
    api = FastAPI()
    api.include_router(llm.router)
    api.dependency_overrides[get_db] = lambda: db_session
    api.dependency_overrides[analysis_queue.analysis_sender] = lambda: queue.append

    response = TestClient(api).post(f"/llm/summarise/ticker/BHP?limit={limit}")

    assert response.status_code == status
    assert _requested(queue) == ([pending.id] if status == 202 else [])


def test_the_ticker_route_answers_404_for_an_unknown_ticker(
    db_session: Session,
    queue: list[SummaryRequestMessage],
) -> None:
    with pytest.raises(HTTPException) as error:
        llm.summarise_ticker_artifacts("NOPE", db=db_session, send=queue.append)

    assert (error.value.status_code, error.value.detail) == (404, "Ticker 'NOPE' not found")


@pytest.mark.parametrize("route", ["summarise_artifact", "summarise_ticker"])
def test_the_summary_routes_answer_503_without_an_analysis_queue(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    announcement = _announcement(db_session)
    monkeypatch.setattr(settings, "ANALYSIS_QUEUE_URL", "")
    sent: list[SummaryRequestMessage] = []
    call = {
        "summarise_artifact": lambda: llm.summarise_artifact(
            announcement.id, db=db_session, send=sent.append
        ),
        "summarise_ticker": lambda: llm.summarise_ticker_artifacts(
            "BHP", db=db_session, send=sent.append
        ),
    }[route]

    with pytest.raises(HTTPException) as error:
        call()

    assert (error.value.status_code, error.value.detail) == (
        503,
        "ANALYSIS_QUEUE_URL is not configured",
    )
    assert sent == []


def test_the_artifact_route_answers_503_when_the_queue_refuses_the_request(
    db_session: Session,
    queue: list[SummaryRequestMessage],
) -> None:
    announcement = _announcement(db_session)

    def refuse(_message: SummaryRequestMessage) -> None:
        raise AnalysisQueueUnavailable("The analysis queue did not accept the request")

    with pytest.raises(HTTPException) as error:
        llm.summarise_artifact(announcement.id, db=db_session, send=refuse)

    assert error.value.status_code == 503


def test_a_request_sqs_refuses_is_reported_as_an_unavailable_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from botocore.exceptions import EndpointConnectionError

    class UnreachableSqs:
        def send_message(self, **_message) -> dict:
            raise EndpointConnectionError(endpoint_url="https://sqs.example")

    monkeypatch.setattr(settings, "ANALYSIS_QUEUE_URL", "https://sqs.example/analysis")
    monkeypatch.setattr(analysis_queue, "_sqs_client", UnreachableSqs)

    with pytest.raises(AnalysisQueueUnavailable):
        analysis_queue.send_analysis_request(SummaryRequestMessage(artifact_id=uuid.uuid4()))


def test_category_split_reports_the_model(db_session: Session, scripted) -> None:
    _announcement(db_session)
    scripted(
        json.dumps(
            {
                "revenue": "",
                "strategy": "",
                "risk": "",
                "dividend": "A dividend date was confirmed.",
                "organisational": "",
            }
        )
    )

    result = llm.categorise_recent_artifacts("BHP", db=db_session)

    assert result["model_used"] == "scripted:test-model"
    assert result["categories"]["dividend"] == "A dividend date was confirmed."


def test_reddit_digest_summarises_the_most_engaging_posts(
    db_session: Session,
    scripted,
) -> None:
    _reddit_post(db_session, "BHP quiet week", engagement=2)
    _reddit_post(db_session, "BHP iron ore outlook", engagement=40)
    provider = scripted(
        json.dumps(
            {
                "summary": "Investors debate iron ore demand.",
                "dominant_sentiment": "Mixed",
                "key_themes": ["iron ore"],
            }
        )
    )

    result = reddit.reddit_ticker_sentiment("bhp", db=db_session, _investor=None)

    assert result["summary"] == "Investors debate iron ore demand."
    assert result["dominant_sentiment"] == "mixed"
    assert result["post_count"] == 2
    assert [post["title"] for post in result["posts_used"]] == [
        "BHP iron ore outlook",
        "BHP quiet week",
    ]
    assert "1. [40 upvotes] BHP iron ore outlook" in provider.calls[0].prompt


@pytest.mark.parametrize("route", ["categorise", "reddit_digest"])
def test_routes_answer_503_when_no_llm_is_on(
    db_session: Session,
    scripted,
    route: str,
) -> None:
    _announcement(db_session)
    _reddit_post(db_session, "BHP iron ore outlook", engagement=40)
    scripted(LLMUnavailableError("Amazon Bedrock is disabled"))
    call = {
        "categorise": lambda: llm.categorise_recent_artifacts("BHP", db=db_session),
        "reddit_digest": lambda: reddit.reddit_ticker_sentiment(
            "BHP",
            db=db_session,
            _investor=None,
        ),
    }[route]

    with pytest.raises(HTTPException) as error:
        call()

    assert error.value.status_code == 503
    assert error.value.detail == "Amazon Bedrock is disabled"
