"""Database state transitions shared by the scrape API and workers."""

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.information_platform import InformationPlatform
from app.models.scrape_run import ScrapeRun
from app.models.ticker import Ticker
from app.schemas.scrape_run import ScrapeRunCreate
from app.status import AnalysisStatus, DownloadStatus, RUN_DOWNSTREAM_OF_DISCOVERY, ScrapeRunStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _commit(db: Session, value: Any) -> Any:
    db.commit()
    db.refresh(value)
    return value


def get_scrape_run(db: Session, scrape_run_id: UUID) -> ScrapeRun | None:
    return db.query(ScrapeRun).filter(ScrapeRun.id == scrape_run_id).first()


def _lock_run(db: Session, scrape_run_id: UUID) -> ScrapeRun | None:
    """Serialise aggregate counter and status updates for one scrape run."""
    return (
        db.query(ScrapeRun)
        .filter(ScrapeRun.id == scrape_run_id)
        .with_for_update()
        .first()
    )


def get_scrape_runs_by_ticker(db: Session, ticker_id: UUID) -> list[ScrapeRun]:
    return (
        db.query(ScrapeRun)
        .filter(ScrapeRun.ticker_id == ticker_id)
        .order_by(ScrapeRun.created_at.desc())
        .all()
    )


def create_scrape_run(db: Session, scrape_run: ScrapeRunCreate) -> ScrapeRun:
    db_run = ScrapeRun(**scrape_run.model_dump())
    db.add(db_run)
    return _commit(db, db_run)


def create_public_discussion_run(
    db: Session,
    *,
    platform_id: UUID,
    source_url: str,
    idempotency_key: str,
) -> ScrapeRun:
    """Create durable state before a public discussion background task starts."""
    run, _created = get_or_create_public_discussion_run(
        db,
        platform_id=platform_id,
        source_url=source_url,
        idempotency_key=idempotency_key,
    )
    return run


