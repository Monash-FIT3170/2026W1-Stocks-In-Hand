"""Ticker sentiment: the one definition of a ticker's analysed sentiment.

Two read-models share it. The latest signal is the headline sentiment the
brief shows. Category sentiment breaks a ticker's analysed artifacts down
by sentiment bucket, with public discussion as a sixth group, for its
research summary. Both read the sentiment the analysis worker stored and
never run FinBERT, so the API needs no model runtime.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.read_models.ticker_records import find_ticker
from app.schemas.category_sentiment import CategorySentimentResponse, CategorySentimentResult
from app.schemas.public_discussion import PublicDiscussionSource
from app.sentiment_buckets import SENTIMENT_BUCKETS
from app.services import artifact_summary
from app.services.public_discussion import PUBLIC_DISCUSSION_SOURCE_TYPES
from app.services.sentiment import SENTIMENT_LABELS

CATEGORY_SENTIMENT_KEYS = (*SENTIMENT_BUCKETS, "user_discussion")
DEFAULT_SENTIMENT_DAYS = 365
DEFAULT_SENTIMENT_LIMIT = 250
FALLBACK_CATEGORY_KEYWORDS = {
    "revenue": (
        "financial",
        "guidance",
        "revenue",
        "earnings",
        "profit",
        "operational review",
        "quarterly",
        "half year",
    ),
    "strategy": (
        "strategy",
        "strategic",
        "acquisition",
        "growth",
        "project",
        "review",
        "capital allocation",
    ),
    "risk": (
        "risk",
        "impairment",
        "downgrade",
        "decline",
        "conflict",
        "investigation",
        "security",
    ),
    "dividend": ("dividend", "distribution", "buy-back", "buyback", "shareholder return"),
    "organisational": (
        "director",
        "leadership",
        "ceo",
        "chair",
        "appointment",
        "substantial holding",
        "organisational",
    ),
}

# Each taxonomy category proposes a sentiment bucket
# (parsing/classification/taxonomy.py). Until the team agrees that mapping,
# artifacts are still bucketed by these keywords, so the numbers shown do not
# change. Keywords match whole words, with plural and simple verb endings. Stored
# identifiers such as "SecurityNotification" or "security_notification" are
# single words, so "security" no longer files Appendix 3G/3H share notices
# under risk.
_CATEGORY_KEYWORD_PATTERNS = {
    category: re.compile(
        r"(?<![a-z0-9_])(?:"
        + "|".join(re.escape(keyword) for keyword in keywords)
        + r")(?:s|es|d|ed|ing)?(?![a-z0-9_])"
    )
    for category, keywords in FALLBACK_CATEGORY_KEYWORDS.items()
}

AnalysedRow = tuple[Artifact, ArtifactSentiment]


@dataclass(frozen=True)
class LatestSignal:
    """The sentiment of the artifact a ticker's headline signal comes from."""

    artifact_id: UUID
    sentiment_label: str
    confidence_score: float | None
    model_used: str | None
    analyzed_at: dt.datetime | None


def latest_signals(db: Session, ticker_ids: Iterable[UUID]) -> dict[UUID, LatestSignal]:
    """Each ticker's latest signal, in one query however many tickers are asked for.

    The signal is the most recently analysed sentiment of any artifact
    stored against the ticker. A post linked to it only by a mention does
    not count. A ticker with no analysed artifact is left out.
    """
    ids = list(ticker_ids)
    if not ids:
        return {}
    rows = (
        db.query(Artifact.ticker_id, ArtifactSentiment)
        .join(ArtifactSentiment, ArtifactSentiment.artifact_id == Artifact.id)
        .filter(Artifact.ticker_id.in_(ids))
        .order_by(Artifact.ticker_id, ArtifactSentiment.created_at.desc())
        .distinct(Artifact.ticker_id)
        .all()
    )
    return {
        ticker_id: LatestSignal(
            artifact_id=sentiment.artifact_id,
            sentiment_label=sentiment.sentiment_label,
            confidence_score=(
                float(sentiment.confidence_score)
                if sentiment.confidence_score is not None
                else None
            ),
            model_used=sentiment.model_used,
            analyzed_at=sentiment.created_at,
        )
        for ticker_id, sentiment in rows
    }


