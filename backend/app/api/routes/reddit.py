import praw
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.config import settings
from app.database.connection import get_db
from app.schemas.reddit import RedditPostResponse
from app.schemas.artifact import ArtifactCreate, SourceType, ArtifactType
from app.crud import artifact as artifact_crud
from app.crud import information_platform as platform_crud

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

def _content_hash(post_id: str) -> str:
    return hashlib.sha256(f"reddit:{post_id}".encode()).hexdigest()

@router.get("/", response_model=list[RedditPostResponse])
def list_reddit_posts(subreddit: str = "ASX", limit: int = 10):
    return _fetch_posts(subreddit, limit)

@router.post("/scrape")
def scrape_and_store(subreddit: str = "ASX", limit: int = 10, db: Session = Depends(get_db)):
    platform = platform_crud.get_platform_by_name(db, name="Reddit")
    if not platform:
        raise HTTPException(
            status_code=404,
            detail="Seed the Reddit platform first via POST /information-platforms/"
        )

    saved, skipped = 0, 0
    for post in _fetch_posts(subreddit, limit):
        chash = _content_hash(post["id"])
        if artifact_crud.get_artifact_by_hash(db, chash):
            skipped += 1
            continue
        artifact_crud.create_artifact(db=db, artifact=ArtifactCreate(
            source_type=SourceType.REDDIT,
            platform_id=platform.id,
            artifact_type=ArtifactType.REDDIT_POST,

            title=post["title"],
            url=post["url"],
            author=post["author"],
            raw_text=post["body"],
            published_at=datetime.fromtimestamp(post["created_utc"], tz=timezone.utc),
            content_hash=chash,
            artifact_metadata={
                "reddit_id":    post["id"],
                "score":        post["score"],
                "upvote_ratio": post["upvote_ratio"],
                "num_comments": post["num_comments"],
                "flair":        post["flair"],
                "is_self":      post["is_self"],
                "external_url": post["external_url"],
                "subreddit":    post["subreddit"],
            },
        ))
        saved += 1
    return {"saved": saved, "skipped_duplicates": skipped}