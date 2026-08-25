from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path
import traceback
from typing import TYPE_CHECKING

# Make app modules importable from parsing directory
_BACKEND_DIR = Path(__file__).parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# db components
from app.database.connection import SessionLocal
from app.models.ticker import Ticker
from app.models.information_platform import InformationPlatform
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.services import groq as groq_service
from app.services import sentiment as sentiment_service
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType
from app.crud import artifact as artifact_crud
from app.crud import ticker as ticker_crud
from app.crud import information_platform as platform_crud
from app.services.title_normalization import MAX_TITLE_LENGTH, normalise_title

if TYPE_CHECKING:
    from scrapers.base import Announcement
    from categories.base import ReportCategory

# Maps parsing category class names to typed ArtifactType enum values.
# Categories not listed here are stored as ASX_ANNOUNCEMENT_OTHER.
_CATEGORY_TO_ARTIFACT_TYPE: dict[str, ArtifactType] = {
    "DividendAnnouncement": ArtifactType.DIVIDEND_ANNOUNCEMENT,
    "SecurityNotification": ArtifactType.SECURITY_NOTIFICATION,
    "LeadershipChange":     ArtifactType.LEADERSHIP_CHANGE,
}


def _fallback_summary_text(title: str, summary: dict[str, str]) -> str:
    parts = [
        summary.get("summary"),
        summary.get("about"),
        summary.get("changed"),
        summary.get("matters"),
    ]
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    return "\n\n".join(cleaned) or title


def _artifact_has_summary_fields(artifact: Artifact) -> bool:
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    return all(isinstance(metadata.get(key), str) and metadata[key].strip() for key in (
        "about",
        "changed",
        "matters",
    ))


def _artifact_sentiment_text(artifact: Artifact, raw_text: str) -> str:
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    parts = [
        artifact.title,
        metadata.get("summary"),
        metadata.get("about"),
        metadata.get("changed"),
        metadata.get("matters"),
    ]
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    if cleaned:
        return "\n\n".join(cleaned)
    return raw_text or artifact.raw_text or ""


def _artifact_has_sentiment(db, artifact: Artifact) -> bool:
    return (
        db.query(ArtifactSentiment)
        .filter(ArtifactSentiment.artifact_id == artifact.id)
        .first()
        is not None
    )