def read_category_sentiment(
    db: Session,
    symbol: str,
    *,
    days: int = DEFAULT_SENTIMENT_DAYS,
    limit: int = DEFAULT_SENTIMENT_LIMIT,
) -> CategorySentimentResponse:
    """A ticker's analysed sentiment in each bucket, read without running FinBERT.

    Reads at most ``limit`` analysed artifacts published, or collected when
    there is no publication date, in the last ``days`` days: those stored
    against the ticker and the posts that mention it. Raises
    ``TickerNotFound`` for a symbol with no ticker.
    """
    ticker = find_ticker(db, symbol)
    grouped: dict[str, list[AnalysedRow]] = {key: [] for key in CATEGORY_SENTIMENT_KEYS}
    for artifact, sentiment in _analysed_rows(db, ticker.id, days=days, limit=limit):
        for bucket in buckets_for(artifact):
            grouped[bucket].append((artifact, sentiment))

    categories = {
        bucket: aggregate_bucket(bucket, grouped[bucket]) for bucket in CATEGORY_SENTIMENT_KEYS
    }
    available_count = sum(result.available for result in categories.values())
    status: Literal["available", "partial", "unavailable"] = (
        "available"
        if available_count == len(CATEGORY_SENTIMENT_KEYS)
        else "partial"
        if available_count
        else "unavailable"
    )
    models = {result.model_used for result in categories.values() if result.model_used}
    analyzed_dates = [
        result.latest_analyzed_at for result in categories.values() if result.latest_analyzed_at
    ]
    return CategorySentimentResponse(
        ticker=ticker.symbol,
        status=status,
        model_used=(
            next(iter(models))
            if len(models) == 1
            else "Multiple stored models" if models else None
        ),
        latest_analyzed_at=max(analyzed_dates) if analyzed_dates else None,
        categories=categories,
    )


def buckets_for(artifact: Artifact) -> tuple[str, ...]:
    """The groups an analysed artifact counts in.

    A public discussion post counts only in ``user_discussion``. Anything
    else counts in every bucket a keyword in its category, type, title or
    summary lines names, or in ``strategy`` when none does.
    """
    if str(artifact.source_type or "").lower() in PUBLIC_DISCUSSION_SOURCE_TYPES:
        return ("user_discussion",)

    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    summary = artifact_summary.read(artifact)
    lines = (summary.summary, summary.about, summary.changed, summary.matters) if summary else ()
    haystack = " ".join(
        str(value or "")
        for value in (metadata.get("category"), artifact.artifact_type, artifact.title, *lines)
    ).lower()
    matches = tuple(
        bucket for bucket, pattern in _CATEGORY_KEYWORD_PATTERNS.items() if pattern.search(haystack)
    )
    return matches or ("strategy",)


