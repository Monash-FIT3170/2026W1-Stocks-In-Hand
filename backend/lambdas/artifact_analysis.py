"""Artifact analysis: analyse one artifact and record the result.

News and public discussion are analysed from the text their collector
stored. FinBERT scores the artifact's title and text, the LLM summarises it
with the prompt for its kind, and the records store the text, the summary
and the sentiment and complete the analysis.

The module reaches outside code only through ``AnalysisPorts``: the
records, whose one adapter is ``PostgresAnalysisRecords``, the sentiment
scorer and the LLM provider. ``deployed_ports`` builds them for the analysis
Lambda.

A ``PermanentDocumentError`` means a retry cannot help. Any other exception,
including generation's ``RuntimeError`` and ``ValueError``, is worth
retrying, so ``pipeline_stage.run_stage`` still decides between a retry and
a final failure.

The Lambda imports this module before it loads its configuration from SSM,
so nothing imported at the top of this file builds ``Settings``. Generation,
FinBERT and the Postgres records are imported where they are used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

from lambdas.common import (
    PermanentDocumentError,
    database_session,
    load_runtime_configuration,
)

if TYPE_CHECKING:
    from app.services.generation import Generated, Unavailable
    from app.services.generation.kinds import Kind
    from app.services.generation.providers import TextProvider

ArtifactKind = Literal["announcement", "news", "discussion", "other"]

# The metadata category stored text is recorded under, and the title a
# summary and FinBERT read when the artifact has none.
_STORED_TEXT_CATEGORIES = {"news": "news_article", "discussion": "user_discussion"}
_UNTITLED = {"news": "Untitled news article", "discussion": "Untitled public discussion"}


@dataclass(frozen=True)
class ArtifactFacts:
    """What analysis reads from one artifact's row."""

    artifact_id: UUID
    kind: ArtifactKind
    source_type: str | None
    run_id: UUID | None
    title: str | None
    raw_text: str | None
    # The publisher a news story names.
    source_name: str | None
    completed: bool


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
    summary: Generated[dict[str, object]] | Unavailable
    sentiment: Sentiment


@dataclass(frozen=True)
class Analysed:
    """An artifact this call analysed and recorded."""

    artifact_id: UUID
    run_id: UUID | None
    source_type: str | None
    category: str
    # False when no LLM is switched on or its answer has no text.
    summarised: bool


@dataclass(frozen=True)
class AlreadyAnalysed:
    """An artifact whose analysis had already completed, so nothing was done."""

    artifact_id: UUID
    run_id: UUID | None


class SentimentScorer(Protocol):
    def score(self, text: str) -> Sentiment:
        """The sentiment of one text."""


class FinBertScorer:
    """FinBERT, loaded from ``FINBERT_MODEL`` the first time it scores a text."""

    def score(self, text: str) -> Sentiment:
        # Imported on use: the sentiment service builds Settings.
        from app.services import sentiment

        result = sentiment.analyse_text(text)
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

    def start(self, artifact_id: UUID) -> None:
        """Record that the artifact's analysis has started."""

    def finish(self, artifact_id: UUID, result: AnalysisResult) -> bool:
        """Record the result and complete the analysis.

        Returns whether a summary was recorded with it.
        """


@dataclass(frozen=True)
class AnalysisPorts:
    """The outside code an analysis reaches."""

    records: AnalysisRecords
    scorer: SentimentScorer
    # None asks the provider LLM_PROVIDER selects.
    provider: TextProvider | None = None


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
    title = (facts.title or "").strip()
    text = ((facts.raw_text or "").strip() or title).replace("\x00", "").strip()
    if not text:
        raise PermanentDocumentError(
            "Stored-text artifact has no text",
            code="no_extractable_text",
        )
    if facts.completed:
        return AlreadyAnalysed(artifact_id=artifact_id, run_id=facts.run_id)

    ports.records.start(artifact_id)
    title = title or _UNTITLED[facts.kind]
    summarised = _record_analysis(
        artifact_id,
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
        category=category,
        summarised=summarised,
    )


def deployed_ports() -> AnalysisPorts:
    """The ports the analysis Lambda runs with."""
    load_runtime_configuration()
    # Imported once DATABASE_URL is loaded: the records import the crud
    # layer, which builds Settings.
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


def _summary_request(
    facts: ArtifactFacts,
    title: str,
    text: str,
) -> Kind[dict[str, object]]:
    """The summary kind for the artifact: the one place it is chosen."""
    generation = _generation()
    if facts.kind == "news":
        return generation.NewsSummary(
            title=title,
            source_name=facts.source_name,
            raw_text=text,
        )
    return generation.DiscussionSummary(
        title=title,
        source_type=facts.source_type or "",
        raw_text=text,
    )


def _record_analysis(  # pylint: disable=too-many-arguments
    artifact_id: UUID,
    ports: AnalysisPorts,
    *,
    title: str,
    text: str,
    metadata: dict[str, Any],
    request: Kind[dict[str, object]],
) -> bool:
    """Score, summarise and record one artifact's text, in that order.

    FinBERT reads the title and source text, never the summary, so a retry
    or a new summary cannot change the artifact's sentiment.
    """
    sentiment = ports.scorer.score(_sentiment_input(title, text))
    summary = _generation().generate(request, provider=ports.provider)
    return ports.records.finish(
        artifact_id,
        AnalysisResult(
            raw_text=text,
            metadata=metadata,
            summary=summary,
            sentiment=sentiment,
        ),
    )


def _sentiment_input(title: str, text: str) -> str:
    # Imported on use: the sentiment service builds Settings.
    from app.services import sentiment

    return sentiment.sentiment_input(title, text)


def _generation():
    # Imported on use: generation builds Settings.
    from app.services import generation

    return generation
