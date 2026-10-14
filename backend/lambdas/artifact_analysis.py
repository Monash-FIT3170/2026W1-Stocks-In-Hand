"""Artifact analysis: analyse one artifact and record the result.

An announcement is read from its stored document, or from one the local
loader downloaded, and classified by the rules, which extract its
category's fields; it is stored under the category's artifact type. News
and public discussion are analysed from the text their collector stored and
keep the type their collector set. Either way FinBERT scores the artifact's
title and text, the LLM summarises it with the prompt for its kind, and the
records store the text, the summary and the sentiment and complete the
analysis. A scrape run's announcement with an alertable sentiment is then
sent to alert delivery.

``summarise`` writes a new summary from the stored text and changes nothing
else, and ``repair_missing_summaries`` uses it to complete the summaries of
analysed announcements.

The module reaches outside code only through ``AnalysisPorts``: the
records, whose one adapter is ``PostgresAnalysisRecords``, the sentiment
scorer, the LLM provider, the raw document store and the alert sender.
``deployed_ports`` builds them for the analysis Lambda and ``local_ports``
for the local loader.

A ``PermanentDocumentError`` means a retry cannot help. Any other exception,
including generation's ``RuntimeError`` and ``ValueError``, is worth
retrying, so ``pipeline_stage.run_stage`` still decides between a retry and
a final failure.

The Postgres records and the artifact summary rules are imported where they
are used: importing the database layer creates the engine, and the records
module imports this one.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

import boto3

from app.alert_vocabulary import ALERT_SENTIMENT_LABELS
from app.messages import NotificationMessage
from app.services import generation
from app.services import sentiment as sentiment_service
from app.sources import adapter_matches_ticker
from lambdas.common import PermanentDocumentError, database_session
from lambdas.download_validation import DocumentFormat, DownloadedDocument
from lambdas.raw_documents import (
    DocumentLocation,
    RawDocumentStore,
    StoredDocument,
    raw_document_store,
)
from parsing.analysis import apply_rules, extract_document
from parsing.classification.taxonomy import artifact_type_for
from parsing.classification_metadata import merge_classification_metadata

if TYPE_CHECKING:
    from app.services.generation import Generated, Unavailable
    from app.services.generation.kinds import Kind
    from app.services.generation.providers import TextProvider
    from parsing.classification import ClassificationResult

ArtifactKind = Literal["announcement", "news", "discussion", "other"]
AlertSender = Callable[[NotificationMessage], object]

# The metadata category stored text is recorded under, and the title a
# summary and FinBERT read when the artifact has none.
_STORED_TEXT_CATEGORIES = {"news": "news_article", "discussion": "user_discussion"}
_UNTITLED = {"news": "Untitled news article", "discussion": "Untitled public discussion"}
_UNTITLED_ANNOUNCEMENT = "Untitled ASX announcement"
# The most announcements one summary repair asks Bedrock to summarise.
REPAIR_LIMIT = 20


@dataclass(frozen=True)
class RecordedDocument:
    """The stored copy of a document, as its artifact row records it."""

    bucket: str | None
    key: str | None
    checksum: str | None


@dataclass(frozen=True)
class ArtifactFacts:
    """What analysis reads from one artifact's row."""

    artifact_id: UUID
    kind: ArtifactKind
    source_type: str | None
    source_adapter: str | None
    ticker: str | None
    run_id: UUID | None
    title: str | None
    raw_text: str | None
    artifact_type: str | None
    # An announcement's metadata category and the fields extracted for it.
    category: str | None
    extracted_data: dict[str, Any]
    # The publisher a news story names.
    source_name: str | None
    # A document's file name, from its metadata or the end of its URL.
    filename: str | None
    completed: bool
    # None until the download stage has stored the document.
    document: RecordedDocument | None


@dataclass(frozen=True)
class Sentiment:
    """What the sentiment scorer found in one artifact's title and text."""

    label: str
    stance: str | None
    confidence: float | None
    model: str | None


@dataclass(frozen=True)
class AnalysisResult:
    """Everything one analysis records about its artifact."""

    raw_text: str
    metadata: dict[str, Any]
    # The type an announcement is stored under; None keeps the stored type.
    artifact_type: str | None
    summary: Generated[dict[str, object]] | Unavailable
    sentiment: Sentiment


@dataclass(frozen=True)
class Analysed:
    """An artifact this call analysed and recorded."""

    artifact_id: UUID
    run_id: UUID | None
    source_type: str | None
    source_adapter: str | None
    category: str
    page_count: int
    # The rules' classification of a document; stored text has none.
    classification: ClassificationResult | None
    # False when no LLM is switched on or its answer has no text.
    summarised: bool
    # The type of the error that stopped the alert from being sent.
    alert_error: str | None = None


