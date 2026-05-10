import praw
from fastapi import APIRouter
from app.core.config import settings
from app.schemas.reddit import RedditPostResponse

router = APIRouter(prefix="/reddit", tags=["reddit"])

def _get_reddit_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=settings.REDDIT_CLIENT_ID,
        client_secret=settings.REDDIT_CLIENT_SECRET,
        user_agent="ASXResearchBot/1.0",
    )

def _fetch_posts(subreddit_name: str, limit: int) -> list[dict]:
    reddit = _get_reddit_client()
    posts = []
    for s in reddit.subreddit(subreddit_name).hot(limit=limit):
        posts.append({
            "id":           s.id,
            "title":        s.title,
            "body":         s.selftext[:1000] if s.selftext else "",
            "score":        s.score,
            "upvote_ratio": s.upvote_ratio,
            "num_comments": s.num_comments,
            "url":          f"https://reddit.com{s.permalink}",
            "external_url": s.url if not s.is_self else None,
            "author":       str(s.author) if s.author else "[deleted]",
            "flair":        s.link_flair_text,
            "is_self":      s.is_self,
            "created_utc":  s.created_utc,
            "subreddit":    subreddit_name,
        })
    return posts

@router.get("/", response_model=list[RedditPostResponse])
def list_reddit_posts(subreddit: str = "ASX", limit: int = 10):
    return _fetch_posts(subreddit, limit)