"""PyTest tests for the APIs in main.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from unittest.mock import patch, MagicMock
from sqlalchemy.exc import OperationalError


def test_health_ok_when_database_reachable() -> None:
    """The health endpoint reports ok once it can query the database."""
    db = MagicMock()
    assert main.health(db=db) == {"status": "ok"}
    db.execute.assert_called_once()


def test_health_reports_error_when_database_unreachable() -> None:
    """The health endpoint reports a 503 when the database can't be reached."""
    db = MagicMock()
    db.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("connection refused")
    )
    response = main.health(db=db)
    assert response.status_code == 503
    assert json.loads(response.body) == {
        "status": "error",
        "detail": "database unreachable",
    }


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

    with patch.object(
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


def _fetch_reddit(submission) -> list[dict]:
    from app.services.discussion_sources import reddit

    with patch.object(reddit.settings, "REDDIT_CLIENT_ID", "client"), patch.object(
        reddit.settings, "REDDIT_CLIENT_SECRET", "secret"
    ), patch.object(reddit.RedditSource, "client") as client:
        client.return_value.subreddit.return_value.hot.return_value = [submission]
        return reddit.REDDIT.fetch("ASX", 1)


def test_list_reddit_posts_returns_posts() -> None:
    """GET /reddit/ returns a list of posts from the subreddit."""
    mock_post = _make_mock_submission()

    result = _fetch_reddit(mock_post)

    assert len(result) == 1
    assert result[0]["id"] == "abc123"
    assert result[0]["title"] == "Test Post"
    assert result[0]["score"] == 100
    assert result[0]["author"] == "testuser"


def test_list_reddit_posts_truncates_body() -> None:
    """Body text is truncated to 1000 characters."""
    long_body = "x" * 2000
    mock_post = _make_mock_submission(selftext=long_body)

    result = _fetch_reddit(mock_post)

    assert len(result[0]["body"]) == 1000


def test_list_reddit_posts_empty_body() -> None:
    """Posts with no body text return an empty string."""
    mock_post = _make_mock_submission(selftext="")

    result = _fetch_reddit(mock_post)

    assert result[0]["body"] == ""


def test_list_reddit_posts_external_url_for_link_post() -> None:
    """Link posts (is_self=False) populate external_url."""
    mock_post = _make_mock_submission(
        is_self=False,
        url="https://example.com/article"
    )

    result = _fetch_reddit(mock_post)

    assert result[0]["external_url"] == "https://example.com/article"
    assert result[0]["is_self"] is False


# --- Bluesky route tests ---

def test_fetch_bluesky_posts_returns_normalised_posts() -> None:
    """Public Bluesky search results are converted into stored post fields."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "posts": [{
            "uri": "at://did:plc:test/app.bsky.feed.post/abc123",
            "record": {
                "text": "ANZ results look strong.",
                "createdAt": "2026-08-09T01:00:00Z",
                "langs": ["en"],
                "tags": [{"tag": "ASX"}],
            },
            "author": {"handle": "investor.bsky.social", "displayName": "Investor"},
            "replyCount": 2,
            "repostCount": 3,
            "likeCount": 4,
            "quoteCount": 1,
        }],
    }

    with patch("app.services.discussion_sources.bluesky.httpx.get", return_value=mock_response):
        from app.services.discussion_sources.bluesky import BLUESKY
        result = BLUESKY.fetch("ANZ", 1)

    assert len(result) == 1
    assert result[0]["uri"] == "at://did:plc:test/app.bsky.feed.post/abc123"
    assert result[0]["text"] == "ANZ results look strong."
    assert result[0]["author"] == "investor.bsky.social"
    assert result[0]["like_count"] == 4
    assert result[0]["tags"] == ["ASX"]


def test_stored_sentiment_groups_forum_sources_as_public_discussion() -> None:
    """All supported forum sources should share the public discussion category."""
    from app.api.routes.category_sentiment import _categories_for_stored_artifact

    for source_type in ("reddit", "bluesky", "mastodon"):
        artifact = MagicMock(source_type=source_type)
        assert _categories_for_stored_artifact(artifact) == ["user_discussion"]


# --- Mastodon route tests ---

def test_fetch_mastodon_posts_returns_normalised_posts() -> None:
    """Public Mastodon hashtag results are converted into stored post fields."""
    mock_response = MagicMock()
    mock_response.json.return_value = [{
        "id": "114123456789",
        "created_at": "2026-08-10T01:00:00Z",
        "content": "<p>ANZ results look <strong>strong</strong>.</p>",
        "url": "https://aus.social/@investor/114123456789",
        "account": {"acct": "investor", "display_name": "Investor"},
        "replies_count": 2,
        "reblogs_count": 3,
        "favourites_count": 4,
        "language": "en",
        "tags": [{"name": "ASX", "url": "https://aus.social/tags/ASX"}],
        "sensitive": False,
        "spoiler_text": "",
    }]

    with patch("app.services.discussion_sources.mastodon.httpx.get", return_value=mock_response):
        from app.services.discussion_sources.mastodon import MASTODON
        result = MASTODON.fetch("ANZ", 1)

    assert len(result) == 1
    assert result[0]["id"] == "114123456789"
    assert result[0]["text"] == "ANZ results look strong."
    assert result[0]["author"] == "investor"
    assert result[0]["favourites_count"] == 4
    assert result[0]["tags"] == ["ASX"]


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
    ), patch("app.services.sentiment.analyse_text") as analyse_text:
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
    analyse_text.assert_not_called()


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


def test_summary_metadata_clears_stale_speculation_without_mutating_input() -> None:
    """A later summary can replace old clarity classifications with empty lists."""
    from app.api.routes.llm import _summary_metadata

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


def test_legacy_summary_is_not_skipped_during_clarity_backfill() -> None:
    """Ticker-wide backfills should revisit summaries created before clarity v2."""
    from app.api.routes.llm import _has_current_summary

    assert not _has_current_summary({"about": "An existing legacy summary."})
    assert _has_current_summary(
        {
            "about": "A current summary.",
            "confirmed_facts": [],
            "speculation": [],
        }
    )


def test_ticker_overview_exposes_clean_clarity_classifications() -> None:
    """The overview contract should expose classified claims for the summary UI."""
    from datetime import datetime, timezone

    from app.api.routes import ticker as ticker_route

    ticker = MagicMock()
    ticker.id = "ticker-id"
    ticker.symbol = "ANZ"
    ticker.company_name = "ANZ Group Holdings Limited"
    ticker.sector = "Financials"
    ticker.industry = "Banks"
    ticker.exchange = "ASX"

    artifact = MagicMock()
    artifact.artifact_metadata = {
        "about": "ANZ published an update.",
        "confirmed_facts": [
            " Net profit was $1 billion. ",
            "Net profit was $1 billion.",
            None,
        ],
        "speculation": ["Management expects costs to fall."],
    }
    artifact.raw_text = "ANZ published an update."
    artifact.source_type = "asx_announcement"
    artifact.title = "ANZ update"
    artifact.url = "https://example.test/anz-update"
    artifact.published_at = datetime(2040, 1, 2, tzinfo=timezone.utc)
    artifact.created_at = artifact.published_at

    with patch.object(
        ticker_route.crud,
        "get_ticker_by_symbol",
        return_value=ticker,
    ), patch.object(
        ticker_route,
        "_ticker_artifacts",
        return_value=[artifact],
    ), patch.object(
        ticker_route,
        "_latest_sentiment_for_ticker",
        return_value=None,
    ), patch.object(ticker_route, "_live_quote", return_value=None):
        result = ticker_route.get_ticker_brief("anz", db=MagicMock())["overview"]

    assert result["clarity"] == {
        "is_classified": True,
        "confirmed_facts": ["Net profit was $1 billion."],
        "speculation": ["Management expects costs to fall."],
    }


def test_clarity_contract_marks_legacy_metadata_as_unclassified() -> None:
    """Older artifacts must not be presented as verified without classification."""
    from app.api.routes.ticker import _clarity_for_artifact

    artifact = MagicMock()
    artifact.artifact_metadata = {
        "confirmed_facts": "A malformed legacy value.",
    }

    assert _clarity_for_artifact(artifact) == {
        "is_classified": False,
        "confirmed_facts": [],
        "speculation": [],
    }
