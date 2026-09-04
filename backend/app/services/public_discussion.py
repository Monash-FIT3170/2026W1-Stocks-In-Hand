import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import artifact_ticker_mention as mention_crud
from app.models.artifact import Artifact
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.ticker import Ticker
from app.schemas.public_discussion import ArtifactTickerMentionCreate

PUBLIC_DISCUSSION_SOURCE_TYPES = frozenset(
    {"reddit", "bluesky", "mastodon", "blog"}
)
FINANCE_TERMS = frozenset(
    {
        "asx",
        "bank",
        "bearish",
        "bullish",
        "buy",
        "company",
        "dividend",
        "earnings",
        "guidance",
        "investor",
        "investors",
        "market",
        "mining",
        "portfolio",
        "profit",
        "results",
        "revenue",
        "sell",
        "share",
        "shares",
        "stock",
        "stocks",
    }
)
LEGAL_SUFFIX_PATTERN = re.compile(
    r"\s+(?:group\s+holdings|group|holdings)?\s*(?:limited|ltd)\.?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TickerMentionMatch:
    ticker_id: UUID
    symbol: str
    match_method: str
    match_confidence: float
    matched_text: str


def _phrase_pattern(value: str) -> re.Pattern[str]:
    escaped = re.escape(value.strip()).replace(r"\ ", r"\s+")
    return re.compile(
        rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _company_aliases(company_name: str, symbol: str) -> tuple[str, ...]:
    candidates = [company_name.strip()]
    shortened = LEGAL_SUFFIX_PATTERN.sub("", company_name.strip()).strip()
    candidates.append(shortened)
    if shortened.lower().endswith(" of australia"):
        candidates.append(shortened[: -len(" of australia")].strip())

    aliases = []
    for candidate in candidates:
        if (
            len(candidate) >= 5
            and candidate.casefold() != symbol.casefold()
            and candidate.casefold() not in {alias.casefold() for alias in aliases}
        ):
            aliases.append(candidate)
    return tuple(aliases)


def _metadata_has_finance_context(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    context_values = [
        metadata.get("subreddit"),
        metadata.get("flair"),
        *(metadata.get("tags") or []),
    ]
    words = set(
        re.findall(
            r"[A-Za-z]+",
            " ".join(str(value or "") for value in context_values).lower(),
        )
    )
    return bool(words & FINANCE_TERMS)


def _has_finance_context(text: str, metadata: dict[str, Any] | None) -> bool:
    words = set(re.findall(r"[A-Za-z]+", text.lower()))
    return bool(words & FINANCE_TERMS) or _metadata_has_finance_context(metadata)


def find_ticker_mentions(
    *,
    title: str | None,
    raw_text: str | None,
    metadata: dict[str, Any] | None,
    tickers: Iterable[Ticker],
) -> list[TickerMentionMatch]:
    """Return strong, explainable ticker matches for one public post."""

    text = " ".join(part.strip() for part in (title or "", raw_text or "") if part)
    if not text:
        return []

    has_finance_context = _has_finance_context(text, metadata)
    matches = []
    for ticker in tickers:
        symbol = str(ticker.symbol or "").strip().upper()
        if not symbol:
            continue

        patterns = (
            ("cashtag", 1.0, re.compile(rf"(?<![A-Za-z0-9])\${re.escape(symbol)}(?![A-Za-z0-9])", re.IGNORECASE)),
            (
                "exchange_qualified",
                1.0,
                re.compile(
                    rf"(?<![A-Za-z0-9])(?:ASX\s*:\s*{re.escape(symbol)}|{re.escape(symbol)}\.AX)(?![A-Za-z0-9])",
                    re.IGNORECASE,
                ),
            ),
        )
        matched = None
        for method, confidence, pattern in patterns:
            result = pattern.search(text)
            if result:
                matched = TickerMentionMatch(
                    ticker_id=ticker.id,
                    symbol=symbol,
                    match_method=method,
                    match_confidence=confidence,
                    matched_text=result.group(0),
                )
                break

        if matched is None:
            for alias in _company_aliases(str(ticker.company_name or ""), symbol):
                result = _phrase_pattern(alias).search(text)
                if result:
                    matched = TickerMentionMatch(
                        ticker_id=ticker.id,
                        symbol=symbol,
                        match_method="company_name",
                        match_confidence=0.95,
                        matched_text=result.group(0),
                    )
                    break

        if matched is None and has_finance_context:
            result = _phrase_pattern(symbol).search(text)
            if result:
                matched = TickerMentionMatch(
                    ticker_id=ticker.id,
                    symbol=symbol,
                    match_method="ticker_symbol",
                    match_confidence=0.85,
                    matched_text=result.group(0),
                )

        if matched is not None:
            matches.append(matched)

    return matches


def matches_for_artifact(
    artifact: Artifact,
    tickers: Iterable[Ticker],
) -> list[TickerMentionMatch]:
    return find_ticker_mentions(
        title=artifact.title,
        raw_text=artifact.raw_text,
        metadata=artifact.artifact_metadata,
        tickers=tickers,
    )


def link_artifact_to_tickers(
    db: Session,
    artifact: Artifact,
    *,
    tickers: Sequence[Ticker] | None = None,
    commit: bool = True,
) -> list[TickerMentionMatch]:
    candidate_tickers = list(tickers) if tickers is not None else db.query(Ticker).all()
    matches = matches_for_artifact(artifact, candidate_tickers)
    for match in matches:
        mention_crud.upsert_artifact_ticker_mention(
            db,
            ArtifactTickerMentionCreate(
                artifact_id=artifact.id,
                ticker_id=match.ticker_id,
                match_method=match.match_method,
                match_confidence=match.match_confidence,
                matched_text=match.matched_text,
            ),
            commit=False,
        )

    if matches and commit:
        db.commit()
    return matches


def queue_artifact_analysis(
    db: Session,
    artifact: Artifact,
    _matches: Sequence[TickerMentionMatch],
) -> bool:
    """Queue unfinished discussion text when analysis is configured.

    Ticker matches still control ticker links, but a broad ASX discussion can be
    useful in the announcements feed even when it does not name a supported ticker.
    """
    if (
        artifact.analysis_status in {"queued", "analyzing", "completed"}
        or not settings.ANALYSIS_QUEUE_URL
    ):
        return False
    from app.crud import scrape_run as scrape_run_crud
    from app.services import analysis_queue

    analysis_queue.enqueue_stored_artifact_analysis(artifact.id)
    scrape_run_crud.mark_inline_artifact_analysis_queued(db, artifact.id)
    return True


def backfill_artifact_ticker_mentions(
    db: Session,
    *,
    source_types: Sequence[str] | None = None,
    limit: int = 500,
    offset: int = 0,
    execute: bool = False,
) -> dict[str, int | bool]:
    selected_sources = tuple(source_types or sorted(PUBLIC_DISCUSSION_SOURCE_TYPES))
    if not selected_sources:
        raise ValueError("At least one source type is required")
    if limit < 1 or offset < 0:
        raise ValueError("limit must be positive and offset must not be negative")

    tickers = db.query(Ticker).order_by(Ticker.symbol.asc()).all()
    artifacts = (
        db.query(Artifact)
        .filter(Artifact.source_type.in_(selected_sources))
        .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    artifact_ids = [artifact.id for artifact in artifacts]
    existing_pairs = set()
    if artifact_ids:
        existing_pairs = {
            (artifact_id, ticker_id)
            for artifact_id, ticker_id in (
                db.query(
                    ArtifactTickerMention.artifact_id,
                    ArtifactTickerMention.ticker_id,
                )
                .filter(ArtifactTickerMention.artifact_id.in_(artifact_ids))
                .all()
            )
        }

    matched_artifacts = 0
    matches_found = 0
    new_mentions = 0
    for artifact in artifacts:
        matches = matches_for_artifact(artifact, tickers)
        if matches:
            matched_artifacts += 1
        matches_found += len(matches)
        new_mentions += sum(
            (artifact.id, match.ticker_id) not in existing_pairs
            for match in matches
        )
        if execute and matches:
            link_artifact_to_tickers(
                db,
                artifact,
                tickers=tickers,
                commit=False,
            )

    if execute and matches_found:
        db.commit()

    return {
        "dry_run": not execute,
        "artifacts_scanned": len(artifacts),
        "matched_artifacts": matched_artifacts,
        "matches_found": matches_found,
        "new_mentions": new_mentions,
        "mentions_written": new_mentions if execute else 0,
    }


def _ticker_for_symbol(db: Session, ticker_symbol: str) -> Ticker:
    symbol = ticker_symbol.strip().upper()
    ticker = db.query(Ticker).filter(func.lower(Ticker.symbol) == symbol.lower()).first()
    if ticker is None:
        raise ValueError(f"Ticker '{symbol}' not found")
    return ticker


def _ticker_discussion_artifacts(db: Session, ticker: Ticker) -> list[Artifact]:
    return (
        db.query(Artifact)
        .filter(Artifact.source_type.in_(tuple(PUBLIC_DISCUSSION_SOURCE_TYPES)))
        .filter(
            or_(
                Artifact.ticker_id == ticker.id,
                Artifact.ticker_mentions.any(
                    ArtifactTickerMention.ticker_id == ticker.id
                ),
            )
        )
        .order_by(
            Artifact.published_at.desc().nullslast(),
            Artifact.created_at.desc(),
        )
        .all()
    )


def public_discussion_status(
    db: Session,
    ticker_symbol: str,
) -> dict[str, Any]:
    ticker = _ticker_for_symbol(db, ticker_symbol)
    artifacts = _ticker_discussion_artifacts(db, ticker)
    counts = {
        "total": len(artifacts),
        "pending": 0,
        "queued": 0,
        "analyzing": 0,
        "completed": 0,
        "failed": 0,
    }
    sources: dict[str, int] = {}
    collected_dates = []
    for artifact in artifacts:
        status = str(artifact.analysis_status or "pending").lower()
        if status not in {"pending", "queued", "analyzing", "completed", "failed"}:
            status = "pending"
        counts[status] += 1
        source_type = str(artifact.source_type or "unknown").lower()
        sources[source_type] = sources.get(source_type, 0) + 1
        collected_at = artifact.published_at or artifact.created_at
        if collected_at is not None:
            collected_dates.append(collected_at)

    if not artifacts:
        status = "unavailable"
    elif counts["completed"] == counts["total"]:
        status = "available"
    elif counts["completed"]:
        status = "partial"
    elif counts["failed"] == counts["total"]:
        status = "failed"
    else:
        status = "pending"
    return {
        "ticker": ticker.symbol,
        "status": status,
        "counts": counts,
        "sources": dict(sorted(sources.items())),
        "latest_collected_at": max(collected_dates) if collected_dates else None,
    }


def requeue_pending_analysis(
    db: Session,
    *,
    ticker_symbol: str | None = None,
    limit: int = 100,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview or queue a bounded batch of recoverable discussion artifacts."""
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    ticker = _ticker_for_symbol(db, ticker_symbol) if ticker_symbol else None
    artifacts = _pending_analysis_artifacts(db, ticker=ticker, limit=limit)
    artifact_ids = [artifact.id for artifact in artifacts]
    if not execute:
        return {
            "execute": False,
            "ticker": ticker.symbol if ticker else None,
            "candidates": len(artifacts),
            "queued": 0,
            "artifact_ids": artifact_ids,
            "errors": [],
        }
    if not settings.ANALYSIS_QUEUE_URL:
        raise ValueError("ANALYSIS_QUEUE_URL is not configured")

    from app.crud import scrape_run as scrape_run_crud
    from app.services import analysis_queue

    queued_ids = []
    errors = []
    for artifact in artifacts:
        try:
            analysis_queue.enqueue_stored_artifact_analysis(artifact.id)
            scrape_run_crud.mark_inline_artifact_analysis_queued(db, artifact.id)
            queued_ids.append(artifact.id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            errors.append({"artifact_id": str(artifact.id), "message": str(exc)})
    return {
        "execute": True,
        "ticker": ticker.symbol if ticker else None,
        "candidates": len(artifacts),
        "queued": len(queued_ids),
        "artifact_ids": queued_ids,
        "errors": errors,
    }


def _pending_analysis_artifacts(
    db: Session,
    *,
    ticker: Ticker | None,
    limit: int,
) -> list[Artifact]:
    query = (
        db.query(Artifact)
        .filter(Artifact.source_type.in_(tuple(PUBLIC_DISCUSSION_SOURCE_TYPES)))
        .filter(Artifact.analysis_status.in_(("pending", "failed")))
        .filter(
            func.length(
                func.trim(
                    func.coalesce(Artifact.raw_text, "")
                    + func.coalesce(Artifact.title, "")
                )
            )
            > 0
        )
        .filter(
            or_(
                Artifact.ticker_id.isnot(None),
                Artifact.ticker_mentions.any(),
            )
        )
    )
    if ticker is not None:
        query = query.filter(
            or_(
                Artifact.ticker_id == ticker.id,
                Artifact.ticker_mentions.any(
                    ArtifactTickerMention.ticker_id == ticker.id
                ),
            )
        )
    artifacts = query.order_by(Artifact.created_at.asc()).limit(limit).all()
    return list(artifacts)
