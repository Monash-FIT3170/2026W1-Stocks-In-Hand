"""PyTest tests for the APIs in main.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from unittest.mock import patch, MagicMock


def test_health() -> None:
    """Confirming that the health API returns the "ok" status as expected"""
    assert main.health() == {"status": "ok"}


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


def test_sentiment_pipeline_combines_asx_and_reddit() -> None:
    """POST /sentiment/{ticker} wires ASX categories and Reddit summary together."""
    from app.api.routes import category_sentiment

    captured_categories = {}

    def fake_analyse_categories(categories):
        captured_categories.update(categories)
        return {
            name: {
                "summary": text,
                "sentiment_label": "neutral",
                "label": "neutral",
                "score": 0.5,
                "confidence_score": 0.5,
                "distribution": {"positive": 0.2, "neutral": 0.6, "negative": 0.2},
                "model_used": "test-finbert",
                "chunks_used": 1,
                "chunks_analyzed": 1,
            }
            for name, text in categories.items()
        }

    with patch.object(
        category_sentiment,
        "_categorise_recent_asx",
        return_value={"revenue": "ANZ revenue increased."},
    ), patch.object(
        category_sentiment,
        "_summarise_recent_reddit",
        return_value={
            "summary": "Retail investors are mixed on ANZ.",
            "dominant_sentiment": "mixed",
            "key_themes": ["banks"],
        },
    ), patch.object(
        category_sentiment.sentiment_service,
        "analyse_categories",
        side_effect=fake_analyse_categories,
    ), patch.object(
        category_sentiment.sentiment_service,
        "model_name",
        return_value="test-finbert",
    ):
        result = category_sentiment.analyse_ticker_category_sentiments(
            ticker="anz",
            body=None,
            db=MagicMock(),
        )

    assert result["ticker"] == "ANZ"
    assert result["model_used"] == "test-finbert"
    assert captured_categories["revenue"] == "ANZ revenue increased."
    assert captured_categories["user_discussion"] == "Retail investors are mixed on ANZ."
    assert set(result["categories"]) == {
        "revenue",
        "strategy",
        "risk",
        "dividend",
        "organisational",
        "user_discussion",
    }
    assert result["categories"]["revenue"]["sentiment_label"] == "neutral"


def test_gemini_summary_response_parser_accepts_strict_json() -> None:
    """Gemini summary parsing should return the four fields the UI uses."""
    from app.services.groq import parse_summary_response

    result = parse_summary_response(
        """
        {
          "summary": "The company announced an updated dividend timetable.",
          "about": "The filing explains the dividend key dates.",
          "changed": "The payment date was confirmed.",
          "matters": "Investors can use the dates to plan income expectations."
        }
        """
    )

    assert result == {
        "summary": "The company announced an updated dividend timetable.",
        "about": "The filing explains the dividend key dates.",
        "changed": "The payment date was confirmed.",
        "matters": "Investors can use the dates to plan income expectations.",
    }


def test_gemini_summary_response_parser_rejects_missing_keys() -> None:
    """Incomplete Gemini JSON should fail before storage uses it."""
    import pytest

    from app.services.groq import parse_summary_response

    with pytest.raises(ValueError, match="missing keys"):
        parse_summary_response('{"summary": "Only one field"}')


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
    assert result["summary"] == "The company confirmed its dividend timetable."
    mock_upsert.assert_called_once()
