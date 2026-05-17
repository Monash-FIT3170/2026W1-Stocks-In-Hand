import praw
import hashlib
import json
from groq import Groq
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
def _get_groq_client() -> Groq:
    return Groq(api_key=settings.GROQ_API_KEY)


def _summarise_reddit_posts(ticker_symbol: str, posts: list[dict]) -> dict:
    if not posts:
        return {
            "summary": "No relevant Reddit posts found.",
            "post_count": 0,
        }

    post_block = ""
    for i, p in enumerate(posts, 1):
        post_block += f"{i}. [{p['score']} upvotes] {p['title']}\n"
        if p["body"]:
            post_block += f"   {p['body'][:300]}\n"
        post_block += "\n"

    prompt = f"""You are a financial analyst reading Reddit posts about ASX-listed company {ticker_symbol}.

Here are the most relevant recent Reddit posts (ordered by upvotes):

{post_block[:12000]}

Write a short 2-3 sentence summary of what retail investors are saying about {ticker_symbol}.
Focus on: overall sentiment, key concerns or excitement, any recurring themes.
Be objective and concise and do not use —. Do not invent facts not present in the posts.

Return JSON only, no explanation:
{{
  "summary": "2-3 sentence summary here",
  "dominant_sentiment": "bullish | bearish | mixed | neutral",
  "key_themes": ["theme1", "theme2"]
}}"""

    response = _get_groq_client().chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    raw = response.choices[0].message.content or ""
    # strip markdown fences Groq sometimes wraps around JSON
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]          # get content between fences
        if clean.startswith("json"):
            clean = clean[4:]                  # strip the "json" language tag
        clean = clean.strip()
    try:
        result = json.loads(clean)
    except json.JSONDecodeError:
        result = {"summary": raw, "dominant_sentiment": "unknown", "key_themes": []}
    return result

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

@router.get("/ticker-sentiment/{ticker_symbol}")
def reddit_ticker_sentiment(
    ticker_symbol: str,
    days: int = 30,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    posts = artifact_crud.get_reddit_posts_for_ticker(
        db=db,
        ticker_symbol=ticker_symbol.upper(),
        days=days,
        limit=limit,
    )

    if not posts:
        return {
            "ticker":             ticker_symbol.upper(),
            "post_count":         0,
            "summary":            "No Reddit posts mentioning this ticker in the last 30 days.",
            "dominant_sentiment": "neutral",
            "key_themes":         [],
            "posts_used":         [],
        }

    post_dicts = [
        {
            "title": a.title or "",
            "body":  a.raw_text or "",
            "score": (a.artifact_metadata or {}).get("score", 0),
            "url":   a.url or "",
        }
        for a in posts
    ]

    result = _summarise_reddit_posts(
        ticker_symbol=ticker_symbol.upper(),
        posts=post_dicts,
    )

    return {
        "ticker":        ticker_symbol.upper(),
        "days_searched": days,
        **result,
        "posts_used": [
            {
                "title": a.title,
                "url":   a.url,
                "score": (a.artifact_metadata or {}).get("score", 0),
            }
            for a in posts
        ],
    }