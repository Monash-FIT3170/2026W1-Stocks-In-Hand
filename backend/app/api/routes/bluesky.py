import hashlib
from datetime import datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.crud import artifact as artifact_crud
from app.crud import information_platform as platform_crud
from app.database.connection import SessionLocal
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType
from app.schemas.information_platform import InformationPlatformCreate

router = APIRouter(prefix="/bluesky", tags=["bluesky"])

BLUESKY_SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"


def _fetch_posts(query: str, limit: int) -> list[dict]:
    response = httpx.get(
        BLUESKY_SEARCH_URL,
        params={"q": query, "limit": limit},
        timeout=15.0,
    )
    response.raise_for_status()

    posts = []
    for post in response.json().get("posts", []):
        record = post.get("record", {})
        author = post.get("author", {})
        posts.append({
            "uri": post.get("uri", ""),
            "text": record.get("text", ""),
            "created_at": record.get("createdAt", ""),
            "author": author.get("handle", "[deleted]"),
            "display_name": author.get("displayName"),
            "reply_count": post.get("replyCount", 0),
            "repost_count": post.get("repostCount", 0),
            "like_count": post.get("likeCount", 0),
            "quote_count": post.get("quoteCount", 0),
            "langs": record.get("langs", []),
            "tags": [tag.get("tag") for tag in record.get("tags", []) if tag.get("tag")],
        })
    return posts


def _content_hash(uri: str) -> str:
    return hashlib.sha256(f"bluesky:{uri}".encode()).hexdigest()


def _get_or_create_bluesky_platform(db: Session):
    platform = platform_crud.get_platform_by_name(db, name="Bluesky")
    if platform:
        return platform
    return platform_crud.create_platform(
        db,
        InformationPlatformCreate(
            name="Bluesky",
            platform_type="social",
            base_url="https://bsky.app",
            scrape_enabled=True,
        ),
    )


def _scrape_and_store_posts(query: str, limit: int) -> dict:
    with SessionLocal() as db:
        platform = _get_or_create_bluesky_platform(db)
        saved, skipped = 0, 0

        for post in _fetch_posts(query, limit):
            if not post["uri"]:
                skipped += 1
                continue

            content_hash = _content_hash(post["uri"])
            if artifact_crud.get_artifact_by_hash(db, content_hash):
                skipped += 1
                continue

            created_at = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
            artifact_crud.create_artifact(
                db=db,
                artifact=ArtifactCreate(
                    source_type=SourceType.BLUESKY,
                    artifact_type=ArtifactType.BLUESKY_POST,
                    platform_id=platform.id,
                    title=post["text"][:200] or "Bluesky post",
                    url=f"https://bsky.app/profile/{post['author']}/post/{post['uri'].rsplit('/', 1)[-1]}",
                    author=post["author"],
                    raw_text=post["text"],
                    published_at=created_at,
                    content_hash=content_hash,
                    artifact_metadata={
                        "bluesky_uri": post["uri"],
                        "display_name": post["display_name"],
                        "reply_count": post["reply_count"],
                        "repost_count": post["repost_count"],
                        "like_count": post["like_count"],
                        "quote_count": post["quote_count"],
                        "langs": post["langs"],
                        "tags": post["tags"],
                        "search_query": query,
                    },
                ),
            )
            saved += 1

    return {"saved": saved, "skipped_duplicates": skipped}


def _run_bluesky_scrape(query: str, limit: int) -> None:
    try:
        result = _scrape_and_store_posts(query, limit)
        print(
            "[BLUESKY] Scrape complete "
            f"query={query}: saved={result['saved']} skipped={result['skipped_duplicates']}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[BLUESKY] Scrape failed for query={query}: {exc}")


@router.post("/scrape")
def scrape_and_store(
    background_tasks: BackgroundTasks,
    query: str = "ASX",
    limit: int = 25,
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")

    background_tasks.add_task(_run_bluesky_scrape, query.strip(), limit)
    return {"status": "queued", "query": query.strip(), "limit": limit}
