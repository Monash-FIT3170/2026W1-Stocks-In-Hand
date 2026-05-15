"""PyTest tests for the APIs in main.py"""
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
        from app.api.routes.reddit import list_reddit_posts
        result = list_reddit_posts(subreddit="ASX", limit=1)

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
        from app.api.routes.reddit import list_reddit_posts
        result = list_reddit_posts(subreddit="ASX", limit=1)

    assert len(result[0]["body"]) == 1000


def test_list_reddit_posts_empty_body() -> None:
    """Posts with no body text return an empty string."""
    mock_post = _make_mock_submission(selftext="")

    with patch("app.api.routes.reddit._get_reddit_client") as mock_client:
        mock_client.return_value.subreddit.return_value.hot.return_value = [mock_post]
        from app.api.routes.reddit import list_reddit_posts
        result = list_reddit_posts(subreddit="ASX", limit=1)

    assert result[0]["body"] == ""


def test_list_reddit_posts_external_url_for_link_post() -> None:
    """Link posts (is_self=False) populate external_url."""
    mock_post = _make_mock_submission(
        is_self=False,
        url="https://example.com/article"
    )

    with patch("app.api.routes.reddit._get_reddit_client") as mock_client:
        mock_client.return_value.subreddit.return_value.hot.return_value = [mock_post]
        from app.api.routes.reddit import list_reddit_posts
        result = list_reddit_posts(subreddit="ASX", limit=1)

    assert result[0]["external_url"] == "https://example.com/article"
    assert result[0]["is_self"] is False