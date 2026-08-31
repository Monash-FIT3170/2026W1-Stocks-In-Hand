import hashlib
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin_investor
from app.crud import artifact as artifact_crud
from app.crud import information_platform as platform_crud
from app.crud import scrape_run as scrape_run_crud
from app.database.connection import SessionLocal, get_db
from app.models.investor import Investor
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType
from app.schemas.information_platform import InformationPlatformCreate
from app.services import public_discussion as public_discussion_service

router = APIRouter(prefix="/mastodon", tags=["mastodon"])

MASTODON_BASE_URL = "https://aus.social"


class _PostTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _strip_html(content: str) -> str:
    parser = _PostTextParser()
    parser.feed(content)
    return " ".join("".join(parser.parts).split())


def _fetch_posts(tag: str, limit: int) -> list[dict]:
    response = httpx.get(
        f"{MASTODON_BASE_URL}/api/v1/timelines/tag/{quote(tag)}",
        params={"limit": limit},
        timeout=15.0,
    )
    response.raise_for_status()

    posts = []
    for item in response.json():
        status = item.get("reblog") or item
        account = status.get("account", {})
        posts.append({
            "id": status.get("id", ""),
            "text": _strip_html(status.get("content", "")),
            "created_at": status.get("created_at", ""),
            "url": status.get("url", ""),
            "author": account.get("acct") or account.get("username") or "[deleted]",
            "display_name": account.get("display_name"),
            "replies_count": status.get("replies_count", 0),
            "reblogs_count": status.get("reblogs_count", 0),
            "favourites_count": status.get("favourites_count", 0),
            "language": status.get("language"),
            "tags": [entry.get("name") for entry in status.get("tags", []) if entry.get("name")],
            "sensitive": status.get("sensitive", False),
            "spoiler_text": status.get("spoiler_text", ""),
        })
    return posts


def _content_hash(url: str, post_id: str) -> str:
    identifier = url or f"{MASTODON_BASE_URL}:{post_id}"
    return hashlib.sha256(f"mastodon:{identifier}".encode()).hexdigest()


def _get_or_create_mastodon_platform(db: Session):
    platform = platform_crud.get_platform_by_name(db, name="Mastodon")
    if platform:
        return platform
    return platform_crud.create_platform(
        db,
        InformationPlatformCreate(
            name="Mastodon",
            platform_type="social",
            base_url=MASTODON_BASE_URL,
            scrape_enabled=True,
        ),
    )


def _scrape_and_store_posts(
    tag: str,
    limit: int,
    scrape_run_id: UUID | None = None,
) -> dict:
    with SessionLocal() as db:
        platform = _get_or_create_mastodon_platform(db)
        saved, skipped, mentions_linked, analysis_queued = 0, 0, 0, 0

        for post in _fetch_posts(tag, limit):
            if not post["id"] or not post["created_at"]:
                skipped += 1
                continue

            content_hash = _content_hash(post["url"], post["id"])
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

            published_at = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
            artifact = artifact_crud.create_artifact(
                db=db,
                artifact=ArtifactCreate(
                    source_type=SourceType.MASTODON,
                    artifact_type=ArtifactType.MASTODON_POST,
                    platform_id=platform.id,
                    scrape_run_id=scrape_run_id,
                    title=post["text"][:200] or "Mastodon post",
                    url=post["url"] or f"{MASTODON_BASE_URL}/@{post['author']}/{post['id']}",
                    author=post["author"],
                    raw_text=post["text"],
                    published_at=published_at,
                    content_hash=content_hash,
                    artifact_metadata={
                        "mastodon_id": post["id"],
                        "display_name": post["display_name"],
                        "replies_count": post["replies_count"],
                        "reblogs_count": post["reblogs_count"],
                        "favourites_count": post["favourites_count"],
                        "language": post["language"],
                        "tags": post["tags"],
                        "sensitive": post["sensitive"],
                        "spoiler_text": post["spoiler_text"],
                        "search_tag": tag,
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


def _run_mastodon_scrape(
    tag: str,
    limit: int,
    scrape_run_id: UUID | None = None,
) -> None:
    try:
        if scrape_run_id:
            with SessionLocal() as db:
                scrape_run_crud.mark_public_discussion_run_started(db, scrape_run_id)
        result = _scrape_and_store_posts(tag, limit, scrape_run_id)
        if scrape_run_id:
            with SessionLocal() as db:
                scrape_run_crud.mark_public_discussion_run_completed(
                    db,
                    scrape_run_id,
                    items_found=result["saved"] + result["skipped_duplicates"],
                    items_saved=result["saved"],
                )
        print(
            "[MASTODON] Scrape complete "
            f"tag=#{tag}: saved={result['saved']} "
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
        print(f"[MASTODON] Scrape failed for tag=#{tag}: {exc}")


@router.post("/scrape")
def scrape_and_store(
    background_tasks: BackgroundTasks,
    tag: str = "ASX",
    limit: int = 25,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    clean_tag = tag.strip().lstrip("#")
    if not clean_tag:
        raise HTTPException(status_code=400, detail="tag must not be empty")
    if not clean_tag.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="tag must contain only letters, numbers or underscores")
    if not 1 <= limit <= 40:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 40")

    platform = _get_or_create_mastodon_platform(db)
    run = scrape_run_crud.create_public_discussion_run(
        db,
        platform_id=platform.id,
        source_url=f"{MASTODON_BASE_URL}/tags/{quote(clean_tag)}",
        idempotency_key=f"public-discussion:mastodon:{uuid4()}",
    )
    background_tasks.add_task(_run_mastodon_scrape, clean_tag, limit, run.id)
    return {
        "status": "queued",
        "tag": clean_tag,
        "limit": limit,
        "scrape_run_id": run.id,
    }
