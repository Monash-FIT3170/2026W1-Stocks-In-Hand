from typing import Any

from sqlalchemy import Integer, cast, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.models.ticker import Ticker
from app.schemas.artifact import ArtifactCreate, SourceType
from datetime import datetime, timezone, timedelta

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


def store_artifact_analysis(
    db: Session,
    *,
    artifact_id: UUID,
    raw_text: str,
    metadata: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    sentiment: dict[str, Any] | None = None,
) -> Artifact:
    """Atomically store extracted text and the single analysis result rows."""
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
        summary_row = (
            db.query(ArtifactSummary)
            .filter(ArtifactSummary.artifact_id == artifact_id)
            .first()
        )
        if summary_row is None:
            summary_row = ArtifactSummary(
                artifact_id=artifact_id,
                summary_text=str(summary["summary_text"]),
            )
            db.add(summary_row)
        summary_row.summary_text = str(summary["summary_text"])
        summary_row.model_used = summary.get("model_used")
        summary_row.prompt_version = summary.get("prompt_version")
        summary_row.confidence_score = summary.get("confidence_score")

    if sentiment is not None:
        sentiment_row = (
            db.query(ArtifactSentiment)
            .filter(ArtifactSentiment.artifact_id == artifact_id)
            .first()
        )
        if sentiment_row is None:
            sentiment_row = ArtifactSentiment(
                artifact_id=artifact_id,
                sentiment_label=str(sentiment["sentiment_label"]),
            )
            db.add(sentiment_row)
        sentiment_row.sentiment_label = str(sentiment["sentiment_label"])
        sentiment_row.stance = sentiment.get("stance")
        sentiment_row.confidence_score = sentiment.get("confidence_score")
        sentiment_row.model_used = sentiment.get("model_used")

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

def get_reddit_posts_for_ticker(
    db: Session,
    ticker_symbol: str,
    days: int = 30,
    limit: int = 50,
) -> list[Artifact]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    keyword = f"%{ticker_symbol.upper()}%"

    return (
        db.query(Artifact)
        .filter(Artifact.source_type == SourceType.REDDIT.value)
        .filter(Artifact.published_at >= cutoff)
        .filter(
            or_(
                Artifact.title.ilike(keyword),
                Artifact.raw_text.ilike(keyword),
            )
        )
        .order_by(
            Artifact.artifact_metadata["score"].as_integer().desc().nullslast()
        )
        .limit(limit)
        .all()
    )
