"""Tests for raw-text news sentiment analysis."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services import news_sentiment


def _artifact(**overrides):
    values = {
        "id": uuid.uuid4(),
        "title": "BHP reports stronger copper production",
        "raw_text": "BHP reported stronger copper production in its quarterly update.",
        "artifact_metadata": {
            "summary": "This generated summary must not be analysed.",
            "about": "This generated about text must not be analysed.",
        },
    }
    values.update(overrides)
    artifact = MagicMock()
    for key, value in values.items():
        setattr(artifact, key, value)
    return artifact


def test_analyse_news_artifact_sentiment_uses_raw_text_only() -> None:
    db = MagicMock()
    artifact = _artifact()

    with patch.object(
        news_sentiment.sentiment_service,
        "analyse_text",
        return_value={
            "sentiment_label": "positive",
            "label": "positive",
            "confidence_score": 0.87,
            "model_used": "test-finbert",
        },
    ) as analyse_text:
        sentiment = news_sentiment.analyse_news_artifact_sentiment(db, artifact)

    analyse_text.assert_called_once_with(
        "BHP reported stronger copper production in its quarterly update."
    )
    assert sentiment.artifact_id == artifact.id
    assert sentiment.sentiment_label == "positive"
    assert sentiment.stance == "positive"
    assert sentiment.confidence_score == 0.87
    assert sentiment.model_used == "test-finbert"
    db.add.assert_called_once_with(sentiment)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(sentiment)


def test_analyse_news_artifact_sentiment_rejects_empty_text() -> None:
    db = MagicMock()
    artifact = _artifact(raw_text=" ")

    with pytest.raises(ValueError, match="News artifact has no text to analyse"):
        news_sentiment.analyse_news_artifact_sentiment(db, artifact)

    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_has_news_sentiment_detects_existing_sentiment() -> None:
    db = MagicMock()
    artifact = _artifact()
    db.query.return_value.filter.return_value.first.return_value = MagicMock()

    assert news_sentiment.has_news_sentiment(db, artifact) is True


def test_has_news_sentiment_detects_missing_sentiment() -> None:
    db = MagicMock()
    artifact = _artifact()
    db.query.return_value.filter.return_value.first.return_value = None

    assert news_sentiment.has_news_sentiment(db, artifact) is False


def test_analyse_news_sentiment_for_symbol_skips_existing_sentiment() -> None:
    db = MagicMock()
    ticker = MagicMock(symbol="BHP")
    fresh = _artifact(title="Fresh story")
    analysed = _artifact(title="Analysed story")

    with patch.object(
        news_sentiment.news_summary,
        "_ticker_for_symbol",
        return_value=ticker,
    ), patch.object(
        news_sentiment.news_summary,
        "_news_artifacts_for_ticker",
        return_value=[fresh, analysed],
    ), patch.object(
        news_sentiment,
        "has_news_sentiment",
        side_effect=[False, True],
    ), patch.object(
        news_sentiment,
        "analyse_news_artifact_sentiment",
    ) as analyse_artifact:
        result = news_sentiment.analyse_news_sentiment_for_symbol(db, "bhp", limit=10)

    assert result == {
        "ticker": "BHP",
        "candidates": 2,
        "analysed": 1,
        "skipped": 1,
        "errors": [],
    }
    analyse_artifact.assert_called_once_with(db, fresh)


def test_analyse_news_sentiment_for_symbol_records_errors_and_continues() -> None:
    db = MagicMock()
    ticker = MagicMock(symbol="BHP")
    failed = _artifact(title="Broken story")
    later = _artifact(title="Later story")

    with patch.object(
        news_sentiment.news_summary,
        "_ticker_for_symbol",
        return_value=ticker,
    ), patch.object(
        news_sentiment.news_summary,
        "_news_artifacts_for_ticker",
        return_value=[failed, later],
    ), patch.object(
        news_sentiment,
        "has_news_sentiment",
        return_value=False,
    ), patch.object(
        news_sentiment,
        "analyse_news_artifact_sentiment",
        side_effect=[ValueError("News artifact has no text to analyse"), MagicMock()],
    ):
        result = news_sentiment.analyse_news_sentiment_for_symbol(db, "BHP", limit=10)

    assert result["candidates"] == 2
    assert result["analysed"] == 1
    assert result["skipped"] == 0
    assert result["errors"] == [
        {
            "artifact_id": str(failed.id),
            "title": "Broken story",
            "message": "News artifact has no text to analyse",
        }
    ]
    db.rollback.assert_called_once()


def test_analyse_news_sentiment_for_symbol_missing_ticker_raises_value_error() -> None:
    db = MagicMock()

    with patch.object(
        news_sentiment.news_summary,
        "_ticker_for_symbol",
        side_effect=ValueError("Ticker 'BHP' not found"),
    ):
        with pytest.raises(ValueError, match="Ticker 'BHP' not found"):
            news_sentiment.analyse_news_sentiment_for_symbol(db, "BHP")