@dataclass(frozen=True)
class AlreadyAnalysed:
    """An artifact whose analysis had already completed, so nothing was done."""

    artifact_id: UUID
    run_id: UUID | None


@dataclass(frozen=True)
class Summarised:
    """A new summary of an artifact, recorded by this call."""

    artifact_id: UUID
    model: str
    prompt_version: str
    # Whether it has every field a summary of its kind should have.
    complete: bool


@dataclass(frozen=True)
class SummaryUnavailable:
    """No summary was recorded: no LLM is switched on, or its answer has no text."""

    artifact_id: UUID
    reason: str


class SentimentScorer(Protocol):
    def score(self, text: str) -> Sentiment:
        """The sentiment of one text."""


class FinBertScorer:
    """FinBERT, loaded from ``FINBERT_MODEL`` the first time it scores a text."""

    def score(self, text: str) -> Sentiment:
        result = sentiment_service.analyse_text(text)
        return Sentiment(
            label=result["sentiment_label"],
            stance=result.get("label"),
            confidence=result.get("confidence_score"),
            model=result.get("model_used"),
        )


@dataclass
class FixedSentiment:
    """Gives every text the same sentiment and keeps each text, for tests."""

    label: str
    confidence: float = 0.9
    model: str = "fixed-sentiment"
    scored: list[str] = field(default_factory=list)

    def score(self, text: str) -> Sentiment:
        self.scored.append(text)
        return Sentiment(
            label=self.label,
            stance=self.label,
            confidence=self.confidence,
            model=self.model,
        )


class AnalysisRecords(Protocol):
    """Where analysis reads an artifact and records what it found."""

    def facts(self, artifact_id: UUID) -> ArtifactFacts | None:
        """The artifact's facts, or None when it does not exist."""

    def mark_stored(self, artifact_id: UUID, stored: StoredDocument) -> bool:
        """Record the stored copy of the artifact's document.

        Returns False when the artifact does not exist.
        """

    def start(self, artifact_id: UUID) -> None:
        """Record that the artifact's analysis has started."""

    def finish(self, artifact_id: UUID, result: AnalysisResult) -> bool:
        """Record the result and complete the analysis.

        Returns whether a summary was recorded with it.
        """

    def record_summary(
        self,
        artifact_id: UUID,
        generated: Generated[dict[str, object]],
        *,
        complete_only: bool = False,
    ) -> bool:
        """Record a new summary of the artifact, on its own.

        Returns whether the summary has every field its kind should have.
        With ``complete_only`` an incomplete summary is not recorded.
        """

    def missing_summaries(self, limit: int) -> tuple[list[UUID], int]:
        """Analysed announcements whose summary is incomplete, oldest first.

        Returns at most ``limit`` of them and how many there are in all.
        """


@dataclass(frozen=True)
class AnalysisPorts:
    """The outside code an analysis reaches."""

    records: AnalysisRecords
    scorer: SentimentScorer
    # Needed only to analyse a stored document.
    documents: RawDocumentStore | None = None
    # None asks the provider LLM_PROVIDER selects.
    provider: TextProvider | None = None
    # None sends no alerts.
    alerts: AlertSender | None = None


def analyse_stored_document(
    location: DocumentLocation,
    ports: AnalysisPorts,
) -> Analysed | AlreadyAnalysed:
    """Analyse the stored document an S3 notification names.

    The notification is trusted only when it names a scrape run's artifact
    for the same ticker and source adapter, and an object the artifact
    records as its copy. S3 can announce an object before the download stage
    records it, so an artifact with no recorded copy is reconciled from the
    object itself instead of waiting a visibility timeout for the database.

    Raises ``PermanentDocumentError`` with ``unexpected_bucket``,
    ``artifact_not_found`` or ``artifact_identity_mismatch`` when the
    notification cannot be trusted, and with its own code when the document
    cannot be read.
    """
    documents = ports.documents
    if documents is None:
        raise RuntimeError("The raw document store is not configured")
    if location.bucket != documents.name:
        raise PermanentDocumentError(
            "S3 event came from an unexpected bucket",
            code="unexpected_bucket",
        )
    facts = _facts(location.artifact_id, ports)
    if (
        not adapter_matches_ticker(location.ticker, facts.source_adapter or "")
        or facts.ticker != location.ticker
        or facts.run_id is None
    ):
        raise PermanentDocumentError(
            "S3 notification does not identify a supported pipeline artifact",
            code="artifact_identity_mismatch",
        )
    if facts.document is not None:
        if not location.is_recorded_as(
            s3_bucket=facts.document.bucket,
            s3_key=facts.document.key,
            checksum_sha256=facts.document.checksum,
        ):
            raise PermanentDocumentError(
                "S3 notification is stale or does not match the artifact",
                code="artifact_identity_mismatch",
            )
    elif not ports.records.mark_stored(facts.artifact_id, documents.verify(location)):
        raise PermanentDocumentError("Artifact does not exist", code="artifact_not_found")
    if facts.completed:
        return AlreadyAnalysed(artifact_id=facts.artifact_id, run_id=facts.run_id)

    ports.records.start(facts.artifact_id)
    return _analyse_document(
        facts,
        documents.read(location),
        location.document_format,
        ports,
        fallback_filename=location.key.rsplit("/", 1)[-1],
    )


