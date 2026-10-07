"""Collect public discussion from one source into stored artifacts.

The routes and the scheduled collector both request a collection run and
then ``collect`` it. The source adapter fetches and normalises posts; the
collector owns everything else: de-duplication by content hash, ticker
linking, queueing stored text for analysis, failure counting and the run
lifecycle. A post the source cannot read (``MalformedPostError``) counts as
a failed item, so its run ends partial instead of completed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.crud import artifact as artifact_crud
from app.crud import information_platform as platform_crud
from app.crud import scrape_run as scrape_run_crud
from app.models.information_platform import InformationPlatform
from app.models.scrape_run import ScrapeRun
from app.schemas.information_platform import InformationPlatformCreate
from app.services import public_discussion as public_discussion_service
from app.services.discussion_sources.base import DiscussionSource, MalformedPostError
from app.status import ScrapeRunStatus

LOGGER = logging.getLogger(__name__)
SessionScope = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class CollectionResult:
    status: ScrapeRunStatus
    found: int = 0
    saved: int = 0
    skipped_duplicates: int = 0
    failed: int = 0
    mentions_linked: int = 0
    analysis_queued: int = 0
    error: str | None = None


def platform_for(db: Session, source: DiscussionSource, target: str) -> InformationPlatform:
    spec = source.platform(target)
    platform = platform_crud.get_platform_by_name(db, name=spec.name)
    if platform:
        return platform
    return platform_crud.create_platform(
        db,
        InformationPlatformCreate(
            name=spec.name,
            platform_type=spec.platform_type,
            base_url=spec.base_url,
            scrape_enabled=True,
        ),
    )


def request_collection(
    db: Session,
    source: DiscussionSource,
    target: str,
    *,
    idempotency_key: str,
    trigger_type: str = "manual",
) -> tuple[ScrapeRun, bool]:
    """Record a queued collection run for a validated target."""
    platform = platform_for(db, source, target)
    return scrape_run_crud.get_or_create_public_discussion_run(
        db,
        platform_id=platform.id,
        source_url=source.source_url(target),
        idempotency_key=idempotency_key,
        trigger_type=trigger_type,
    )


def collect(
    source: DiscussionSource,
    target: str,
    limit: int,
    *,
    session_scope: SessionScope,
    run_id: UUID | None = None,
) -> CollectionResult:
    """Fetch, store, link and queue one target's posts, recording the run.

    Never raises: a failed collection is recorded on its run and returned.
    """
    try:
        if run_id:
            with session_scope() as db:
                scrape_run_crud.mark_public_discussion_run_started(db, run_id)
        result = _store(source, target, limit, session_scope=session_scope, run_id=run_id)
        if run_id:
            with session_scope() as db:
                scrape_run_crud.mark_public_discussion_run_completed(
                    db,
                    run_id,
                    items_found=result.found,
                    items_saved=result.saved,
                    items_failed=result.failed,
                )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("%s collection for %s failed: %s", source.source_type, target, exc)
        if run_id:
            with session_scope() as db:
                scrape_run_crud.mark_public_discussion_run_failed(db, run_id, error=str(exc))
        return CollectionResult(status=ScrapeRunStatus.FAILED, error=str(exc))
    LOGGER.info(
        "%s collection for %s: %s",
        source.source_type,
        target,
        result,
    )
    return result


def _store(
    source: DiscussionSource,
    target: str,
    limit: int,
    *,
    session_scope: SessionScope,
    run_id: UUID | None,
) -> CollectionResult:
    fetched = source.fetch(target, limit)
    saved = skipped = failed = mentions = queued = 0
    with session_scope() as db:
        platform = platform_for(db, source, target)
        for raw in fetched:
            try:
                post = source.post(raw, target)
            except MalformedPostError as exc:
                LOGGER.info("%s skipped a malformed post: %s", source.source_type, exc)
                failed += 1
                continue
            artifact = artifact_crud.get_artifact_by_hash(db, post.content_hash)
            if artifact is None:
                artifact = artifact_crud.create_artifact(
                    db=db,
                    artifact=post.artifact.model_copy(
                        update={"platform_id": platform.id, "scrape_run_id": run_id}
                    ),
                )
                saved += 1
            else:
                skipped += 1
            matches = public_discussion_service.link_artifact_to_tickers(db, artifact)
            mentions += len(matches)
            queued += public_discussion_service.queue_artifact_analysis(db, artifact, matches)
    return CollectionResult(
        status=ScrapeRunStatus.PARTIAL if failed else ScrapeRunStatus.COMPLETED,
        found=len(fetched),
        saved=saved,
        skipped_duplicates=skipped,
        failed=failed,
        mentions_linked=mentions,
        analysis_queued=queued,
    )
