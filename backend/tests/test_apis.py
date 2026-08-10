"""PyTest tests for the APIs in main.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from unittest.mock import patch, MagicMock


def test_health() -> None:
    """Confirming that the health API returns the "ok" status as expected"""
    assert main.health() == {"status": "ok"}


def test_news_feed_does_not_use_raw_text_as_summary() -> None:
    """Unsummarised announcements should be marked pending, not expose raw text."""
    import uuid

    from app.api.routes import ticker

    ticker_record = MagicMock()
    ticker_record.id = uuid.uuid4()
    ticker_record.symbol = "BHP"

    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.artifact_type = "asx_announcement_other"
    artifact.source_type = "asx_announcement"
    artifact.title = "Operational update"
    artifact.url = "https://example.com/announcement"
    artifact.raw_text = "This raw filing text must not be presented as a summary."
    artifact.artifact_metadata = {}
    artifact.published_at = None

    with patch.object(
        ticker.crud,
        "get_ticker_by_symbol",
        return_value=ticker_record,
    ), patch.object(
        ticker,
        "_ticker_artifacts",
        return_value=[artifact],
    ), patch.object(
        ticker,
        "_sources_for_artifact",
        return_value=[],
    ):
        result = ticker.get_ticker_news_feed("BHP", db=MagicMock())

    assert result[0]["about"] == "Summary pending."
    assert artifact.raw_text not in result[0]["about"]
    assert result[0]["source_type"] == "asx_announcement"
    assert result[0]["source_name"] is None
    assert result[0]["source_label"] == "View original ASX filing"


def test_news_feed_uses_source_aware_news_label() -> None:
    """News article cards should expose publisher-specific source labels."""
    import uuid

    from app.api.routes import ticker

    ticker_record = MagicMock()
    ticker_record.id = uuid.uuid4()
    ticker_record.symbol = "BHP"

    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.artifact_type = "news_article"
    artifact.source_type = "news"
    artifact.title = "BHP production story"
    artifact.url = "https://publisher.example/bhp-story"
    artifact.raw_text = "BHP reported stronger copper production."
    artifact.artifact_metadata = {
        "source_name": "publisher.example",
        "about": "The story covers BHP's production update.",
    }
    artifact.published_at = None

    with patch.object(
        ticker.crud,
        "get_ticker_by_symbol",
        return_value=ticker_record,
    ), patch.object(
        ticker,
        "_ticker_artifacts",
        return_value=[artifact],
    ), patch.object(
        ticker,
        "_sources_for_artifact",
        return_value=[],
    ):
        result = ticker.get_ticker_news_feed("BHP", db=MagicMock())

    assert result[0]["source_type"] == "news"
    assert result[0]["source_name"] == "publisher.example"
    assert result[0]["source_label"] == "View original at publisher.example"


def test_news_feed_uses_generic_source_label_when_news_source_missing() -> None:
    """News article cards should fall back cleanly when publisher metadata is absent."""
    import uuid

    from app.api.routes import ticker

    ticker_record = MagicMock()
    ticker_record.id = uuid.uuid4()
    ticker_record.symbol = "BHP"

    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.artifact_type = "news_article"
    artifact.source_type = "news"
    artifact.title = "BHP production story"
    artifact.url = "https://publisher.example/bhp-story"
    artifact.raw_text = "BHP reported stronger copper production."
    artifact.artifact_metadata = {"about": "The story covers BHP's production update."}
    artifact.published_at = None

    with patch.object(
        ticker.crud,
        "get_ticker_by_symbol",
        return_value=ticker_record,
    ), patch.object(
        ticker,
        "_ticker_artifacts",
        return_value=[artifact],
    ), patch.object(
        ticker,
        "_sources_for_artifact",
        return_value=[],
    ):
        result = ticker.get_ticker_news_feed("BHP", db=MagicMock())

    assert result[0]["source_type"] == "news"
    assert result[0]["source_name"] is None
    assert result[0]["source_label"] == "View original source"


def test_combined_ticker_brief_reuses_one_quote_lookup() -> None:
    """The shared frontend shell should need one quote request per ticker load."""
    from datetime import datetime, timezone
    import uuid

    from app.api.routes import ticker

    ticker_record = MagicMock(
        id=uuid.uuid4(),
        symbol="CBA",
        company_name="Commonwealth Bank of Australia",
        sector="Financials",
        industry="Banks",
        exchange="ASX",
    )
    published_at = datetime(2026, 8, 24, tzinfo=timezone.utc)
    artifact = MagicMock(
        id=uuid.uuid4(),
        title="CBA results",
        raw_text="CBA published its latest financial results.",
        artifact_metadata={"about": "CBA reported its latest financial results."},
        artifact_type="financial_results",
        source_type="asx_announcement",
        url="https://example.com/cba-results",
        published_at=published_at,
        created_at=published_at,
    )
    sentiment = MagicMock(
        sentiment_label="positive",
        confidence_score=0.91,
        model_used="ProsusAI/finbert",
        created_at=published_at,
    )

    with patch.object(ticker, "_ensure_default_tickers"), patch.object(
        ticker.crud,
        "get_ticker_by_symbol",
        return_value=ticker_record,
    ), patch.object(
        ticker,
        "_live_quote",
        return_value=(150.0, 149.0),
    ) as live_quote, patch.object(
        ticker,
        "_ticker_artifacts",
        return_value=[artifact],
    ), patch.object(
        ticker,
        "_latest_sentiment_for_ticker",
        return_value=sentiment,
    ):
        result = ticker.get_ticker_brief("CBA", db=MagicMock())

    live_quote.assert_called_once_with("CBA")
    assert result["overview"]["latest_signal_confidence_pct"] == "91%"
    assert result["overview"]["sentiment_status"] == "available"
    assert result["aside"]["key_numbers"][0]["value"] == "$150.00"


# --- Reddit route tests ---

def _make_mock_submission(
    id="abc123",
    title="Test Post",
    selftext="Some body text",
    score=100,
    upvote_ratio=0.95,
    num_comments=10,
    permalink="/r/ASX/comments/abc123/test_post/",
    url="https://reddit.com/r/ASX/comments/abc123/test_post/",
    author="testuser",
    link_flair_text="Discussion",
    is_self=True,
    created_utc=1715000000.0,
):
    s = MagicMock()
    s.id = id
    s.title = title
    s.selftext = selftext
    s.score = score
    s.upvote_ratio = upvote_ratio
    s.num_comments = num_comments
    s.permalink = permalink
    s.url = url
    s.author = author
    s.link_flair_text = link_flair_text
    s.is_self = is_self
    s.created_utc = created_utc
    return s


def test_list_reddit_posts_returns_posts() -> None:
    """GET /reddit/ returns a list of posts from the subreddit."""
    mock_post = _make_mock_submission()

    with patch("app.api.routes.reddit._get_reddit_client") as mock_client:
        mock_client.return_value.subreddit.return_value.hot.return_value = [mock_post]
        from app.api.routes.reddit import _fetch_posts
        result = _fetch_posts(subreddit_name="ASX", limit=1)

    assert len(result) == 1
    assert result[0]["id"] == "abc123"
    assert result[0]["title"] == "Test Post"
    assert result[0]["score"] == 100
    assert result[0]["author"] == "testuser"


def test_list_reddit_posts_truncates_body() -> None:
    """Body text is truncated to 1000 characters."""
    long_body = "x" * 2000
    mock_post = _make_mock_submission(selftext=long_body)

    with patch("app.api.routes.reddit._get_reddit_client") as mock_client:
        mock_client.return_value.subreddit.return_value.hot.return_value = [mock_post]
        from app.api.routes.reddit import _fetch_posts
        result = _fetch_posts(subreddit_name="ASX", limit=1)

    assert len(result[0]["body"]) == 1000


def test_list_reddit_posts_empty_body() -> None:
    """Posts with no body text return an empty string."""
    mock_post = _make_mock_submission(selftext="")

    with patch("app.api.routes.reddit._get_reddit_client") as mock_client:
        mock_client.return_value.subreddit.return_value.hot.return_value = [mock_post]
        from app.api.routes.reddit import _fetch_posts
        result = _fetch_posts(subreddit_name="ASX", limit=1)

    assert result[0]["body"] == ""


def test_list_reddit_posts_external_url_for_link_post() -> None:
    """Link posts (is_self=False) populate external_url."""
    mock_post = _make_mock_submission(
        is_self=False,
        url="https://example.com/article"
    )

    with patch("app.api.routes.reddit._get_reddit_client") as mock_client:
        mock_client.return_value.subreddit.return_value.hot.return_value = [mock_post]
        from app.api.routes.reddit import _fetch_posts
        result = _fetch_posts(subreddit_name="ASX", limit=1)

    assert result[0]["external_url"] == "https://example.com/article"
    assert result[0]["is_self"] is False


def test_summarise_reddit_posts_uses_configured_groq_model() -> None:
    """Reddit summaries should use the configured Groq model, not a hardcoded ID."""
    from app.api.routes import reddit

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=(
                    '{"summary": "Retail investors are mixed on BHP.", '
                    '"dominant_sentiment": "mixed", '
                    '"key_themes": ["iron ore"]}'
                )
            )
        )
    ]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch.object(
        reddit,
        "_get_groq_client",
        return_value=mock_client,
    ), patch.object(
        reddit.settings,
        "GROQ_MODEL",
        "openai/gpt-oss-120b",
    ):
        result = reddit._summarise_reddit_posts(
            "BHP",
            [
                {
                    "title": "BHP outlook",
                    "body": "Investors are debating iron ore demand.",
                    "score": 12,
                }
            ],
        )

    assert result["summary"] == "Retail investors are mixed on BHP."
    mock_client.chat.completions.create.assert_called_once()
    assert (
        mock_client.chat.completions.create.call_args.kwargs["model"]
        == "openai/gpt-oss-120b"
    )


def test_sentiment_route_reads_stored_analysis_without_finbert() -> None:
    """Ticker views read worker-produced sentiment without API inference."""
    from datetime import datetime, timezone
    import uuid

    from app.api.routes import category_sentiment
    from app.schemas.category_sentiment import CategorySentimentResponse

    ticker_record = MagicMock(id=uuid.uuid4(), symbol="ANZ")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = ticker_record

    revenue_artifact = MagicMock(
        source_type="asx_announcement",
        artifact_type="financial_results",
        title="ANZ revenue increased",
        artifact_metadata={"about": "Revenue increased during the half year."},
    )
    reddit_artifact = MagicMock(
        source_type="reddit",
        artifact_type="reddit_post",
        title="Investors discuss ANZ",
        artifact_metadata={"summary": "Investors remain mixed on ANZ."},
    )
    analyzed_at = datetime(2026, 8, 24, tzinfo=timezone.utc)
    positive = MagicMock(
        sentiment_label="positive",
        confidence_score=0.86,
        model_used="ProsusAI/finbert",
        created_at=analyzed_at,
    )
    neutral = MagicMock(
        sentiment_label="neutral",
        confidence_score=0.71,
        model_used="ProsusAI/finbert",
        created_at=analyzed_at,
    )

    with patch.object(
        category_sentiment,
        "_stored_sentiment_rows",
        return_value=[(revenue_artifact, positive), (reddit_artifact, neutral)],
    ), patch.object(
        category_sentiment.sentiment_service,
        "analyse_categories",
    ) as analyse_categories:
        result = category_sentiment.get_ticker_category_sentiments("anz", db=db)

    assert result["ticker"] == "ANZ"
    assert result["status"] == "partial"
    assert result["model_used"] == "ProsusAI/finbert"
    assert set(result["categories"]) == {
        "revenue",
        "strategy",
        "risk",
        "dividend",
        "organisational",
        "user_discussion",
    }
    assert result["categories"]["revenue"]["sentiment_label"] == "positive"
    assert result["categories"]["revenue"]["available"] is True
    assert result["categories"]["risk"]["sentiment_label"] is None
    assert result["categories"]["risk"]["available"] is False
    assert result["categories"]["user_discussion"]["sentiment_label"] == "neutral"
    validated = CategorySentimentResponse.model_validate(result)
    assert validated.status == "partial"
    assert validated.categories["risk"].sentiment_label is None
    analyse_categories.assert_not_called()


def test_sentiment_route_reports_unavailable_without_stored_analysis() -> None:
    from app.api.routes import category_sentiment

    ticker_record = MagicMock(id="ticker-id", symbol="BHP")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = ticker_record

    with patch.object(category_sentiment, "_stored_sentiment_rows", return_value=[]):
        result = category_sentiment.get_ticker_category_sentiments("bhp", db=db)

    assert result["status"] == "unavailable"
    assert result["model_used"] is None
    assert all(not category["available"] for category in result["categories"].values())
    assert all(category["sentiment_label"] is None for category in result["categories"].values())


def test_sentiment_post_rejects_ad_hoc_api_inference() -> None:
    import pytest
    from fastapi import HTTPException

    from app.api.routes import category_sentiment
    from app.schemas.category_sentiment import CategorySentimentRequest

    with pytest.raises(HTTPException) as error:
        category_sentiment.build_ticker_category_sentiment(
            ticker="ANZ",
            body=CategorySentimentRequest(categories={"revenue": "Revenue increased."}),
            db=MagicMock(),
        )

    assert error.value.status_code == 503
    assert "analysis pipeline" in error.value.detail


def test_gemini_summary_response_parser_accepts_strict_json() -> None:
    """Gemini summary parsing should preserve text and clarity fields."""
    from app.services.gemini import parse_summary_response

    result = parse_summary_response(
        """
        {
          "summary": "The company announced an updated dividend timetable.",
          "about": "The filing explains the dividend key dates.",
          "changed": "The payment date was confirmed.",
          "matters": "Investors can use the dates to plan income expectations.",
          "confirmed_facts": ["The payment date is 2 January 2040."],
          "speculation": ["Investors may use the date to plan future income."]
        }
        """
    )

    assert result == {
        "summary": "The company announced an updated dividend timetable.",
        "about": "The filing explains the dividend key dates.",
        "changed": "The payment date was confirmed.",
        "matters": "Investors can use the dates to plan income expectations.",
        "confirmed_facts": ["The payment date is 2 January 2040."],
        "speculation": ["Investors may use the date to plan future income."],
    }


def test_gemini_summary_response_parser_rejects_missing_keys() -> None:
    """Incomplete Gemini JSON should fail before storage uses it."""
    import pytest

    from app.services.gemini import parse_summary_response

    with pytest.raises(ValueError, match="missing keys"):
        parse_summary_response('{"summary": "Only one field"}')


def test_gemini_summary_response_parser_rejects_non_list_clarity_fields() -> None:
    """Clarity fields must remain structured so the UI can label each claim."""
    import pytest

    from app.services.gemini import parse_summary_response

    with pytest.raises(ValueError, match="confirmed_facts.*list of strings"):
        parse_summary_response(
            """
            {
              "summary": "A summary.",
              "about": "An announcement.",
              "changed": "A change.",
              "matters": "An impact.",
              "confirmed_facts": "This should be a list.",
              "speculation": []
            }
            """
        )


def test_summarise_artifact_route_stores_summary_and_metadata() -> None:
    """Manual summary backfill should update artifact metadata and create a row."""
    import uuid

    from app.api.routes import gemini

    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.title = "Dividend update"
    artifact.artifact_type = "dividend_announcement"
    artifact.raw_text = "The company confirmed a dividend payment date."
    artifact.artifact_metadata = {
        "category": "DividendAnnouncement",
        "extracted_data": {"payment_date": "2040-01-02"},
    }
    db = MagicMock()

    with patch.object(
        gemini.artifact_crud,
        "get_artifact",
        return_value=artifact,
    ), patch.object(
        gemini.gemini_service,
        "summarise_announcement",
        return_value={
            "summary": "The company confirmed its dividend timetable.",
            "about": "The filing explains dividend timing.",
            "changed": "The payment date was confirmed.",
            "matters": "Investors can plan income timing.",
            "confirmed_facts": ["The payment date is 2 January 2040."],
            "speculation": ["The dividend may affect future income expectations."],
        },
    ), patch.object(
        gemini.artifact_summary_crud,
        "upsert_artifact_summary",
        return_value=MagicMock(
            id=uuid.uuid4(),
            model_used="test-gemini",
            prompt_version="test-v1",
        ),
    ) as mock_upsert:
        result = gemini.summarise_artifact(
            artifact_id=artifact.id,
            db=db,
        )

    assert artifact.artifact_metadata["about"] == "The filing explains dividend timing."
    assert artifact.artifact_metadata["changed"] == "The payment date was confirmed."
    assert artifact.artifact_metadata["matters"] == "Investors can plan income timing."
    assert artifact.artifact_metadata["confirmed_facts"] == [
        "The payment date is 2 January 2040."
    ]
    assert artifact.artifact_metadata["speculation"] == [
        "The dividend may affect future income expectations."
    ]
    assert result["summary"] == "The company confirmed its dividend timetable."
    mock_upsert.assert_called_once()


def test_summarise_news_artifact_uses_news_prompt() -> None:
    """News artifacts should not be summarised as official ASX filings."""
    import uuid

    from app.api.routes import gemini

    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.title = "BHP production story"
    artifact.source_type = "news"
    artifact.artifact_type = "news_article"
    artifact.raw_text = "BHP reported an increase in quarterly copper production."
    artifact.artifact_metadata = {"source_name": "Example News"}
    db = MagicMock()

    with patch.object(
        gemini.artifact_crud,
        "get_artifact",
        return_value=artifact,
    ), patch.object(
        gemini.gemini_service,
        "summarise_news_article",
        return_value={
            "summary": "BHP reported higher copper production.",
            "about": "The story covers BHP's quarterly copper output.",
            "changed": "Reported production increased.",
            "matters": "The increase may affect revenue expectations.",
        },
    ) as summarise_news, patch.object(
        gemini.gemini_service,
        "summarise_announcement",
    ) as summarise_announcement:
        result = gemini.summarise_artifact(artifact.id, db=db)

    assert result["about"] == "The story covers BHP's quarterly copper output."
    assert result["prompt_version"] == "groq-news-summary-v1"
    summarise_news.assert_called_once_with(
        title="BHP production story",
        source_name="Example News",
        raw_text=artifact.raw_text,
    )
    summarise_announcement.assert_not_called()


def test_summary_metadata_clears_stale_speculation_without_mutating_input() -> None:
    """A later summary can replace old clarity classifications with empty lists."""
    from app.api.routes.gemini import _summary_metadata

    metadata = {
        "category": "DividendAnnouncement",
        "speculation": ["An outdated forecast."],
    }
    result = _summary_metadata(
        metadata,
        {
            "summary": "A concise summary.",
            "about": "",
            "changed": "No material change identified.",
            "matters": "The dates help investors plan.",
            "confirmed_facts": ["The payment date was announced."],
            "speculation": [],
        },
    )

    assert result["confirmed_facts"] == ["The payment date was announced."]
    assert result["speculation"] == []
    assert metadata["speculation"] == ["An outdated forecast."]
