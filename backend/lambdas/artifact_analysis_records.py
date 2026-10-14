"""Artifact analysis records on Postgres, the one adapter of the records port.

Each method opens its own short session through ``session_scope``, so no
connection is held while FinBERT or the LLM runs. The analysis Lambda passes
``lambdas.common.database_session``, and tests pass a scope over their own
session. There is no in-memory fake: it would have to copy the scrape run
counters that ``crud.scrape_run`` keeps.

Starting and finishing an analysis picks its transition from the row at the
moment it writes, by the rule ``crud.scrape_run.fail_abandoned_work`` uses:
a stored document moves its scrape run's counters, and any other artifact
is analysed without touching them.

Every summary goes through the artifact summary module. One recorded with
an analysis joins ``crud.artifact.store_artifact_analysis``'s transaction
with the text and sentiment; one recorded on its own commits by itself.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote_plus, urlparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.crud import artifact as artifact_crud
from app.crud import scrape_run as scrape_run_crud
from app.models.artifact import Artifact
from app.services import artifact_summary
from app.services.generation import Generated, Unavailable
from app.services.public_discussion import PUBLIC_DISCUSSION_SOURCE_TYPES
from app.status import AnalysisStatus, DownloadStatus
from lambdas.artifact_analysis import (
    AnalysisResult,
    ArtifactFacts,
    ArtifactKind,
    RecordedDocument,
)
from lambdas.common import PermanentDocumentError
from lambdas.raw_documents import StoredDocument

SessionScope = Callable[[], AbstractContextManager[Session]]


class PostgresAnalysisRecords:
    """Artifact rows with their summary and sentiment rows."""

    def __init__(self, session_scope: SessionScope) -> None:
        self._session_scope = session_scope

    def facts(self, artifact_id: UUID) -> ArtifactFacts | None:
        with self._session_scope() as db:
            artifact = artifact_crud.get_artifact(db, artifact_id)
            return _facts(artifact) if artifact is not None else None

    def mark_stored(self, artifact_id: UUID, stored: StoredDocument) -> bool:
        with self._session_scope() as db:
            recorded = scrape_run_crud.mark_artifact_stored(
                db,
                artifact_id,
                **stored.artifact_fields(),
            )
            return recorded is not None

    def start(self, artifact_id: UUID) -> None:
        with self._session_scope() as db:
            if _is_stored_document(db, artifact_id):
                scrape_run_crud.mark_artifact_analysis_started(db, artifact_id)
            else:
                scrape_run_crud.mark_inline_artifact_analysis_started(db, artifact_id)

    def finish(self, artifact_id: UUID, result: AnalysisResult) -> bool:
        summary = (
            None
            if isinstance(result.summary, Unavailable)
            else artifact_summary.from_generated(result.summary)
        )
        if summary is not None and not summary.lines:
            # An answer with no text is not recorded; the sentiment still is.
            summary = None
        with self._session_scope() as db:
            artifact_crud.store_artifact_analysis(
                db,
                artifact_id=artifact_id,
                raw_text=result.raw_text,
                metadata=result.metadata,
                artifact_type=result.artifact_type,
                summary=summary,
                sentiment={
                    "sentiment_label": result.sentiment.label,
                    "stance": result.sentiment.stance,
                    "confidence_score": result.sentiment.confidence,
                    "model_used": result.sentiment.model,
                },
            )
        with self._session_scope() as db:
            if _is_stored_document(db, artifact_id):
                scrape_run_crud.mark_artifact_analysis_completed(db, artifact_id)
            else:
                scrape_run_crud.mark_inline_artifact_analysis_completed(db, artifact_id)
        return summary is not None

    def record_summary(
        self,
        artifact_id: UUID,
        generated: Generated[dict[str, object]],
        *,
        complete_only: bool = False,
    ) -> bool:
        summary = artifact_summary.from_generated(generated)
        with self._session_scope() as db:
            artifact = artifact_crud.get_artifact(db, artifact_id)
            if artifact is None:
                raise PermanentDocumentError("Artifact does not exist", code="artifact_not_found")
            complete = artifact_summary.is_complete(summary, source_type=artifact.source_type)
            if complete or not complete_only:
                artifact_summary.record(db, artifact, summary)
                db.commit()
        return complete

    def missing_summaries(self, limit: int) -> tuple[list[UUID], int]:
        with self._session_scope() as db:
            return artifact_summary.incomplete_announcements(db, limit=limit)


def _is_stored_document(db: Session, artifact_id: UUID) -> bool:
    status = db.query(Artifact.download_status).filter(Artifact.id == artifact_id).scalar()
    return status == DownloadStatus.STORED


def _kind(artifact: Artifact) -> ArtifactKind:
    source_type = (artifact.source_type or "").lower()
    if source_type == "news" or artifact.artifact_type == "news_article":
        return "news"
    if source_type in PUBLIC_DISCUSSION_SOURCE_TYPES:
        return "discussion"
    if source_type == "asx_announcement":
        return "announcement"
    return "other"


def _filename(artifact: Artifact, metadata: dict[str, Any]) -> str | None:
    filename = metadata.get("filename")
    if isinstance(filename, str) and filename.strip():
        return filename.strip()
    for url in (artifact.document_url, artifact.url):
        name = PurePosixPath(unquote_plus(urlparse(url).path)).name if url else ""
        if name:
            return name
    return None


def _facts(artifact: Artifact) -> ArtifactFacts:
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    category = metadata.get("category")
    extracted_data = metadata.get("extracted_data")
    source_name = metadata.get("source_name") or metadata.get("provider")
    return ArtifactFacts(
        artifact_id=artifact.id,
        kind=_kind(artifact),
        source_type=artifact.source_type,
        source_adapter=artifact.source_adapter,
        ticker=artifact.ticker.symbol if artifact.ticker is not None else None,
        run_id=artifact.scrape_run_id,
        title=artifact.title,
        raw_text=artifact.raw_text,
        artifact_type=artifact.artifact_type,
        category=str(category) if category else None,
        extracted_data=extracted_data if isinstance(extracted_data, dict) else {},
        source_name=source_name if isinstance(source_name, str) else None,
        filename=_filename(artifact, metadata),
        completed=artifact.analysis_status == AnalysisStatus.COMPLETED,
        document=(
            RecordedDocument(
                bucket=artifact.s3_bucket,
                key=artifact.s3_key,
                checksum=artifact.checksum_sha256,
            )
            if artifact.download_status == DownloadStatus.STORED
            else None
        ),
    )
