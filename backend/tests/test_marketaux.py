"""Tests for Marketaux news normalisation, storage, and API wiring.

Stored stories are handed to analysis, queued for the analysis worker by
default. The inline mode used to summarise stories instead and never queue
one with a summary, so news fetched on demand never got FinBERT sentiment.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import ANY, MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.routes import news
from app.core.config import settings
from app.messages import StoredTextAnalysisMessage
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.schemas.artifact import ArtifactType, SourceType
from app.services import analysis_queue, marketaux
from app.status import AnalysisStatus


def _payload(**overrides):
    payload = {
        "uuid": "article-123",
        "title": "BHP reports stronger copper production",
        "description": "BHP reported an increase in quarterly copper production.",
        "snippet": "Copper output increased during the quarter.",
        "full_text": "BHP reported stronger copper production in its quarterly update.",
        "url": "https://publisher.example/bhp-copper-update",
        "image_url": "https://publisher.example/image.jpg",
        "published_at": "2026-08-04T01:02:03Z",
        "source": "publisher.example",
        "entities": [
            {
                "symbol": "BHP.AX",
                "name": "BHP Group Limited",
                "exchange": "ASX",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _article(**overrides):
    values = {
        "provider_id": "article-123",
        "title": "BHP reports stronger copper production",
        "url": "https://publisher.example/bhp-copper-update",
        "published_at": datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc),
        "source_name": "publisher.example",
        "author": None,
        "raw_text": "BHP reported stronger copper production in its quarterly update.",
        "text_used": "full_text",
        "snippet": "Copper output increased during the quarter.",
        "description": "BHP reported an increase in quarterly copper production.",
        "symbols": ["BHP.AX"],
        "entities": [{"symbol": "BHP.AX", "name": "BHP Group Limited"}],
        "image_url": "https://publisher.example/image.jpg",
    }
    values.update(overrides)
    return marketaux.NewsArticle(**values)


def test_marketaux_response_normalisation() -> None:
    article = marketaux.normalise_article(_payload())

    assert article.provider_id == "article-123"
    assert article.title == "BHP reports stronger copper production"
    assert article.source_name == "publisher.example"
    assert article.published_at == datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc)
    assert article.symbols == ["BHP.AX"]
    assert article.image_url == "https://publisher.example/image.jpg"


def test_fetch_news_uses_exchange_qualified_asx_symbol() -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": [_payload()]}

    with patch.object(
        marketaux.settings,
        "MARKETAUX_API_TOKEN",
        "test-token",
    ), patch.object(
        marketaux.settings,
        "MARKETAUX_BASE_URL",
        "https://api.marketaux.test/v1",
    ), patch.object(
        marketaux.httpx,
        "get",
        return_value=response,
    ) as get:
        articles = marketaux.fetch_news("bhp", 7)

    assert len(articles) == 1
    assert get.call_args.args[0] == "https://api.marketaux.test/v1/news/all"
    assert get.call_args.kwargs["params"]["symbols"] == "BHP.AX"
    assert get.call_args.kwargs["params"]["limit"] == 7


@pytest.mark.parametrize(
    ("overrides", "expected_text", "expected_source"),
    [
        ({}, "full text", "full_text"),
        ({"full_text": None}, "description", "description"),
        ({"full_text": None, "description": ""}, "snippet", "snippet"),
        (
            {"full_text": None, "description": None, "snippet": None},
            "fallback title",
            "title",
        ),
    ],
)
def test_text_fallback(overrides, expected_text, expected_source) -> None:
    payload = {
        "title": "fallback title",
        "full_text": "full text",
        "description": "description",
        "snippet": "snippet",
        **overrides,
    }

    text, source = marketaux.select_article_text(payload)

    assert text == expected_text
    assert source == expected_source


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
    # The loop rolls back after a failed story; a savepoint per session
    # transaction keeps that rollback inside this test's transaction.
    session = sessionmaker(
        bind=connection,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


class FakeSqs:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    def send_message(self, **message) -> dict:
        self.bodies.append(message["MessageBody"])
        return {"MessageId": f"message-{len(self.bodies)}"}


def _stored_story(db: Session, article: marketaux.NewsArticle, **values) -> Artifact:
    bhp = db.scalars(select(Ticker).where(Ticker.symbol == "BHP")).one()
    story = Artifact(
        source_type="news",
        artifact_type="news_article",
        title=article.title,
        raw_text=article.raw_text,
        content_hash=marketaux.article_content_hash(article),
        ticker_id=bhp.id,
        **values,
    )
    db.add(story)
    db.commit()
    return story


def test_new_and_stored_stories_are_each_handed_to_analysis(db_session: Session) -> None:
    handed: list = []

    def analyse(_db: Session, story: Artifact) -> bool:
        handed.append(story.id)
        return True

    with patch.object(marketaux, "fetch_news", return_value=[_article()]):
        first = marketaux.fetch_and_store_news("BHP", 10, db_session, analyse=analyse)
        again = marketaux.fetch_and_store_news("BHP", 10, db_session, analyse=analyse)

    assert (first["created"], first["skipped_duplicates"], first["analysis_queued"]) == (1, 0, 1)
    assert (again["created"], again["skipped_duplicates"], again["analysis_queued"]) == (0, 1, 1)
    assert len(handed) == 2 and handed[0] == handed[1]
    assert "summarised" not in first


def test_stories_are_queued_unless_their_analysis_is_under_way_or_done(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new, summarised, analysed = (
        _article(url=f"https://publisher.example/{name}") for name in ("new", "old", "done")
    )
    # The inline mode summarised stories it fetched but never analysed them.
    pending = _stored_story(
        db_session,
        summarised,
        artifact_metadata={
            "summary": "BHP reported stronger copper production.",
            "about": "The story covers BHP production.",
            "changed": "Copper output rose.",
            "matters": "Output supports revenue.",
        },
    )
    done = _stored_story(db_session, analysed, analysis_status=AnalysisStatus.COMPLETED)
    sqs = FakeSqs()
    monkeypatch.setattr(settings, "ANALYSIS_QUEUE_URL", "https://sqs.example/analysis")
    monkeypatch.setattr(analysis_queue, "_sqs_client", lambda: sqs)

    with patch.object(marketaux, "fetch_news", return_value=[new, summarised, analysed]):
        result = marketaux.fetch_and_store_news("BHP", 10, db_session)

    queued = [StoredTextAnalysisMessage.model_validate_json(body).artifact_id for body in sqs.bodies]
    created = db_session.scalars(
        select(Artifact).where(Artifact.content_hash == marketaux.article_content_hash(new))
    ).one()
    db_session.refresh(pending)
    db_session.refresh(done)
    assert queued == [created.id, pending.id]
    assert result["analysis_queued"] == 2
    assert (pending.analysis_status, done.analysis_status) == (
        AnalysisStatus.QUEUED,
        AnalysisStatus.COMPLETED,
    )


def test_a_story_that_cannot_be_handed_on_is_listed_and_the_next_still_is(
    db_session: Session,
) -> None:
    first, second = (
        _article(url=f"https://publisher.example/{name}") for name in ("first", "second")
    )
    handed: list = []

    def analyse(_db: Session, story: Artifact) -> bool:
        if not handed:
            handed.append(None)
            raise RuntimeError("ANALYSIS_QUEUE_URL is not configured")
        handed.append(story.id)
        return True

    with patch.object(marketaux, "fetch_news", return_value=[first, second]):
        result = marketaux.fetch_and_store_news("BHP", 10, db_session, analyse=analyse)

    assert (result["created"], result["analysis_queued"], result["errors"]) == (2, 1, 1)
    assert result["error_details"] == [
        {
            "url": first.url,
            "stage": "queue_analysis",
            "message": "ANALYSIS_QUEUE_URL is not configured",
        }
    ]


def test_correct_news_artifact_is_created() -> None:
    db = MagicMock()
    ticker = MagicMock(id=uuid.uuid4(), symbol="BHP")
    platform = MagicMock(id=uuid.uuid4())
    article = _article(raw_text="Description-only text", text_used="description")
    analyse = MagicMock(return_value=True)

    with patch.object(marketaux, "fetch_news", return_value=[article]), patch.object(
        marketaux.ticker_crud,
        "ensure_ticker",
        return_value=ticker,
    ), patch.object(
        marketaux,
        "_get_or_create_platform",
        return_value=platform,
    ), patch.object(
        marketaux.artifact_crud,
        "get_artifact_by_hash",
        return_value=None,
    ), patch.object(
        marketaux.artifact_crud,
        "create_artifact",
        return_value=MagicMock(id=uuid.uuid4(), artifact_metadata={}),
    ) as create_artifact:
        result = marketaux.fetch_and_store_news("BHP", 10, db, analyse=analyse)

    assert (result["created"], result["analysis_queued"]) == (1, 1)
    analyse.assert_called_once_with(db, create_artifact.return_value)
    artifact = create_artifact.call_args.kwargs["artifact"]
    assert artifact.source_type == SourceType.NEWS
    assert artifact.artifact_type == ArtifactType.NEWS_ARTICLE
    assert artifact.raw_text == "Description-only text"
    assert artifact.ticker_id == ticker.id
    assert artifact.platform_id == platform.id
    assert artifact.artifact_metadata["provider"] == "marketaux"
    assert artifact.artifact_metadata["text_used"] == "description"
    assert artifact.artifact_metadata["symbols"] == ["BHP.AX"]


def test_news_fetch_route_response_shape() -> None:
    expected = {
        "symbol": "BHP",
        "found": 3,
        "created": 2,
        "analysis_queued": 3,
        "skipped_duplicates": 1,
        "errors": 0,
        "error_details": [],
    }

    with patch.object(
        news.marketaux,
        "fetch_and_store_news",
        return_value=expected,
    ) as fetch_and_store:
        result = news.fetch_symbol_news("bhp", limit=5, db=MagicMock())

    assert result == expected
    fetch_and_store.assert_called_once_with("bhp", 5, ANY)
