"""Tests for Marketaux news normalisation, storage, and API wiring."""

import uuid
from datetime import datetime, timezone
from unittest.mock import ANY, MagicMock, patch

import pytest

from app.api.routes import news
from app.schemas.artifact import ArtifactType, SourceType
from app.services import marketaux


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


def test_duplicate_article_is_skipped() -> None:
    db = MagicMock()
    ticker = MagicMock(id=uuid.uuid4(), symbol="BHP")
    platform = MagicMock(id=uuid.uuid4())
    article = _article()
    existing = MagicMock()
    existing.artifact_metadata = {"about": "Existing summary"}

    with patch.object(marketaux, "fetch_news", return_value=[article]), patch.object(
        marketaux,
        "_get_or_create_ticker",
        return_value=ticker,
    ), patch.object(
        marketaux,
        "_get_or_create_platform",
        return_value=platform,
    ), patch.object(
        marketaux.artifact_crud,
        "get_artifact_by_hash",
        return_value=existing,
    ), patch.object(
        marketaux.artifact_crud,
        "create_artifact",
    ) as create_artifact:
        result = marketaux.fetch_and_store_news("BHP", 10, db)

    assert result["found"] == 1
    assert result["created"] == 0
    assert result["summarised"] == 0
    assert result["skipped_duplicates"] == 1
    assert result["errors"] == 0
    create_artifact.assert_not_called()


def test_correct_news_artifact_is_created() -> None:
    db = MagicMock()
    ticker = MagicMock(id=uuid.uuid4(), symbol="BHP")
    platform = MagicMock(id=uuid.uuid4())
    article = _article(raw_text="Description-only text", text_used="description")

    with patch.object(marketaux, "fetch_news", return_value=[article]), patch.object(
        marketaux,
        "_get_or_create_ticker",
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
    ) as create_artifact, patch.object(
        marketaux,
        "_summarise_and_store_news_artifact",
    ) as summarise_artifact:
        result = marketaux.fetch_and_store_news("BHP", 10, db)

    assert result["created"] == 1
    assert result["summarised"] == 1
    artifact = create_artifact.call_args.kwargs["artifact"]
    assert artifact.source_type == SourceType.NEWS
    assert artifact.artifact_type == ArtifactType.NEWS_ARTICLE
    assert artifact.raw_text == "Description-only text"
    assert artifact.ticker_id == ticker.id
    assert artifact.platform_id == platform.id
    assert artifact.artifact_metadata["provider"] == "marketaux"
    assert artifact.artifact_metadata["text_used"] == "description"
    assert artifact.artifact_metadata["symbols"] == ["BHP.AX"]
    summarise_artifact.assert_called_once()


def test_news_summary_is_stored_in_artifact_metadata() -> None:
    db = MagicMock()
    article = _article()
    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.artifact_metadata = {"provider": "marketaux"}

    with patch.object(
        marketaux.summary_service,
        "summarise_news_article",
        return_value={
            "summary": "BHP reported stronger copper production.",
            "about": "The story covers BHP's quarterly copper production.",
            "changed": "Reported copper output increased.",
            "matters": "Higher output may affect revenue expectations.",
        },
    ):
        marketaux._summarise_and_store_news_artifact(db, artifact, article)

    assert artifact.artifact_metadata["about"] == (
        "The story covers BHP's quarterly copper production."
    )
    summary_row = db.add.call_args.args[0]
    assert summary_row.artifact_id == artifact.id
    assert summary_row.prompt_version == "groq-news-summary-v1"
    db.commit.assert_called_once()


def test_news_fetch_route_response_shape() -> None:
    expected = {
        "symbol": "BHP",
        "found": 3,
        "created": 2,
        "summarised": 2,
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