def analyse_downloaded_document(
    artifact_id: UUID,
    document: DownloadedDocument,
    ports: AnalysisPorts,
) -> Analysed | AlreadyAnalysed:
    """Analyse a document the caller downloaded itself, as the local loader does.

    The document is read, classified and recorded exactly as a stored one.
    There is no stored copy to check, and an artifact with no scrape run
    sends no alert. Raises ``PermanentDocumentError`` with
    ``artifact_not_found`` when the artifact does not exist.
    """
    facts = _facts(artifact_id, ports)
    if facts.completed:
        return AlreadyAnalysed(artifact_id=artifact_id, run_id=facts.run_id)

    ports.records.start(artifact_id)
    return _analyse_document(
        facts,
        document.content,
        document.document_format,
        ports,
        fallback_filename=None,
    )


def analyse_stored_text(
    artifact_id: UUID,
    ports: AnalysisPorts,
) -> Analysed | AlreadyAnalysed:
    """Analyse the text a news or public discussion collector stored.

    Raises ``PermanentDocumentError`` with ``artifact_not_found`` when the
    artifact does not exist, ``artifact_identity_mismatch`` when it is not
    news or public discussion, and ``no_extractable_text`` when it has
    neither a title nor text.
    """
    facts = _facts(artifact_id, ports)
    category = _STORED_TEXT_CATEGORIES.get(facts.kind)
    if category is None:
        raise PermanentDocumentError(
            "Artifact is not a supported stored-text source",
            code="artifact_identity_mismatch",
        )
    text = (facts.raw_text or "").strip() or (facts.title or "").strip()
    text = text.replace("\x00", "").strip()
    if not text:
        raise PermanentDocumentError(
            "Stored-text artifact has no text",
            code="no_extractable_text",
        )
    if facts.completed:
        return AlreadyAnalysed(artifact_id=artifact_id, run_id=facts.run_id)

    ports.records.start(artifact_id)
    title = _title(facts)
    result = _analysis(
        ports,
        title=title,
        text=text,
        metadata={"category": category, "category_confidence": 1.0},
        request=_summary_request(facts, title, text),
    )
    return Analysed(
        artifact_id=artifact_id,
        run_id=facts.run_id,
        source_type=facts.source_type,
        source_adapter=facts.source_adapter,
        category=category,
        page_count=1,
        classification=None,
        summarised=ports.records.finish(artifact_id, result),
    )


def summarise(
    artifact_id: UUID,
    ports: AnalysisPorts,
    *,
    complete_only: bool = False,
) -> Summarised | SummaryUnavailable:
    """Summarise an artifact again from its stored text, and record only the summary.

    An announcement is summarised with the category and fields its analysis
    stored. Its sentiment, classification and analysis status are left
    alone. With no LLM switched on, or an answer with no text, nothing is
    recorded and the artifact keeps the summary it has. With
    ``complete_only``, an answer that lacks a field its kind needs is not
    recorded either, and raises ``RuntimeError``.

    Raises ``PermanentDocumentError`` with ``artifact_not_found`` when the
    artifact does not exist and ``no_extractable_text`` when it has no text.
    """
    facts = _facts(artifact_id, ports)
    text = (facts.raw_text or "").strip()
    if not text:
        raise PermanentDocumentError(
            "Artifact has no text to summarise",
            code="no_extractable_text",
        )
    generated = generation.generate(
        _summary_request(
            facts,
            _title(facts),
            text,
            category=facts.category or facts.artifact_type or "UNKNOWN",
            extracted_data=facts.extracted_data,
        ),
        provider=ports.provider,
    )
    if isinstance(generated, generation.Unavailable):
        return SummaryUnavailable(artifact_id=artifact_id, reason=generated.reason)
    if not _has_text(generated):
        # An outcome, not a failure to retry: the repair prompt asks for
        # empty strings when nothing can be recovered.
        return SummaryUnavailable(
            artifact_id=artifact_id,
            reason=f"The answer from {generated.model} has no text",
        )
    complete = ports.records.record_summary(
        artifact_id,
        generated,
        complete_only=complete_only,
    )
    if complete_only and not complete:
        raise RuntimeError("The generated summary omitted structured summary fields")
    return Summarised(
        artifact_id=artifact_id,
        model=generated.model,
        prompt_version=generated.prompt_version,
        complete=complete,
    )


