import re

from sqlalchemy import Integer, cast, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from app.models.artifact import Artifact
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


def _is_bluesky_ticker_post(artifact: Artifact, ticker_symbol: str, company_name: str) -> bool:
    text = " ".join((artifact.title or "", artifact.raw_text or ""))
    if not re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker_symbol)}(?![A-Za-z0-9])", text, re.IGNORECASE):
        return False

    company_terms = tuple(
        term
        for term in (company_name, company_name.replace(" Holdings Limited", ""))
        if term.lower() != ticker_symbol.lower()
    )
    finance_terms = (
        "asx",
        "share",
        "stock",
        "dividend",
        "earnings",
        "profit",
        "revenue",
        "investor",
        "market",
        "bank",
        "portfolio",
    )
    lower_text = text.lower()
    return any(
        term.lower() in lower_text
        for term in (*company_terms, f"{ticker_symbol} bank", *finance_terms)
        if term
    )


def get_bluesky_posts_for_ticker(
    db: Session,
    ticker_symbol: str,
    days: int = 30,
    limit: int = 50,
) -> list[Artifact]:
    ticker = (
        db.query(Ticker)
        .filter(func.lower(Ticker.symbol) == ticker_symbol.lower())
        .first()
    )
    if not ticker:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    candidates = (
        db.query(Artifact)
        .filter(Artifact.source_type == SourceType.BLUESKY.value)
        .filter(Artifact.published_at >= cutoff)
        .filter(
            or_(
                Artifact.title.ilike(f"%{ticker_symbol}%"),
                Artifact.raw_text.ilike(f"%{ticker_symbol}%"),
            )
        )
        .order_by(
            Artifact.artifact_metadata["like_count"].as_integer().desc().nullslast()
        )
        .limit(limit * 3)
        .all()
    )
    return [
        artifact
        for artifact in candidates
        if _is_bluesky_ticker_post(artifact, ticker_symbol, ticker.company_name)
    ][:limit]