def get_or_create_public_discussion_run(
    db: Session,
    *,
    platform_id: UUID,
    source_url: str,
    idempotency_key: str,
    trigger_type: str = "manual",
) -> tuple[ScrapeRun, bool]:
    """Create one durable public discussion run per idempotency key."""
    existing = (
        db.query(ScrapeRun)
        .filter(ScrapeRun.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        return existing, False

    run = ScrapeRun(
        platform_id=platform_id,
        status="queued",
        source_url=source_url,
        idempotency_key=idempotency_key,
        trigger_type=trigger_type,
        queued_at=_utcnow(),
    )
    db.add(run)
    try:
        return _commit(db, run), True
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(ScrapeRun)
            .filter(ScrapeRun.idempotency_key == idempotency_key)
            .first()
        )
        if existing is None:
            raise
        return existing, False


def mark_public_discussion_run_started(
    db: Session,
    scrape_run_id: UUID,
) -> ScrapeRun | None:
    run = _lock_run(db, scrape_run_id)
    if run is None or run.status in {"completed", "partial"}:
        return run
    run.status = "running"
    run.started_at = run.started_at or _utcnow()
    run.finished_at = None
    run.error_message = None
    return _commit(db, run)


def mark_public_discussion_run_completed(
    db: Session,
    scrape_run_id: UUID,
    *,
    items_found: int,
    items_saved: int,
    items_failed: int = 0,
) -> ScrapeRun | None:
    run = _lock_run(db, scrape_run_id)
    if run is None:
        return None
    run.items_found = max(items_found, 0)
    run.items_saved = max(items_saved, 0)
    run.items_failed = max(items_failed, 0)
    run.status = "partial" if run.items_failed else "completed"
    run.finished_at = _utcnow()
    run.error_message = None
    return _commit(db, run)


def mark_public_discussion_run_failed(
    db: Session,
    scrape_run_id: UUID,
    *,
    error: str,
) -> ScrapeRun | None:
    run = _lock_run(db, scrape_run_id)
    if run is None:
        return None
    run.status = "failed"
    run.finished_at = _utcnow()
    run.error_message = error[:8000]
    return _commit(db, run)


def _get_or_create_platform(db: Session, source_url: str) -> InformationPlatform:
    platform = (
        db.query(InformationPlatform)
        .filter(InformationPlatform.name == "ASX")
        .first()
    )
    if platform:
        return platform
    platform = InformationPlatform(
        name="ASX",
        platform_type="asx_announcements",
        base_url=source_url,
        scrape_enabled=True,
    )
    db.add(platform)
    db.flush()
    return platform


def _get_or_create_ticker(db: Session, ticker: str) -> Ticker:
    row = db.query(Ticker).filter(Ticker.symbol == ticker).first()
    if row:
        return row
    row = Ticker(
        symbol=ticker,
        company_name="CSL Limited" if ticker == "CSL" else ticker,
        exchange="ASX",
    )
    db.add(row)
    db.flush()
    return row


def get_or_create_queued_run(
    db: Session,
    *,
    ticker: str,
    source_url: str,
    idempotency_key: str,
    trigger_type: str = "manual",
) -> tuple[ScrapeRun, bool]:
    """Create Queue A state, or return the run created by the same request."""
    existing = (
        db.query(ScrapeRun)
        .filter(ScrapeRun.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        return existing, False

    platform = _get_or_create_platform(db, source_url)
    ticker_row = _get_or_create_ticker(db, ticker)
    run = ScrapeRun(
        platform_id=platform.id,
        ticker_id=ticker_row.id,
        status=ScrapeRunStatus.ENQUEUEING,
        source_url=source_url,
        idempotency_key=idempotency_key,
        trigger_type=trigger_type,
        queued_at=None,
        items_found=0,
        items_saved=0,
        items_downloaded=0,
        items_analyzed=0,
        items_failed=0,
    )
    db.add(run)
    try:
        return _commit(db, run), True
    except IntegrityError:
        # A concurrent request with the same idempotency key won the race.
        db.rollback()
        existing = (
            db.query(ScrapeRun)
            .filter(ScrapeRun.idempotency_key == idempotency_key)
            .first()
        )
        if existing is None:
            raise
        return existing, False


def mark_run_enqueueing(db: Session, scrape_run_id: UUID) -> ScrapeRun | None:
    """Prepare a failed producer attempt for another Queue A send."""
    run = _lock_run(db, scrape_run_id)
    if run is None:
        return None
    if run.status != ScrapeRunStatus.FAILED:
        return run
    run.status = ScrapeRunStatus.ENQUEUEING
    run.finished_at = None
    run.error_message = None
    return _commit(db, run)


def mark_run_queued_if_enqueueing(
    db: Session,
    scrape_run_id: UUID,
) -> ScrapeRun | None:
    """Record a successful send without regressing a worker that already ran."""
    run = _lock_run(db, scrape_run_id)
    if run is None:
        return None
    if run.status != ScrapeRunStatus.ENQUEUEING:
        return run
    run.status = ScrapeRunStatus.QUEUED
    run.queued_at = _utcnow()
    return _commit(db, run)


def mark_run_discovery_started(db: Session, scrape_run_id: UUID) -> ScrapeRun | None:
    run = _lock_run(db, scrape_run_id)
    if run is None:
        return None
    if run.status in RUN_DOWNSTREAM_OF_DISCOVERY:
        return run
    run.status = ScrapeRunStatus.DISCOVERING
    run.started_at = run.started_at or _utcnow()
    run.finished_at = None
    run.error_message = None
    return _commit(db, run)


def mark_run_discovery_completed(
    db: Session,
    scrape_run_id: UUID,
    *,
    items_found: int,
) -> ScrapeRun | None:
    run = _lock_run(db, scrape_run_id)
    if run is None:
        return None
    run.items_found = max(items_found, run.items_found or 0)
    if run.items_found == 0:
        if run.status not in RUN_DOWNSTREAM_OF_DISCOVERY:
            run.status = ScrapeRunStatus.COMPLETED
            run.finished_at = _utcnow()
    elif run.status not in RUN_DOWNSTREAM_OF_DISCOVERY:
        run.status = ScrapeRunStatus.DOWNLOADING
    _finish_run_if_terminal(run)
    run.error_message = None
    return _commit(db, run)


def mark_run_discovery_failed(
    db: Session,
    scrape_run_id: UUID,
    *,
    error: str,
) -> ScrapeRun | None:
    run = _lock_run(db, scrape_run_id)
    if run is None:
        return None
    if run.status in RUN_DOWNSTREAM_OF_DISCOVERY:
        return run
    run.status = ScrapeRunStatus.FAILED
    run.finished_at = _utcnow()
    run.error_message = error[:8000]
    return _commit(db, run)


def get_or_create_artifact(
    db: Session,
    *,
    scrape_run_id: UUID,
    canonical_url: str,
    document_url: str,
    source_adapter: str = "csl",
    source_id: str | None = None,
    title: str | None = None,
    published_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[Artifact, bool]:
    """Create discovery state once for a source document across all runs."""
    identity_value = (source_id or canonical_url).strip()
    source_document_identity = hashlib.sha256(
        f"v1:{source_adapter}:{identity_value}".encode("utf-8")
    ).hexdigest()
    existing = (
        db.query(Artifact)
        .filter(
            Artifact.source_document_identity == source_document_identity,
        )
        .first()
    )
    if existing:
        return existing, False

    run = get_scrape_run(db, scrape_run_id)
    if run is None:
        raise ValueError(f"Scrape run {scrape_run_id} does not exist")

    artifact = Artifact(
        scrape_run_id=run.id,
        ticker_id=run.ticker_id,
        platform_id=run.platform_id,
        source_type="asx_announcement",
        source_adapter=source_adapter,
        artifact_type="asx_announcement_other",
        source_id=source_id,
        source_document_identity=source_document_identity,
        canonical_url=canonical_url,
        document_url=document_url,
        url=document_url,
        title=title,
        published_at=published_at,
        artifact_metadata=metadata or {},
        download_status=DownloadStatus.PENDING,
        analysis_status=AnalysisStatus.PENDING,
    )
    db.add(artifact)
    try:
        return _commit(db, artifact), True
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(Artifact)
            .filter(
                Artifact.source_document_identity == source_document_identity,
            )
            .first()
        )
        if existing is None:
            raise
        return existing, False


def _lock_artifact(db: Session, artifact_id: UUID) -> Artifact | None:
    return (
        db.query(Artifact)
        .filter(Artifact.id == artifact_id)
        .with_for_update()
        .first()
    )


def _finish_run_if_terminal(run: ScrapeRun) -> None:
    terminal = (run.items_analyzed or 0) + (run.items_failed or 0)
    if (run.items_found or 0) > 0 and terminal >= run.items_found:
        run.finished_at = _utcnow()
        if (run.items_analyzed or 0) == 0:
            run.status = ScrapeRunStatus.FAILED
        elif (run.items_failed or 0) > 0:
            run.status = ScrapeRunStatus.PARTIAL
        else:
            run.status = ScrapeRunStatus.COMPLETED


def mark_artifact_download_started(
    db: Session,
    artifact_id: UUID,
) -> Artifact | None:
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None or artifact.download_status == DownloadStatus.STORED:
        return artifact
    run = _lock_run(db, artifact.scrape_run_id) if artifact.scrape_run_id else None
    if artifact.download_status == DownloadStatus.FAILED and run:
        run.items_failed = max((run.items_failed or 0) - 1, 0)
    artifact.download_status = DownloadStatus.DOWNLOADING
    artifact.last_error = None
    if run and run.status != ScrapeRunStatus.COMPLETED:
        run.status = ScrapeRunStatus.DOWNLOADING
        run.finished_at = None
    return _commit(db, artifact)


def mark_artifact_stored(
    db: Session,
    artifact_id: UUID,
    *,
    checksum_sha256: str,
    s3_bucket: str,
    s3_key: str,
    content_type: str,
    file_size_bytes: int,
) -> Artifact | None:
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None:
        return None
    previous_download_status = artifact.download_status
    first_store = artifact.download_status != DownloadStatus.STORED
    run = (
        _lock_run(db, artifact.scrape_run_id)
        if first_store and artifact.scrape_run_id
        else None
    )
    artifact.download_status = DownloadStatus.STORED
    if artifact.analysis_status == AnalysisStatus.SKIPPED:
        artifact.analysis_status = AnalysisStatus.PENDING
    artifact.checksum_sha256 = checksum_sha256
    artifact.s3_bucket = s3_bucket
    artifact.s3_key = s3_key
    artifact.content_type = content_type
    artifact.file_size_bytes = file_size_bytes
    artifact.downloaded_at = artifact.downloaded_at or _utcnow()
    artifact.last_error = None
    if first_store and run:
        if previous_download_status == DownloadStatus.FAILED:
            run.items_failed = max((run.items_failed or 0) - 1, 0)
        run.items_downloaded = (run.items_downloaded or 0) + 1
        run.items_saved = (run.items_saved or 0) + 1
        run.status = ScrapeRunStatus.ANALYZING
        run.finished_at = None
    return _commit(db, artifact)


def mark_artifact_download_failed(
    db: Session,
    artifact_id: UUID,
    *,
    error: str,
) -> Artifact | None:
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None:
        return None
    if artifact.download_status == DownloadStatus.STORED:
        return artifact
    first_failure = artifact.download_status != DownloadStatus.FAILED
    run = (
        _lock_run(db, artifact.scrape_run_id)
        if first_failure and artifact.scrape_run_id
        else None
    )
    artifact.download_status = DownloadStatus.FAILED
    artifact.analysis_status = AnalysisStatus.SKIPPED
    artifact.last_error = error[:8000]
    if first_failure and run:
        run.items_failed = (run.items_failed or 0) + 1
        _finish_run_if_terminal(run)
    return _commit(db, artifact)


def mark_artifact_analysis_started(
    db: Session,
    artifact_id: UUID,
) -> Artifact | None:
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None or artifact.analysis_status == AnalysisStatus.COMPLETED:
        return artifact
    if artifact.download_status != DownloadStatus.STORED:
        raise ValueError(f"Artifact {artifact_id} has not been stored")
    run = _lock_run(db, artifact.scrape_run_id) if artifact.scrape_run_id else None
    if artifact.analysis_status == AnalysisStatus.FAILED and run:
        run.items_failed = max((run.items_failed or 0) - 1, 0)
    artifact.analysis_status = AnalysisStatus.ANALYZING
    artifact.last_error = None
    if run:
        run.status = ScrapeRunStatus.ANALYZING
        run.finished_at = None
    return _commit(db, artifact)


def mark_artifact_analysis_completed(
    db: Session,
    artifact_id: UUID,
) -> Artifact | None:
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None:
        return None
    first_completion = artifact.analysis_status != AnalysisStatus.COMPLETED
    run = (
        _lock_run(db, artifact.scrape_run_id)
        if first_completion and artifact.scrape_run_id
        else None
    )
    artifact.analysis_status = AnalysisStatus.COMPLETED
    artifact.analyzed_at = artifact.analyzed_at or _utcnow()
    artifact.last_error = None
    if first_completion and run:
        run.items_analyzed = (run.items_analyzed or 0) + 1
        _finish_run_if_terminal(run)
    return _commit(db, artifact)


def mark_artifact_analysis_failed(
    db: Session,
    artifact_id: UUID,
    *,
    error: str,
) -> Artifact | None:
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None:
        return None
    if artifact.analysis_status == AnalysisStatus.COMPLETED:
        return artifact
    first_failure = artifact.analysis_status != AnalysisStatus.FAILED
    run = (
        _lock_run(db, artifact.scrape_run_id)
        if first_failure and artifact.scrape_run_id
        else None
    )
    artifact.analysis_status = AnalysisStatus.FAILED
    artifact.last_error = error[:8000]
    if first_failure and run:
        run.items_failed = (run.items_failed or 0) + 1
        _finish_run_if_terminal(run)
    return _commit(db, artifact)


def mark_inline_artifact_analysis_started(
    db: Session,
    artifact_id: UUID,
) -> Artifact | None:
    """Start stored-text analysis without changing document-run counters."""
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None or artifact.analysis_status == "completed":
        return artifact
    if not (artifact.raw_text or artifact.title):
        raise ValueError(f"Artifact {artifact_id} has no stored text")
    artifact.analysis_status = "analyzing"
    artifact.last_error = None
    return _commit(db, artifact)


def mark_inline_artifact_analysis_queued(
    db: Session,
    artifact_id: UUID,
) -> Artifact | None:
    """Record a successful queue send while keeping retries idempotent."""
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None or artifact.analysis_status in {
        "queued",
        "analyzing",
        "completed",
    }:
        return artifact
    artifact.analysis_status = "queued"
    artifact.last_error = None
    return _commit(db, artifact)


def mark_inline_artifact_analysis_completed(
    db: Session,
    artifact_id: UUID,
) -> Artifact | None:
    """Complete stored-text analysis without reopening its collection run."""
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None:
        return None
    artifact.analysis_status = "completed"
    artifact.analyzed_at = artifact.analyzed_at or _utcnow()
    artifact.last_error = None
    return _commit(db, artifact)


def mark_inline_artifact_analysis_failed(
    db: Session,
    artifact_id: UUID,
    *,
    error: str,
) -> Artifact | None:
    """Fail stored-text analysis without changing collection success state."""
    artifact = _lock_artifact(db, artifact_id)
    if artifact is None or artifact.analysis_status == "completed":
        return artifact
    artifact.analysis_status = "failed"
    artifact.last_error = error[:8000]
    return _commit(db, artifact)