def repair_missing_summaries(
    *,
    apply: bool,
    limit: int,
    ports: AnalysisPorts,
) -> dict[str, object]:
    """Summarise again, through Bedrock, analysed announcements with an incomplete summary.

    At most ``REPAIR_LIMIT`` announcements are selected, oldest first, and a
    dry run only lists them. Applying records each new summary only when it
    is complete and lists each announcement it could not repair, so one
    malformed answer cannot block the batch.
    """
    artifact_ids, missing_before = ports.records.missing_summaries(
        max(min(limit, REPAIR_LIMIT), 1)
    )
    result: dict[str, object] = {
        "apply": apply,
        "selected": len(artifact_ids),
        "missing_before": missing_before,
    }
    if not apply:
        return {
            **result,
            "updated": 0,
            "failed": [],
            "artifact_ids": [str(artifact_id) for artifact_id in artifact_ids],
        }

    provider = ports.provider or generation.providers.configured_provider()
    if not provider.name.startswith("bedrock:"):
        raise RuntimeError("Structured summary repair requires Amazon Bedrock")
    bedrock = replace(ports, provider=provider)
    updated = 0
    failed: list[dict[str, str]] = []
    for artifact_id in artifact_ids:
        try:
            outcome = summarise(artifact_id, bedrock, complete_only=True)
            if isinstance(outcome, SummaryUnavailable):
                raise RuntimeError(outcome.reason)
        # Continue so one malformed model response cannot block the batch.
        except Exception as exc:  # pylint: disable=broad-exception-caught
            failed.append(
                {"artifact_id": str(artifact_id), "error": f"{type(exc).__name__}: {exc}"}
            )
            continue
        updated += 1
    _artifact_ids, missing_after = ports.records.missing_summaries(1)
    return {**result, "updated": updated, "failed": failed, "missing_after": missing_after}


def sqs_alert_sender(queue_url: str, client: Any | None = None) -> AlertSender:
    """An alert sender that puts each message on the notification queue.

    Without a client it reuses one SQS client for the warm Lambda process.
    """

    def send(message: NotificationMessage) -> None:
        if not queue_url:
            raise RuntimeError("Notification queue URL is not configured")
        (client or _sqs_client()).send_message(
            QueueUrl=queue_url,
            MessageBody=message.model_dump_json(),
        )

    return send


def deployed_ports() -> AnalysisPorts:
    """The ports the analysis Lambda runs with, from its environment."""
    # Imported on use: the records module imports this one and the database layer.
    from lambdas.artifact_analysis_records import PostgresAnalysisRecords

    notifications_enabled = os.getenv("NOTIFICATIONS_ENABLED", "false").lower() == "true"
    return AnalysisPorts(
        records=PostgresAnalysisRecords(database_session),
        scorer=FinBertScorer(),
        documents=raw_document_store() if os.getenv("RAW_DOCUMENT_BUCKET") else None,
        alerts=(
            sqs_alert_sender(os.getenv("NOTIFICATION_QUEUE_URL", "").strip())
            if notifications_enabled
            else None
        ),
    )


def local_ports() -> AnalysisPorts:
    """The ports the local loader runs with: no raw document store and no alerts."""
    # Imported on use, as in deployed_ports.
    from lambdas.artifact_analysis_records import PostgresAnalysisRecords

    return AnalysisPorts(
        records=PostgresAnalysisRecords(database_session),
        scorer=FinBertScorer(),
    )


def _facts(artifact_id: UUID, ports: AnalysisPorts) -> ArtifactFacts:
    facts = ports.records.facts(artifact_id)
    if facts is None:
        raise PermanentDocumentError("Artifact does not exist", code="artifact_not_found")
    return facts


def _title(facts: ArtifactFacts) -> str:
    """The artifact's title, or the placeholder its kind is summarised under."""
    return (facts.title or "").strip() or _UNTITLED.get(facts.kind, _UNTITLED_ANNOUNCEMENT)


