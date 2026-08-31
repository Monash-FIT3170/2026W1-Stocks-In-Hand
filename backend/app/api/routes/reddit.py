import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import praw
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from groq import Groq
from sqlalchemy.orm import Session

from app.api.deps import require_admin_investor
from app.core.config import settings
from app.crud import artifact as artifact_crud
from app.crud import information_platform as platform_crud
from app.crud import scrape_run as scrape_run_crud
from app.database.connection import SessionLocal, get_db
from app.models.investor import Investor
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType
from app.schemas.information_platform import InformationPlatformCreate
from app.services import public_discussion as public_discussion_service

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


def _summarise_reddit_posts(ticker_symbol: str, posts: list[dict], source_name: str = "Reddit") -> dict:
    if not posts:
        return {
            "summary": f"No relevant {source_name} posts found.",
            "post_count": 0,
        }

    post_block = ""
    for i, p in enumerate(posts, 1):
        post_block += f"{i}. [{p['score']} upvotes] {p['title']}\n"
        if p["body"]:
            post_block += f"   {p['body'][:300]}\n"
        post_block += "\n"

    prompt = f"""You are a financial analyst reading public discussion posts about ASX-listed company {ticker_symbol}.

Here are the most relevant recent posts from {source_name} (ordered by engagement):

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
        model=settings.GROQ_MODEL,
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


def _get_or_create_reddit_platform(db: Session):
    platform = platform_crud.get_platform_by_name(db, name="Reddit")
    if platform:
        return platform
    return platform_crud.create_platform(
        db,
        InformationPlatformCreate(
            name="Reddit",
            platform_type="social",
            base_url="https://reddit.com",
            scrape_enabled=True,
        ),
    )


def _scrape_and_store_posts(
    subreddit: str = "ASX",
    limit: int = 10,
    scrape_run_id: UUID | None = None,
) -> dict:
    if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
        raise RuntimeError("REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be configured")

    with SessionLocal() as db:
        platform = _get_or_create_reddit_platform(db)

        saved, skipped, mentions_linked, analysis_queued = 0, 0, 0, 0
        for post in _fetch_posts(subreddit, limit):
            chash = _content_hash(post["id"])
            existing = artifact_crud.get_artifact_by_hash(db, chash)
            if existing:
                matches = public_discussion_service.link_artifact_to_tickers(db, existing)
                mentions_linked += len(matches)
                analysis_queued += public_discussion_service.queue_artifact_analysis(
                    db,
                    existing,
                    matches,
                )
                skipped += 1
                continue
            artifact = artifact_crud.create_artifact(
                db=db,
                artifact=ArtifactCreate(
                    source_type=SourceType.REDDIT,
                    platform_id=platform.id,
                    scrape_run_id=scrape_run_id,
                    artifact_type=ArtifactType.REDDIT_POST,
                    title=post["title"],
                    url=post["url"],
                    author=post["author"],
                    raw_text=post["body"],
                    published_at=datetime.fromtimestamp(
                        post["created_utc"],
                        tz=timezone.utc,
                    ),
                    content_hash=chash,
                    artifact_metadata={
                        "reddit_id": post["id"],
                        "score": post["score"],
                        "upvote_ratio": post["upvote_ratio"],
                        "num_comments": post["num_comments"],
                        "flair": post["flair"],
                        "is_self": post["is_self"],
                        "external_url": post["external_url"],
                        "subreddit": post["subreddit"],
                    },
                ),
            )
            matches = public_discussion_service.link_artifact_to_tickers(db, artifact)
            mentions_linked += len(matches)
            analysis_queued += public_discussion_service.queue_artifact_analysis(
                db,
                artifact,
                matches,
            )
            saved += 1

    return {
        "saved": saved,
        "skipped_duplicates": skipped,
        "mentions_linked": mentions_linked,
        "analysis_queued": analysis_queued,
    }


def _run_reddit_scrape(
    subreddit: str,
    limit: int,
    scrape_run_id: UUID | None = None,
) -> None:
    try:
        if scrape_run_id:
            with SessionLocal() as db:
                scrape_run_crud.mark_public_discussion_run_started(db, scrape_run_id)
        result = _scrape_and_store_posts(
            subreddit=subreddit,
            limit=limit,
            scrape_run_id=scrape_run_id,
        )
        if scrape_run_id:
            with SessionLocal() as db:
                scrape_run_crud.mark_public_discussion_run_completed(
                    db,
                    scrape_run_id,
                    items_found=result["saved"] + result["skipped_duplicates"],
                    items_saved=result["saved"],
                )
        print(
            "[REDDIT] Scrape complete "
            f"r/{subreddit}: saved={result['saved']} "
            f"skipped={result['skipped_duplicates']} "
            f"mentions={result['mentions_linked']} "
            f"analysis_queued={result['analysis_queued']}"
        )
    except Exception as exc:  # noqa: BLE001
        if scrape_run_id:
            with SessionLocal() as db:
                scrape_run_crud.mark_public_discussion_run_failed(
                    db,
                    scrape_run_id,
                    error=str(exc),
                )
        print(f"[REDDIT] Scrape failed for r/{subreddit}: {exc}")


@router.post("/scrape")
def scrape_and_store(
    background_tasks: BackgroundTasks,
    subreddit: str = "ASX",
    limit: int = 10,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be configured",
        )
    clean_subreddit = subreddit.strip()
    if not clean_subreddit or not clean_subreddit.replace("_", "").isalnum():
        raise HTTPException(
            status_code=400,
            detail="subreddit must contain only letters, numbers or underscores",
        )
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    platform = _get_or_create_reddit_platform(db)
    source_url = f"https://www.reddit.com/r/{clean_subreddit}"
    run = scrape_run_crud.create_public_discussion_run(
        db,
        platform_id=platform.id,
        source_url=source_url,
        idempotency_key=f"public-discussion:reddit:{uuid4()}",
    )
    background_tasks.add_task(_run_reddit_scrape, clean_subreddit, limit, run.id)
    return {
        "status": "queued",
        "subreddit": clean_subreddit,
        "limit": limit,
        "scrape_run_id": run.id,
    }

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
            "dominant_sentiment": None,
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
