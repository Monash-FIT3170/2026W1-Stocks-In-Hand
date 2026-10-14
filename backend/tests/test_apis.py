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