def _analyse_document(
    facts: ArtifactFacts,
    content: bytes,
    document_format: DocumentFormat,
    ports: AnalysisPorts,
    *,
    fallback_filename: str | None,
) -> Analysed:
    """Read and classify a document, analyse its text, then send its alert."""
    title = _title(facts)
    parsed = apply_rules(
        extract_document(
            content,
            document_format=document_format,
            max_pages=int(os.getenv("MAX_PDF_PAGES", "100")),
            max_ocr_pages=int(os.getenv("MAX_OCR_PAGES", "5")),
            max_ocr_pixels_per_page=int(os.getenv("MAX_OCR_PIXELS_PER_PAGE", "8000000")),
        ),
        title=title,
        filename=facts.filename or fallback_filename,
        source_type=facts.source_type,
        source_adapter=facts.source_adapter,
    )
    metadata = merge_classification_metadata({}, parsed.classification)
    metadata.update(
        {
            "extracted_data": parsed.extracted_data,
            "page_count": parsed.page_count,
            "document_format": document_format,
        }
    )
    result = _analysis(
        ports,
        title=title,
        text=parsed.raw_text,
        metadata=metadata,
        artifact_type=artifact_type_for(parsed.category),
        request=_summary_request(
            facts,
            title,
            parsed.raw_text,
            category=parsed.category,
            extracted_data=parsed.extracted_data,
        ),
    )
    summarised = ports.records.finish(facts.artifact_id, result)
    return Analysed(
        artifact_id=facts.artifact_id,
        run_id=facts.run_id,
        source_type=facts.source_type,
        source_adapter=facts.source_adapter,
        category=parsed.category,
        page_count=parsed.page_count,
        classification=parsed.classification,
        summarised=summarised,
        alert_error=_alert(facts, result.sentiment, ports),
    )


def _summary_request(
    facts: ArtifactFacts,
    title: str,
    text: str,
    *,
    category: str = "UNKNOWN",
    extracted_data: dict[str, Any] | None = None,
) -> Kind[dict[str, object]]:
    """The summary kind for the artifact: the one place it is chosen.

    Only an announcement's summary reads its category and extracted fields.
    """
    if facts.kind == "news":
        return generation.NewsSummary(
            title=title,
            source_name=facts.source_name,
            raw_text=text,
        )
    if facts.kind == "discussion":
        return generation.DiscussionSummary(
            title=title,
            source_type=facts.source_type or "",
            raw_text=text,
        )
    return generation.AnnouncementSummary(
        title=title,
        category=category,
        extracted_data=extracted_data or {},
        raw_text=text,
    )


def _analysis(  # pylint: disable=too-many-arguments
    ports: AnalysisPorts,
    *,
    title: str,
    text: str,
    metadata: dict[str, Any],
    request: Kind[dict[str, object]],
    artifact_type: str | None = None,
) -> AnalysisResult:
    """Score and summarise one artifact's text, in that order.

    FinBERT reads the title and source text, never the summary, so a retry
    or a new summary cannot change the artifact's sentiment.
    """
    sentiment = ports.scorer.score(sentiment_service.sentiment_input(title, text))
    summary = generation.generate(request, provider=ports.provider)
    return AnalysisResult(
        raw_text=text,
        metadata=metadata,
        artifact_type=artifact_type,
        summary=summary,
        sentiment=sentiment,
    )


def _alert(facts: ArtifactFacts, sentiment: Sentiment, ports: AnalysisPorts) -> str | None:
    """Send a scrape run's alertable result to alert delivery.

    A failed send never fails the analysis, which is already recorded. The
    error's type is returned for the Lambda to log, never its text.
    """
    if (
        ports.alerts is None
        or facts.run_id is None
        or sentiment.label not in ALERT_SENTIMENT_LABELS
    ):
        return None
    try:
        ports.alerts(
            NotificationMessage(
                artifact_id=facts.artifact_id,
                ticker=facts.ticker,
                scrape_run_id=facts.run_id,
                sentiment_label=sentiment.label,
                confidence_score=sentiment.confidence,
            )
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return type(exc).__name__
    return None


@lru_cache(maxsize=1)
def _sqs_client() -> Any:
    return boto3.client("sqs")


def _has_text(generated: Generated[dict[str, object]]) -> bool:
    """Whether a summary answer has a text line; one without is never recorded."""
    # Imported on use: importing the database layer creates the engine.
    from app.services import artifact_summary

    return bool(artifact_summary.from_generated(generated).lines)
