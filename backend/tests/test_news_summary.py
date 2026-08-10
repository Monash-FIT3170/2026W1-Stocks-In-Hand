"""Tests for reusable news artifact summarisation helpers."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services import news_summary


def _artifact(**overrides):
    values = {
        "id": uuid.uuid4(),
        "title": "BHP reports stronger copper production",
        "raw_text": "BHP reported stronger copper production in its quarterly update.",
        "artifact_metadata": {
            "provider": "marketaux",
            "source_name": "publisher.example",
        },
    }
    values.update(overrides)
    artifact = MagicMock()
    for key, value in values.items():
        setattr(artifact, key, value)
    return artifact


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({}, False),
        ({"about": ""}, False),
        ({"about": "   "}, False),
        ({"about": "The story covers BHP."}, True),
        (None, False),
    ],
)
def test_has_news_summary_metadata(metadata, expected) -> None:
    artifact = _artifact(artifact_metadata=metadata)

    assert news_summary.has_news_summary_metadata(artifact) is expected


def test_summarise_news_artifact_stores_summary_metadata() -> None:
    db = MagicMock()
    artifact = _artifact()

    with patch.object(
        news_summary.summary_service,
        "summarise_news_article",
        return_value={
            "summary": "BHP reported stronger copper production.",
            "about": "The story covers BHP's quarterly copper production.",
            "changed": "Reported copper output increased.",
            "matters": "Higher output may affect revenue expectations.",
        },
    ) as summarise_news:
        summary_row = news_summary.summarise_news_artifact(db, artifact)

    summarise_news.assert_called_once_with(
        title="BHP reports stronger copper production",
        source_name="publisher.example",
        raw_text="BHP reported stronger copper production in its quarterly update.",
    )
    assert artifact.artifact_metadata["summary"] == "BHP reported stronger copper production."
    assert artifact.artifact_metadata["about"] == (
        "The story covers BHP's quarterly copper production."
    )
    assert artifact.artifact_metadata["changed"] == "Reported copper output increased."
    assert artifact.artifact_metadata["matters"] == (
        "Higher output may affect revenue expectations."
    )
    assert summary_row.artifact_id == artifact.id
    assert summary_row.prompt_version == "groq-news-summary-v1"
    assert "BHP reported stronger copper production." in summary_row.summary_text
    db.add.assert_called_once_with(summary_row)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(summary_row)


def test_summarise_news_artifact_uses_fallback_title() -> None:
    db = MagicMock()
    artifact = _artifact(title=None, artifact_metadata={})

    with patch.object(
        news_summary.summary_service,
        "summarise_news_article",
        return_value={
            "summary": "A brief news summary.",
            "about": "The story covers a company update.",
            "changed": "No material change identified.",
            "matters": "Investors may monitor follow-up reports.",
        },
    ) as summarise_news:
        news_summary.summarise_news_artifact(db, artifact)

    summarise_news.assert_called_once_with(
        title="Untitled news story",
        source_name=None,
        raw_text="BHP reported stronger copper production in its quarterly update.",
    )


def test_summarise_news_artifact_rejects_empty_text() -> None:
    db = MagicMock()
    artifact = _artifact(raw_text=" ")

    with pytest.raises(ValueError, match="News artifact has no text to summarise"):
        news_summary.summarise_news_artifact(db, artifact)

    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_summarise_news_for_symbol_summarises_unsummarised_artifacts() -> None:
    db = MagicMock()
    ticker = MagicMock(symbol="BHP")
    unsummarised = _artifact(artifact_metadata={})
    summarised = _artifact(artifact_metadata={"about": "Existing summary"})

    with patch.object(
        news_summary,
        "_ticker_for_symbol",
        return_value=ticker,
    ), patch.object(
        news_summary,
        "_news_artifacts_for_ticker",
        return_value=[unsummarised, summarised],
    ), patch.object(
        news_summary,
        "summarise_news_artifact",
    ) as summarise_artifact:
        result = news_summary.summarise_news_for_symbol(db, "bhp", limit=10)

    assert result == {
        "ticker": "BHP",
        "candidates": 2,
        "summarised": 1,
        "skipped": 1,
        "errors": [],
    }
    summarise_artifact.assert_called_once_with(db, unsummarised)


def test_summarise_news_for_symbol_records_artifact_errors_and_continues() -> None:
    db = MagicMock()
    ticker = MagicMock(symbol="BHP")
    failed = _artifact(title="Broken story", artifact_metadata={})
    later = _artifact(title="Later story", artifact_metadata={})

    with patch.object(
        news_summary,
        "_ticker_for_symbol",
        return_value=ticker,
    ), patch.object(
        news_summary,
        "_news_artifacts_for_ticker",
        return_value=[failed, later],
    ), patch.object(
        news_summary,
        "summarise_news_artifact",
        side_effect=[ValueError("News artifact has no text to summarise"), MagicMock()],
    ):
        result = news_summary.summarise_news_for_symbol(db, "BHP", limit=10)

    assert result["candidates"] == 2
    assert result["summarised"] == 1
    assert result["skipped"] == 0
    assert result["errors"] == [
        {
            "artifact_id": str(failed.id),
            "title": "Broken story",
            "message": "News artifact has no text to summarise",
        }
    ]
    db.rollback.assert_called_once()


def test_summarise_news_for_symbol_missing_ticker_raises_value_error() -> None:
    db = MagicMock()

    with patch.object(
        news_summary,
        "_ticker_for_symbol",
        side_effect=ValueError("Ticker 'BHP' not found"),
    ):
        with pytest.raises(ValueError, match="Ticker 'BHP' not found"):
            news_summary.summarise_news_for_symbol(db, "BHP")


def test_news_artifacts_for_ticker_filters_to_news_rows() -> None:
    db = MagicMock()
    ticker = MagicMock(id=uuid.uuid4())
    query = db.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query

    news_summary._news_artifacts_for_ticker(db, ticker, limit=25)

    filters = query.filter.call_args_list
    assert filters[0].args[0].compare(news_summary.Artifact.ticker_id == ticker.id)
    assert filters[1].args[0].compare(
        news_summary.Artifact.source_type == news_summary.NEWS_SOURCE_TYPE
    )
    assert filters[2].args[0].compare(
        news_summary.Artifact.artifact_type == news_summary.NEWS_ARTIFACT_TYPE
    )
    query.limit.assert_called_once_with(25)
