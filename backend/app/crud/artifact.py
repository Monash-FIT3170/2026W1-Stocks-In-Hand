from datetime import datetime, timedelta, timezone
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crud.artifact_sentiment import stage_artifact_sentiment
from app.models.artifact import Artifact
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.ticker import Ticker
from app.schemas.artifact import ArtifactCreate, SourceType
from app.services import artifact_summary
from app.services.artifact_summary import Summary


def create_artifact(db: Session, artifact: ArtifactCreate):
    db_artifact = Artifact(**artifact.model_dump())
    db.add(db_artifact)
    db.commit()
    db.refresh(db_artifact)
    return db_artifact

def get_artifact(db: Session, artifact_id: UUID):
    return db.query(Artifact).filter(Artifact.id == artifact_id).first()

def get_artifacts_by_ticker(db: Session, ticker_id: UUID):
    return db.query(Artifact).filter(Artifact.ticker_id == ticker_id).all()

def get_artifacts_by_platform(db: Session, platform_id: UUID):
    return db.query(Artifact).filter(Artifact.platform_id == platform_id).all()

def get_all_artifacts(db: Session, limit: int = 200, offset: int = 0):
    return db.query(Artifact).order_by(Artifact.published_at.desc()).offset(offset).limit(limit).all()

def get_artifact_by_hash(db: Session, content_hash: str):
    return db.query(Artifact).filter(Artifact.content_hash == content_hash).first()


def _stage_artifact_analysis(
    db: Session,
    *,
    artifact_id: UUID,
    raw_text: str,
    metadata: dict[str, Any] | None,
    summary: Summary | None,
    sentiment: dict[str, Any] | None,
) -> Artifact:
    artifact = (
        db.query(Artifact)
        .filter(Artifact.id == artifact_id)
        .with_for_update()
        .first()
    )
    if artifact is None:
        raise ValueError(f"Artifact {artifact_id} does not exist")

    artifact.raw_text = raw_text
    artifact.artifact_metadata = {
        **(artifact.artifact_metadata or {}),
        **(metadata or {}),
    }

    if summary is not None:
        artifact_summary.record(db, artifact, summary)

    if sentiment is not None:
        stage_artifact_sentiment(
            db,
            artifact_id=artifact_id,
            sentiment_label=str(sentiment["sentiment_label"]),
            stance=sentiment.get("stance"),
            confidence_score=sentiment.get("confidence_score"),
            model_used=sentiment.get("model_used"),
        )

    return artifact


def store_artifact_analysis(
    db: Session,
    *,
    artifact_id: UUID,
    raw_text: str,
    metadata: dict[str, Any] | None = None,
    summary: Summary | None = None,
    sentiment: dict[str, Any] | None = None,
) -> Artifact:
    """Atomically store extracted text, the summary and the sentiment row.

    The artifact row is locked (`with_for_update`) for the duration of the
    transaction, which serializes concurrent `store_artifact_analysis` calls
    for the same artifact. The summary is recorded through the artifact
    summary module, whose upsert cannot conflict. The sentiment insert can
    still race a writer that does not take the lock, such as
    `upsert_artifact_sentiment`, between our lookup and commit, so it is
    retried once below, the same way the standalone upsert retries.
    """
    artifact = _stage_artifact_analysis(
        db,
        artifact_id=artifact_id,
        raw_text=raw_text,
        metadata=metadata,
        summary=summary,
        sentiment=sentiment,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        artifact = _stage_artifact_analysis(
            db,
            artifact_id=artifact_id,
            raw_text=raw_text,
            metadata=metadata,
            summary=summary,
            sentiment=sentiment,
        )
        db.commit()

    db.refresh(artifact)
    return artifact

def get_platform_by_name(db: Session, name: str):
    from app.models.information_platform import InformationPlatform
    return db.query(InformationPlatform).filter(InformationPlatform.name == name).first()

def get_recent_compiled_artifacts(
    db: Session,
    days: int = 30,
    limit: int = 200,
    offset: int = 0,
    ticker_symbol: str | None = None,
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    query = (
        db.query(Artifact)
        .filter(Artifact.published_at >= cutoff)
        .filter(Artifact.source_type.in_([
            SourceType.REDDIT.value,
            SourceType.ASX_ANNOUNCEMENT.value,
        ]))
    )

    if ticker_symbol:
        ticker = (
            db.query(Ticker)
            .filter(func.lower(Ticker.symbol) == ticker_symbol.lower())
            .first()
        )
        query = query.filter(Artifact.source_type == SourceType.ASX_ANNOUNCEMENT.value)
        query = query.filter(Artifact.ticker_id == ticker.id if ticker else False)

    return query.order_by(Artifact.published_at.desc()).offset(offset).limit(limit).all()

def build_recent_artifact_chunk(
    db: Session,
    days: int = 30,
    limit: int = 200,
    offset: int = 0,
    ticker_symbol: str | None = None,
):
    artifacts = get_recent_compiled_artifacts(
        db=db,
        days=days,
        limit=limit,
        offset=offset,
        ticker_symbol=ticker_symbol,
    )

    sections = []

    for artifact in artifacts:

        if not artifact.raw_text:
            continue

        section = f"""
SOURCE: {artifact.source_type}
ARTIFACT_TYPE: {artifact.artifact_type}
TITLE: {artifact.title or "N/A"}
URL: {artifact.url or "N/A"}
PUBLISHED_AT: {artifact.published_at or "N/A"}

CONTENT:
{artifact.raw_text}
""".strip()

        sections.append(section)

    return "\n\n---\n\n".join(sections)

def get_discussion_posts_for_ticker(
    db: Session,
    ticker_symbol: str,
    *,
    source_types: Sequence[str],
    days: int = 30,
    limit: int = 50,
) -> list[Artifact]:
    """Recent public discussion about a ticker, most engaging first.

    A post is about the ticker when it is stored against it or a ticker
    mention links it. Engagement is the collector's stored
    ``artifact_metadata["engagement"]``.
    """
    ticker = (
        db.query(Ticker)
        .filter(func.lower(Ticker.symbol) == ticker_symbol.lower())
        .first()
    )
    if not ticker:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        db.query(Artifact)
        .outerjoin(
            ArtifactTickerMention,
            and_(
                ArtifactTickerMention.artifact_id == Artifact.id,
                ArtifactTickerMention.ticker_id == ticker.id,
            ),
        )
        .filter(Artifact.source_type.in_(tuple(source_types)))
        .filter(Artifact.published_at >= cutoff)
        .filter(
            or_(
                Artifact.ticker_id == ticker.id,
                ArtifactTickerMention.ticker_id == ticker.id,
            )
        )
        .order_by(
            Artifact.artifact_metadata["engagement"].as_integer().desc().nullslast()
        )
        .limit(limit)
        .all()
    )
