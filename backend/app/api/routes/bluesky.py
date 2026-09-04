import hashlib
from datetime import datetime
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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

router = APIRouter(prefix="/bluesky", tags=["bluesky"])

BLUESKY_SEARCH_PATH = "/xrpc/app.bsky.feed.searchPosts"
BLUESKY_SESSION_PATH = "/xrpc/com.atproto.server.createSession"


def _search_request_config() -> tuple[str, dict[str, str]]:
    identifier = settings.BLUESKY_IDENTIFIER.strip()
    app_password = settings.BLUESKY_APP_PASSWORD.strip()
    if bool(identifier) != bool(app_password):
        raise RuntimeError(
            "BLUESKY_IDENTIFIER and BLUESKY_APP_PASSWORD must be configured together"
        )
    if not identifier:
        return f"{settings.BLUESKY_PUBLIC_API_URL}{BLUESKY_SEARCH_PATH}", {}

    response = httpx.post(
        f"{settings.BLUESKY_SERVICE_URL}{BLUESKY_SESSION_PATH}",
        json={"identifier": identifier, "password": app_password},
        timeout=15.0,
    )
    response.raise_for_status()
    access_token = response.json().get("accessJwt")
    if not access_token:
        raise RuntimeError("Bluesky session response did not include an access token")
    return (
        f"{settings.BLUESKY_SERVICE_URL}{BLUESKY_SEARCH_PATH}",
        {"Authorization": f"Bearer {access_token}"},
    )


def _fetch_posts(query: str, limit: int) -> list[dict]:
    search_url, headers = _search_request_config()
    response = httpx.get(
        search_url,
        params={"q": query, "limit": limit},
        headers=headers,
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


def _scrape_and_store_posts(
    query: str,
    limit: int,
    scrape_run_id: UUID | None = None,
) -> dict:
    with SessionLocal() as db:
        platform = _get_or_create_bluesky_platform(db)
        saved, skipped, mentions_linked, analysis_queued = 0, 0, 0, 0

        for post in _fetch_posts(query, limit):
            if not post["uri"]:
                skipped += 1
                continue

            content_hash = _content_hash(post["uri"])
            existing = artifact_crud.get_artifact_by_hash(db, content_hash)
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

            created_at = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
            artifact = artifact_crud.create_artifact(
                db=db,
                artifact=ArtifactCreate(
                    source_type=SourceType.BLUESKY,
                    artifact_type=ArtifactType.BLUESKY_POST,
                    platform_id=platform.id,
                    scrape_run_id=scrape_run_id,
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


def _run_bluesky_scrape(
    query: str,
    limit: int,
    scrape_run_id: UUID | None = None,
) -> None:
    try:
        if scrape_run_id:
            with SessionLocal() as db:
                scrape_run_crud.mark_public_discussion_run_started(db, scrape_run_id)
        result = _scrape_and_store_posts(query, limit, scrape_run_id)
        if scrape_run_id:
            with SessionLocal() as db:
                scrape_run_crud.mark_public_discussion_run_completed(
                    db,
                    scrape_run_id,
                    items_found=result["saved"] + result["skipped_duplicates"],
                    items_saved=result["saved"],
                )
        print(
            "[BLUESKY] Scrape complete "
            f"query={query}: saved={result['saved']} "
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
        print(f"[BLUESKY] Scrape failed for query={query}: {exc}")


@router.post("/scrape")
def scrape_and_store(
    background_tasks: BackgroundTasks,
    query: str = "ASX",
    limit: int = 25,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")

    clean_query = query.strip()
    platform = _get_or_create_bluesky_platform(db)
    run = scrape_run_crud.create_public_discussion_run(
        db,
        platform_id=platform.id,
        source_url=f"{settings.BLUESKY_PUBLIC_API_URL}{BLUESKY_SEARCH_PATH}",
        idempotency_key=f"public-discussion:bluesky:{uuid4()}",
    )
    background_tasks.add_task(_run_bluesky_scrape, clean_query, limit, run.id)
    return {
        "status": "queued",
        "query": clean_query,
        "limit": limit,
        "scrape_run_id": run.id,
    }
