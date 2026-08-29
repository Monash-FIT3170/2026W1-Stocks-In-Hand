"""Disabled-by-default scheduled collection for bounded public sources."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, cast
from urllib.parse import quote
from uuid import UUID

from lambdas.common import database_session, load_runtime_configuration, log_event

STAGE = "public_discussion_schedule"
MAX_FEEDS = 5
_FINISHED_STATUSES = {"completed", "partial"}


@dataclass(frozen=True)
class CollectorSpec:
    source: str
    target: str
    source_url: str
    platform_factory: Callable[[Any], Any]
    runner: Callable[..., None]
    arguments: tuple[Any, ...]


def _event_key(event: dict) -> str:
    value = event.get("id") or event.get("time")
    if value:
        return str(value)[:200]
    return datetime.now(timezone.utc).date().isoformat()


def _enabled_sources() -> set[str]:
    return {
        source.strip().lower()
        for source in os.getenv(
            "SCHEDULED_PUBLIC_DISCUSSION_SOURCES",
            "bluesky,mastodon",
        ).split(",")
        if source.strip()
    } & {"reddit", "bluesky", "mastodon", "blog"}


def _collection_limit() -> int:
    try:
        configured = int(os.getenv("PUBLIC_DISCUSSION_PER_SOURCE_LIMIT", "10"))
    except ValueError:
        return 10
    return min(max(configured, 1), 25)


def _collector_specs() -> list[CollectorSpec]:
    from app.api.routes import blog, bluesky, mastodon, reddit
    from app.core.config import settings

    enabled = _enabled_sources()
    limit = _collection_limit()
    query = os.getenv("PUBLIC_DISCUSSION_SEARCH_QUERY", "ASX").strip()[:100] or "ASX"
    specs = []
    if (
        "reddit" in enabled
        and settings.REDDIT_CLIENT_ID
        and settings.REDDIT_CLIENT_SECRET
    ):
        specs.append(
            CollectorSpec(
                source="reddit",
                target=query,
                source_url=f"https://www.reddit.com/r/{quote(query)}",
                platform_factory=reddit._get_or_create_reddit_platform,
                runner=reddit._run_reddit_scrape,
                arguments=(query, limit),
            )
        )
    if "bluesky" in enabled:
        specs.append(
            CollectorSpec(
                source="bluesky",
                target=query,
                source_url=(
                    f"{settings.BLUESKY_PUBLIC_API_URL}{bluesky.BLUESKY_SEARCH_PATH}"
                ),
                platform_factory=bluesky._get_or_create_bluesky_platform,
                runner=bluesky._run_bluesky_scrape,
                arguments=(query, limit),
            )
        )
    if "mastodon" in enabled:
        specs.append(
            CollectorSpec(
                source="mastodon",
                target=query,
                source_url=f"{mastodon.MASTODON_BASE_URL}/tags/{quote(query)}",
                platform_factory=mastodon._get_or_create_mastodon_platform,
                runner=mastodon._run_mastodon_scrape,
                arguments=(query, min(limit, 25)),
            )
        )
    if "blog" in enabled:
        for feed_url in settings.PUBLIC_DISCUSSION_FEED_URLS[:MAX_FEEDS]:
            specs.append(
                CollectorSpec(
                    source="blog",
                    target=feed_url,
                    source_url=feed_url,
                    platform_factory=lambda db, url=feed_url: (
                        blog._get_or_create_blog_platform(db, url)
                    ),
                    runner=blog._run_blog_scrape,
                    arguments=(feed_url, limit),
                )
            )
    return specs


def _idempotency_key(spec: CollectorSpec, event_key: str) -> str:
    target_hash = hashlib.sha256(spec.target.encode("utf-8")).hexdigest()[:16]
    return f"public-discussion-schedule:{event_key}:{spec.source}:{target_hash}"


def _run_collector(spec: CollectorSpec, event_key: str) -> str:
    from app.crud import scrape_run as scrape_run_crud

    with database_session() as db:
        platform = spec.platform_factory(db)
        run, created = scrape_run_crud.get_or_create_public_discussion_run(
            db,
            platform_id=platform.id,
            source_url=spec.source_url,
            idempotency_key=_idempotency_key(spec, event_key),
            trigger_type="scheduled",
        )
        if not created and run.status in _FINISHED_STATUSES:
            return "skipped"
        run_id = cast(UUID, run.id)

    spec.runner(*spec.arguments, run_id)

    with database_session() as db:
        run = scrape_run_crud.get_scrape_run(db, run_id)
        if run is None:
            return "failed"
        return "failed" if run.status == "failed" else "completed"


def handler(event: dict, _context) -> dict:
    """Collect each enabled source once for one EventBridge event."""
    started_at = time.monotonic()
    load_runtime_configuration()
    event_key = _event_key(event)
    results = {"completed": 0, "failed": 0, "skipped": 0}
    specs = _collector_specs()

    for spec in specs:
        try:
            outcome = _run_collector(spec, event_key)
        except Exception as exc:  # noqa: BLE001
            outcome = "failed"
            log_event(
                stage=STAGE,
                event="source_failed",
                level=logging.ERROR,
                error_code=type(exc).__name__,
                event_id=event_key,
                source=spec.source,
            )
        results[outcome] += 1

    log_event(
        stage=STAGE,
        event="failed" if results["failed"] else "completed",
        started_at=started_at,
        level=logging.ERROR if results["failed"] else logging.INFO,
        event_id=event_key,
        enabled_sources=sorted(_enabled_sources()),
        collectors=len(specs),
        **results,
    )
    if results["failed"]:
        raise RuntimeError(
            f"{results['failed']} public discussion collectors failed"
        )
    return {"event_id": event_key, "collectors": len(specs), **results}
