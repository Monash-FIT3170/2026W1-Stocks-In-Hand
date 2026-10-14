"""Producer for the analysis queue: stored-text analysis and summary requests.

The API never analyses or summarises an artifact itself. It sends a request
to the analysis queue, and the analysis worker does the work through the
artifact analysis module (``lambdas/artifact_analysis.py``). Routes take
the sender as a dependency, ``analysis_sender``, so tests pass their own.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import artifact as artifact_crud
from app.messages import AnalysisRequest, StoredTextAnalysisMessage, SummaryRequestMessage
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.services import artifact_summary
from app.status import ANALYSIS_QUEUED_OR_DONE, AnalysisStatus

AnalysisSender = Callable[[AnalysisRequest], object]

# An artifact in one of these is about to be analysed, which writes a summary.
_ANALYSIS_UNDER_WAY = frozenset({AnalysisStatus.QUEUED, AnalysisStatus.ANALYZING})


class AnalysisQueueUnavailable(RuntimeError):
    """The analysis queue is not configured, or did not accept a request."""


@lru_cache(maxsize=1)
def _sqs_client() -> Any:
    import boto3

    return boto3.client("sqs", region_name=settings.AWS_REGION)


def _require_queue() -> None:
    if not settings.ANALYSIS_QUEUE_URL:
        raise AnalysisQueueUnavailable("ANALYSIS_QUEUE_URL is not configured")


def send_analysis_request(message: AnalysisRequest) -> str:
    """Send one request to the analysis queue and return its SQS message id."""
    _require_queue()
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        response = _sqs_client().send_message(
            QueueUrl=settings.ANALYSIS_QUEUE_URL,
            MessageBody=message.model_dump_json(),
        )
    except (BotoCoreError, ClientError) as exc:
        raise AnalysisQueueUnavailable("The analysis queue did not accept the request") from exc
    return str(response["MessageId"])


def analysis_sender() -> AnalysisSender:
    """The sender routes depend on."""
    return send_analysis_request


def enqueue_stored_artifact_analysis(artifact_id: UUID) -> str:
    """Queue analysis for text already stored in the artifacts table."""
    return send_analysis_request(StoredTextAnalysisMessage(artifact_id=artifact_id))


def queue_stored_text(db: Session, artifact: Any) -> bool:
    """Send an artifact's stored text for analysis once, if the queue is configured.

    Skips an artifact that is already queued, being analysed or analysed,
    and one with no title or text to analyse. Shared by public discussion,
    Marketaux news and the pending-analysis requeue.
    """
    has_text = (artifact.raw_text or "").strip() or (artifact.title or "").strip()
    if (
        artifact.analysis_status in ANALYSIS_QUEUED_OR_DONE
        or not settings.ANALYSIS_QUEUE_URL
        or not has_text
    ):
        return False
    from app.crud import scrape_run as scrape_run_crud

    enqueue_stored_artifact_analysis(artifact.id)
    scrape_run_crud.mark_inline_artifact_analysis_queued(db, artifact.id)
    return True


def request_summary(
    db: Session,
    artifact_id: UUID,
    *,
    send: AnalysisSender,
) -> dict[str, object]:
    """Queue a new summary of one artifact, which replaces its summary.

    Raises ``LookupError`` when the artifact does not exist or has no text,
    and ``AnalysisQueueUnavailable`` when the queue is not configured or
    does not accept the request.
    """
    artifact = artifact_crud.get_artifact(db, artifact_id)
    if artifact is None:
        raise LookupError("Artifact not found")
    if not artifact.raw_text:
        raise LookupError("Artifact has no text to summarise")
    _require_queue()
    send(SummaryRequestMessage(artifact_id=artifact.id))
    return {"artifact_id": artifact.id, "queued": True}


def request_ticker_summaries(
    db: Session,
    symbol: str,
    *,
    limit: int,
    send: AnalysisSender,
) -> dict[str, object]:
    """Queue a new summary of each of a ticker's artifacts without a complete one.

    Reads the ticker's ``limit`` newest announcements and news stories that
    have text. Skips those whose summary is complete, and those whose
    analysis is queued or running, which writes a summary anyway. A request
    the queue does not accept is listed in ``errors``, and the rest are
    still sent.

    Raises ``LookupError`` for an unknown ticker and
    ``AnalysisQueueUnavailable`` when the queue is not configured.
    """
    ticker = db.query(Ticker).filter(func.lower(Ticker.symbol) == symbol.lower()).first()
    if ticker is None:
        raise LookupError(f"Ticker '{symbol}' not found")
    _require_queue()
    artifacts = (
        db.query(Artifact)
        .options(artifact_summary.WITH_SUMMARY)
        .filter(Artifact.ticker_id == ticker.id)
        .filter(Artifact.source_type.in_(["asx_announcement", "news"]))
        .filter(Artifact.raw_text.isnot(None))
        .order_by(Artifact.published_at.desc())
        .limit(limit)
        .all()
    )
    pending = [
        artifact
        for artifact in artifacts
        if artifact.analysis_status not in _ANALYSIS_UNDER_WAY
        and artifact_summary.needs_summary(artifact)
    ]
    queued: list[UUID] = []
    errors: list[dict[str, str]] = []
    for artifact in pending:
        try:
            send(SummaryRequestMessage(artifact_id=artifact.id))
        except AnalysisQueueUnavailable as exc:
            errors.append({"artifact_id": str(artifact.id), "error": str(exc)})
            continue
        queued.append(artifact.id)
    return {
        "ticker": ticker.symbol,
        "candidates": len(artifacts),
        "queued": len(queued),
        "skipped": len(artifacts) - len(pending),
        "artifact_ids": queued,
        "errors": errors,
    }
