from __future__ import annotations

import hashlib
import sys
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
from app.models.artifact_summary import ArtifactSummary
from app.services import gemini as gemini_service
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType
from app.crud import artifact as artifact_crud
from app.crud import ticker as ticker_crud
from app.crud import information_platform as platform_crud

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
        summary = gemini_service.summarise_announcement(
            title=artifact.title or "Untitled ASX announcement",
            category=category_name,
            extracted_data=extracted_data,
            raw_text=raw_text,
        )
    except RuntimeError as exc:
        print(f"[SUMMARY] Skipped for artifact {artifact.id}: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"[SUMMARY] Failed for artifact {artifact.id}: {exc}")
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
        model_used=gemini_service.settings.GEMINI_MODEL,
        prompt_version=gemini_service.SUMMARY_PROMPT_VERSION,
    ))
    db.commit()
    print(f"[SUMMARY] Stored summary for artifact {artifact.id}")


def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    print(f"[STORAGE] Storing: {announcement.title[:50]}... ({len(raw_text)} chars)")

    db = SessionLocal()
    try:
        ticker = get_or_create_ticker(db, announcement.ticker)
        platform = get_or_create_platform(db, "ASX")
        content_hash = compute_content_hash(raw_text)

        existing = db.query(Artifact).filter_by(content_hash=content_hash).first()
        if existing:
            print(f"[STORAGE] Duplicate found for: {announcement.title[:50]}... Skipping storage.")
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
            title=announcement.title,
            url=announcement.source_url or "",
            published_at=announcement.date,
            content_hash=content_hash,
            raw_text=raw_text,
            ticker_id=ticker.id,
            platform_id=platform.id,
            artifact_metadata=metadata,
        )

        artifact = artifact_crud.create_artifact(db, artifact_data)
        print(f"[STORAGE] Stored artifact (ID: {artifact.id}): {announcement.title[:50]}...")
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