def _analyse_and_store_artifact_sentiment(db, artifact: Artifact, raw_text: str) -> None:
    if _artifact_has_sentiment(db, artifact):
        return

    text = _artifact_sentiment_text(artifact, raw_text).strip()
    if not text:
        print(f"[SENTIMENT] Skipped for artifact {artifact.id}: no text")
        return

    try:
        result = sentiment_service.analyse_text(text)
    except RuntimeError as exc:
        print(f"[SENTIMENT] Skipped for artifact {artifact.id}: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"[SENTIMENT] Failed for artifact {artifact.id}: {exc}")
        return

    db.add(ArtifactSentiment(
        artifact_id=artifact.id,
        sentiment_label=result["sentiment_label"],
        stance=result["label"],
        confidence_score=result["confidence_score"],
        model_used=result["model_used"],
    ))
    db.commit()
    print(f"[SENTIMENT] Stored {result['sentiment_label']} sentiment for artifact {artifact.id}")


def _summarise_and_store_artifact(
    db,
    artifact: Artifact,
    *,
    category_name: str,
    extracted_data: dict,
    raw_text: str,
) -> None:
    if not raw_text:
        print(f"[SUMMARY] Skipped for artifact {artifact.id}: no raw text")
        return

    try:
        summary = groq_service.summarise_announcement(
            title=artifact.title or "Untitled ASX announcement",
            category=category_name,
            extracted_data=extracted_data,
            raw_text=raw_text,
        )
    except RuntimeError as exc:
        print(f"[SUMMARY] Skipped for artifact {artifact.id}: {exc}")
        _analyse_and_store_artifact_sentiment(db, artifact, raw_text)
        return
    except Exception as exc:  # noqa: BLE001
        print(f"[SUMMARY] Failed for artifact {artifact.id}: {exc}")
        _analyse_and_store_artifact_sentiment(db, artifact, raw_text)
        return

    metadata = dict(artifact.artifact_metadata or {})
    for key in ("summary", "about", "changed", "matters"):
        value = summary.get(key)
        if value:
            metadata[key] = value
    artifact.artifact_metadata = metadata

    db.add(ArtifactSummary(
        artifact_id=artifact.id,
        summary_text=_fallback_summary_text(
            artifact.title or "Untitled ASX announcement",
            summary,
        ),
        model_used=groq_service.active_model_name(),
    ))
    db.commit()
    print(f"[SUMMARY] Stored summary for artifact {artifact.id}")
    _analyse_and_store_artifact_sentiment(db, artifact, raw_text)
    time.sleep(3)


def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def should_replace_artifact_title(
    existing_title: str | None,
    incoming_title: str | None,
) -> bool:
    """Return true when a duplicate can safely repair an oversized title."""
    existing = " ".join((existing_title or "").split())
    incoming = " ".join((incoming_title or "").split())
    return bool(
        incoming
        and len(incoming) <= MAX_TITLE_LENGTH
        and (
            not existing
            or (len(existing) > MAX_TITLE_LENGTH and len(incoming) < len(existing))
        )
    )


def get_or_create_ticker(db, ticker_symbol: str) -> Ticker:
    ticker = ticker_crud.get_ticker_by_symbol(db, ticker_symbol)
    if not ticker:
        from app.schemas.ticker import TickerCreate
        ticker_data = TickerCreate(
            symbol=ticker_symbol,
            company_name=ticker_symbol,
            exchange="ASX",
        )
        ticker = ticker_crud.create_ticker(db, ticker_data)
        print(f"[STORAGE] Created new ticker: {ticker_symbol}")
    return ticker


def get_or_create_platform(db, platform_name: str = "ASX") -> InformationPlatform:
    platform = platform_crud.get_platform_by_name(db, platform_name)
    if not platform:
        from app.schemas.information_platform import InformationPlatformCreate
        platform_data = InformationPlatformCreate(
            name=platform_name,
            platform_type="asx_announcements",
            scrape_enabled=True,
        )
        platform = platform_crud.create_platform(db, platform_data)
        print(f"[STORAGE] Created new platform: {platform_name}")
    return platform


def store(
    announcement: "Announcement",
    category: "type[ReportCategory] | None",
    extracted_data: dict,
    raw_text: str,
) -> None:
    """Store announcement with raw text and metadata to database."""
    clean_title = normalise_title(
        announcement.title,
        announcement.source_url or announcement.pdf_url,
    )
    print(f"[STORAGE] Storing: {clean_title[:50]}... ({len(raw_text)} chars)")

    db = SessionLocal()
    try:
        ticker = get_or_create_ticker(db, announcement.ticker)
        platform = get_or_create_platform(db, "ASX")
        content_hash = compute_content_hash(raw_text)

        existing = db.query(Artifact).filter_by(content_hash=content_hash).first()
        if existing:
            print(f"[STORAGE] Duplicate found for: {clean_title[:50]}... Skipping storage.")
            if should_replace_artifact_title(existing.title, clean_title):
                existing.title = clean_title
                db.add(existing)
                db.commit()
                print(f"[STORAGE] Repaired oversized title for artifact {existing.id}")
            if not _artifact_has_summary_fields(existing):
                existing_metadata = (
                    existing.artifact_metadata
                    if isinstance(existing.artifact_metadata, dict)
                    else {}
                )
                existing_category = str(
                    existing_metadata.get("category")
                    or (category.__name__ if category else "UNKNOWN")
                )
                existing_extracted_data = (
                    existing_metadata.get("extracted_data")
                    if isinstance(existing_metadata.get("extracted_data"), dict)
                    else extracted_data
                )
                _summarise_and_store_artifact(
                    db,
                    existing,
                    category_name=existing_category,
                    extracted_data=existing_extracted_data,
                    raw_text=existing.raw_text or raw_text,
                )
            else:
                _analyse_and_store_artifact_sentiment(
                    db,
                    existing,
                    existing.raw_text or raw_text,
                )
            return

        category_name = category.__name__ if category else "UNKNOWN"
        artifact_type = _CATEGORY_TO_ARTIFACT_TYPE.get(
            category_name, ArtifactType.ASX_ANNOUNCEMENT_OTHER
        )

        metadata = {
            "pdf_url": announcement.pdf_url,
            "source_url": announcement.source_url,
            "category": category_name,
            "extracted_data": extracted_data,
            **announcement.metadata,
        }

        artifact_data = ArtifactCreate(
            source_type=SourceType.ASX_ANNOUNCEMENT,
            artifact_type=artifact_type,
            title=clean_title,
            url=announcement.source_url or "",
            published_at=announcement.date,
            content_hash=content_hash,
            raw_text=raw_text,
            ticker_id=ticker.id,
            platform_id=platform.id,
            artifact_metadata=metadata,
        )

        artifact = artifact_crud.create_artifact(db, artifact_data)
        print(f"[STORAGE] Stored artifact (ID: {artifact.id}): {clean_title[:50]}...")
        _summarise_and_store_artifact(
            db,
            artifact,
            category_name=category_name,
            extracted_data=extracted_data,
            raw_text=raw_text,
        )

    except Exception as e:
        db.rollback()
        print(f"[STORAGE] Error storing artifact: {e}")
        traceback.print_exc()
    finally:
        db.close()
