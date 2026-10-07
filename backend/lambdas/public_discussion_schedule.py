"""Disabled-by-default scheduled collection for bounded public sources."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.status import ScrapeRunStatus
from lambdas.common import database_session, load_runtime_configuration, log_event

STAGE = "public_discussion_schedule"
MAX_FEEDS = 5
_FINISHED_STATUSES = {ScrapeRunStatus.COMPLETED, ScrapeRunStatus.PARTIAL}


@dataclass(frozen=True)
class Collection:
    """One source and target the schedule collects for each event."""

    source: Any
    target: str
    limit: int


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


def _collections() -> list[Collection]:
    """The enabled collections. Each source validates its target when collected."""
    # Imported after load_runtime_configuration so settings sees the SSM values.
    from app.core.config import settings
    from app.services.discussion_sources.blog import BLOG
    from app.services.discussion_sources.bluesky import BLUESKY
    from app.services.discussion_sources.mastodon import MASTODON
    from app.services.discussion_sources.reddit import REDDIT

    enabled = _enabled_sources()
    limit = _collection_limit()
    query = os.getenv("PUBLIC_DISCUSSION_SEARCH_QUERY", "ASX").strip()[:100] or "ASX"
    wanted: list[tuple[Any, str]] = []
    if "reddit" in enabled and REDDIT.configured():
        wanted.append((REDDIT, query))
    if "bluesky" in enabled:
        wanted.append((BLUESKY, query))
    if "mastodon" in enabled:
        wanted.append((MASTODON, query))
    if "blog" in enabled:
        wanted.extend(
            (BLOG, feed_url) for feed_url in settings.PUBLIC_DISCUSSION_FEED_URLS[:MAX_FEEDS]
        )
    return [Collection(source=source, target=target, limit=limit) for source, target in wanted]


def _idempotency_key(source_type: str, target: str, event_key: str) -> str:
    target_hash = hashlib.sha256(target.encode("utf-8")).hexdigest()[:16]
    return f"public-discussion-schedule:{event_key}:{source_type}:{target_hash}"


def _collect(collection: Collection, event_key: str) -> str:
    from app.services import discussion_collector

    source = collection.source
    target = source.target(collection.target, collection.limit)
    with database_session() as db:
        run, created = discussion_collector.request_collection(
            db,
            source,
            target,
            idempotency_key=_idempotency_key(source.source_type, target, event_key),
            trigger_type="scheduled",
        )
        if not created and run.status in _FINISHED_STATUSES:
            return "skipped"
        run_id = run.id

    result = discussion_collector.collect(
        source,
        target,
        collection.limit,
        session_scope=database_session,
        run_id=run_id,
    )
    return "failed" if result.status == ScrapeRunStatus.FAILED else "completed"


def handler(event: dict, _context) -> dict:
    """Collect each enabled source once for one EventBridge event."""
    started_at = time.monotonic()
    load_runtime_configuration()
    event_key = _event_key(event)
    results = {"completed": 0, "failed": 0, "skipped": 0}
    collections = _collections()

    for collection in collections:
        try:
            outcome = _collect(collection, event_key)
        except Exception as exc:  # noqa: BLE001
            outcome = "failed"
            log_event(
                stage=STAGE,
                event="source_failed",
                level=logging.ERROR,
                error_code=type(exc).__name__,
                event_id=event_key,
                source=collection.source.source_type,
            )
        results[outcome] += 1

    log_event(
        stage=STAGE,
        event="failed" if results["failed"] else "completed",
        started_at=started_at,
        level=logging.ERROR if results["failed"] else logging.INFO,
        event_id=event_key,
        enabled_sources=sorted(_enabled_sources()),
        collectors=len(collections),
        **results,
    )
    if results["failed"]:
        raise RuntimeError(
            f"{results['failed']} public discussion collectors failed"
        )
    return {"event_id": event_key, "collectors": len(collections), **results}
