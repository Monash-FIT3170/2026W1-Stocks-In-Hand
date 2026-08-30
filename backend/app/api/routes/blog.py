import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlparse
from uuid import UUID, uuid4
from xml.etree import ElementTree

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

router = APIRouter(prefix="/blogs", tags=["blogs"])

MAX_FEED_BYTES = 2_000_000


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _strip_html(value: str) -> str:
    parser = _TextParser()
    parser.feed(value)
    return " ".join("".join(parser.parts).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(element, *names: str):
    wanted = {name.lower() for name in names}
    return next(
        (child for child in element if _local_name(child.tag) in wanted),
        None,
    )


def _child_text(element, *names: str) -> str:
    child = _child(element, *names)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def _parse_date(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _atom_url(entry) -> str:
    links = [child for child in entry if _local_name(child.tag) == "link"]
    alternate = next(
        (link for link in links if link.get("rel", "alternate") == "alternate"),
        None,
    )
    selected = alternate if alternate is not None else (links[0] if links else None)
    return selected.get("href", "") if selected is not None else ""


def _parse_feed(content: bytes, *, limit: int) -> list[dict]:
    upper_content = content.upper()
    if b"<!DOCTYPE" in upper_content or b"<!ENTITY" in upper_content:
        raise ValueError("Feed XML declarations are not allowed")
    root = ElementTree.fromstring(content)
    root_name = _local_name(root.tag)
    if root_name == "rss":
        channel = _child(root, "channel")
        entries = [] if channel is None else [
            child for child in channel if _local_name(child.tag) == "item"
        ]
        return [
            {
                "id": _child_text(entry, "guid") or _child_text(entry, "link"),
                "title": _strip_html(_child_text(entry, "title")),
                "url": _child_text(entry, "link"),
                "author": _child_text(entry, "author", "creator") or None,
                "raw_text": _strip_html(
                    _child_text(entry, "encoded", "description", "content")
                ),
                "published_at": _parse_date(
                    _child_text(entry, "pubdate", "published", "updated")
                ),
            }
            for entry in entries[:limit]
        ]
    if root_name == "feed":
        entries = [child for child in root if _local_name(child.tag) == "entry"]
        return [
            {
                "id": _child_text(entry, "id") or _atom_url(entry),
                "title": _strip_html(_child_text(entry, "title")),
                "url": _atom_url(entry),
                "author": _child_text(_child(entry, "author"), "name")
                if _child(entry, "author") is not None
                else None,
                "raw_text": _strip_html(_child_text(entry, "content", "summary")),
                "published_at": _parse_date(
                    _child_text(entry, "published", "updated")
                ),
            }
            for entry in entries[:limit]
        ]
    raise ValueError("Feed must use RSS 2.0 or Atom format")


def _fetch_posts(feed_url: str, limit: int) -> list[dict]:
    response = httpx.get(
        feed_url,
        timeout=15.0,
        follow_redirects=False,
        headers={"Accept": "application/rss+xml, application/atom+xml, application/xml"},
    )
    response.raise_for_status()
    if len(response.content) > MAX_FEED_BYTES:
        raise ValueError("Feed exceeds the 2 MB size limit")
    return _parse_feed(response.content, limit=limit)


def _content_hash(feed_url: str, source_id: str) -> str:
    return hashlib.sha256(f"blog:{feed_url}:{source_id}".encode()).hexdigest()


def _platform_name(feed_url: str) -> str:
    return f"Blog: {urlparse(feed_url).hostname or 'feed'}"


def _get_or_create_blog_platform(db: Session, feed_url: str):
    name = _platform_name(feed_url)
    platform = platform_crud.get_platform_by_name(db, name=name)
    if platform:
        return platform
    return platform_crud.create_platform(
        db,
        InformationPlatformCreate(
            name=name,
            platform_type="blog",
            base_url=feed_url,
            scrape_enabled=True,
        ),
    )


def _scrape_and_store_posts(
    feed_url: str,
    limit: int,
    scrape_run_id: UUID | None = None,
) -> dict:
    with SessionLocal() as db:
        platform = _get_or_create_blog_platform(db, feed_url)
        posts = _fetch_posts(feed_url, limit)
        saved, skipped, failed, mentions_linked, analysis_queued = 0, 0, 0, 0, 0
        for post in posts:
            source_id = post["id"] or post["url"]
            if not source_id or not post["url"]:
                failed += 1
                continue
            content_hash = _content_hash(feed_url, source_id)
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
            artifact = artifact_crud.create_artifact(
                db=db,
                artifact=ArtifactCreate(
                    source_type=SourceType.BLOG,
                    artifact_type=ArtifactType.BLOG_POST,
                    platform_id=platform.id,
                    scrape_run_id=scrape_run_id,
                    source_adapter="rss_atom",
                    source_id=source_id,
                    canonical_url=post["url"],
                    title=post["title"] or "Blog post",
                    url=post["url"],
                    author=post["author"],
                    raw_text=post["raw_text"],
                    published_at=post["published_at"],
                    content_hash=content_hash,
                    artifact_metadata={"feed_url": feed_url},
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
        "found": len(posts),
        "saved": saved,
        "skipped_duplicates": skipped,
        "failed": failed,
        "mentions_linked": mentions_linked,
        "analysis_queued": analysis_queued,
    }


def _run_blog_scrape(feed_url: str, limit: int, scrape_run_id: UUID) -> None:
    try:
        with SessionLocal() as db:
            scrape_run_crud.mark_public_discussion_run_started(db, scrape_run_id)
        result = _scrape_and_store_posts(feed_url, limit, scrape_run_id)
        with SessionLocal() as db:
            scrape_run_crud.mark_public_discussion_run_completed(
                db,
                scrape_run_id,
                items_found=result["found"],
                items_saved=result["saved"],
                items_failed=result["failed"],
            )
    except Exception as exc:  # noqa: BLE001
        with SessionLocal() as db:
            scrape_run_crud.mark_public_discussion_run_failed(
                db,
                scrape_run_id,
                error=str(exc),
            )


@router.post("/scrape")
def scrape_and_store(
    background_tasks: BackgroundTasks,
    feed_url: str,
    limit: int = 25,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    if feed_url not in settings.PUBLIC_DISCUSSION_FEED_URLS:
        raise HTTPException(status_code=400, detail="feed_url is not in the configured allowlist")
    if urlparse(feed_url).scheme != "https":
        raise HTTPException(status_code=400, detail="feed_url must use HTTPS")
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")

    platform = _get_or_create_blog_platform(db, feed_url)
    run = scrape_run_crud.create_public_discussion_run(
        db,
        platform_id=platform.id,
        source_url=feed_url,
        idempotency_key=f"public-discussion:blog:{uuid4()}",
    )
    background_tasks.add_task(_run_blog_scrape, feed_url, limit, run.id)
    return {
        "status": "queued",
        "feed_url": feed_url,
        "limit": limit,
        "scrape_run_id": run.id,
    }
