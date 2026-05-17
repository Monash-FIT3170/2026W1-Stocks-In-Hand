from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.schemas.artifact import ArtifactCreate, SourceType
from datetime import datetime, timezone, timedelta

def get_artifact(db: Session, artifact_id: UUID):
    return db.query(Artifact).filter(Artifact.id == artifact_id).first()

def get_artifacts_by_ticker(db: Session, ticker_id: UUID):
    return db.query(Artifact).filter(Artifact.ticker_id == ticker_id).all()

def get_artifacts_by_platform(db: Session, platform_id: UUID):
    return db.query(Artifact).filter(Artifact.platform_id == platform_id).all()

def get_all_artifacts(db: Session, limit: int = 200, offset: int = 0):
    return db.query(Artifact).order_by(Artifact.published_at.desc()).offset(offset).limit(limit).all()

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

def create_artifact(db: Session, artifact: ArtifactCreate):
    db_artifact = Artifact(**artifact.model_dump())
    db.add(db_artifact)
    db.commit()
    db.refresh(db_artifact)
    return db_artifact

def get_artifact_by_hash(db: Session, content_hash: str):
    return db.query(Artifact).filter(Artifact.content_hash == content_hash).first()

def get_platform_by_name(db: Session, name: str):
    from app.models.information_platform import InformationPlatform
    return db.query(InformationPlatform).filter(InformationPlatform.name == name).first()