def aggregate_bucket(bucket: str, rows: Sequence[AnalysedRow]) -> CategorySentimentResult:
    """One bucket's sentiment, weighted by each row's confidence.

    Rows with a label that is not a sentiment label are skipped. When no row
    carries any confidence, each label counts once.
    """
    usable: list[tuple[Artifact, ArtifactSentiment, str, float]] = []
    for artifact, sentiment in rows:
        label = str(sentiment.sentiment_label or "").lower()
        if label not in SENTIMENT_LABELS:
            continue
        confidence = float(sentiment.confidence_score or 0)
        usable.append((artifact, sentiment, label, min(max(confidence, 0.0), 1.0)))

    if not usable:
        return CategorySentimentResult(
            summary=f"No analysed {bucket.replace('_', ' ')} signal is available yet."
        )

    weights = dict.fromkeys(SENTIMENT_LABELS, 0.0)
    for _artifact, _sentiment, label, confidence in usable:
        weights[label] += confidence
    total_weight = sum(weights.values())
    if total_weight == 0:
        # No row carries any confidence, so count the labels instead.
        for _artifact, _sentiment, label, _confidence in usable:
            weights[label] += 1.0
        total_weight = float(len(usable))
    distribution = {label: round(weight / total_weight, 4) for label, weight in weights.items()}
    dominant = max(distribution, key=lambda label: distribution[label])
    confidence_score = round(
        sum(confidence for _artifact, _sentiment, _label, confidence in usable) / len(usable),
        4,
    )
    summaries: list[str] = []
    for artifact, _sentiment, _label, _confidence in usable:
        summary = _summary_text(artifact)
        if summary and summary not in summaries:
            summaries.append(summary)
        if len(summaries) == 2:
            break

    models = {
        str(sentiment.model_used)
        for _artifact, sentiment, _label, _confidence in usable
        if sentiment.model_used
    }
    analyzed_dates = [
        sentiment.created_at
        for _artifact, sentiment, _label, _confidence in usable
        if sentiment.created_at
    ]
    sources: list[PublicDiscussionSource] = []
    source_keys = set()
    for artifact, _sentiment, _label, _confidence in usable:
        source = _source(artifact)
        source_key = (source.source_type, source.url, source.title)
        if source_key in source_keys:
            continue
        source_keys.add(source_key)
        sources.append(source)
        if len(sources) == 10:
            break

    return CategorySentimentResult(
        summary=" ".join(summaries) or f"Based on {len(usable)} analysed signals.",
        available=True,
        sentiment_label=dominant,
        label=dominant,
        score=distribution[dominant],
        confidence_score=confidence_score,
        agreement_score=distribution[dominant],
        distribution=distribution,
        model_used=next(iter(models)) if len(models) == 1 else "Multiple stored models",
        chunks_used=len(usable),
        chunks_analyzed=len(usable),
        sources_count=len(usable),
        sources=sources,
        latest_analyzed_at=max(analyzed_dates) if analyzed_dates else None,
    )


def _analysed_rows(db: Session, ticker_id: UUID, *, days: int, limit: int) -> list[AnalysedRow]:
    """The ticker's analysed artifacts in the window, newest first, with their summaries."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(days, 1))
    return (
        db.query(Artifact, ArtifactSentiment)
        .options(artifact_summary.WITH_SUMMARY)
        .join(
            ArtifactSentiment,
            ArtifactSentiment.artifact_id == Artifact.id,
        )
        .outerjoin(
            ArtifactTickerMention,
            ArtifactTickerMention.artifact_id == Artifact.id,
        )
        .filter(
            or_(
                Artifact.ticker_id == ticker_id,
                ArtifactTickerMention.ticker_id == ticker_id,
            )
        )
        .filter(
            or_(
                Artifact.published_at >= cutoff,
                and_(
                    Artifact.published_at.is_(None),
                    Artifact.created_at >= cutoff,
                ),
            )
        )
        .order_by(
            Artifact.published_at.desc().nullslast(),
            ArtifactSentiment.created_at.desc(),
        )
        .distinct()
        .limit(max(limit, 1))
        .all()
    )


def _summary_text(artifact: Artifact) -> str:
    """The title and summary lines that stand for an artifact in a bucket's summary.

    An artifact with neither gives the start of its raw text.
    """
    summary = artifact_summary.read(artifact)
    parts = [artifact.title, *((summary.about, summary.changed, summary.matters) if summary else ())]
    if not any(parts):
        parts.append((artifact.raw_text or "")[:600])
    return " ".join(str(part).strip() for part in parts if part).strip()


def _source(artifact: Artifact) -> PublicDiscussionSource:
    def text(value: object) -> str | None:
        return value if isinstance(value, str) and value.strip() else None

    return PublicDiscussionSource(
        source_type=text(artifact.source_type) or "unknown",
        title=text(artifact.title),
        url=text(artifact.canonical_url) or text(artifact.document_url) or text(artifact.url),
        author=text(artifact.author),
        published_at=artifact.published_at,
    )
