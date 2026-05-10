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
from app.schemas.artifact import ArtifactCreate
from app.crud import artifact as artifact_crud
from app.crud import ticker as ticker_crud
from app.crud import information_platform as platform_crud

if TYPE_CHECKING:
    from scrapers.base import Announcement
    from classifier import ReportCategory

def compute_content_hash(text: str) -> str:
    """Generate SHA256 hash for deduplication"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def get_or_create_ticker(db, ticker_symbol: str) -> Ticker:
    """Get existing ticker or create new one"""
    ticker = ticker_crud.get_ticker_by_symbol(db, ticker_symbol)
    
    if not ticker:
        from app.schemas.ticker import TickerCreate
        ticker_data = TickerCreate(
            symbol=ticker_symbol,
            company_name=ticker_symbol,
            exchange="ASX"
        )
        ticker = ticker_crud.create_ticker(db, ticker_data)
        print(f"[STORAGE] Created new ticker: {ticker_symbol}")
    
    return ticker

def get_or_create_platform(db, platform_name: str = "ASX") -> InformationPlatform:
    """Get existing platform or create new one"""
    platform = platform_crud.get_platform_by_name(db, platform_name)
    
    if not platform:
        from app.schemas.information_platform import InformationPlatformCreate
        platform_data = InformationPlatformCreate(
            name=platform_name,
            platform_type="asx_announcements",
            scrape_enabled=True
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
    """
    Store announcement with raw text and metadata to database.
    
    Args:
        announcement: The scraped announcement with metadata
        category: The classified report category (if any)
        extracted_data: Structured data extracted from the announcement
        raw_text: The extracted text content (passed from pipeline)
    """
    print(f"[STORAGE] Storing: {announcement.title[:50]}... ({len(raw_text)} chars)")

    db = SessionLocal()
    try:
        ticker = get_or_create_ticker(db, announcement.ticker)
        platform = get_or_create_platform(db, "ASX")
        content_hash = compute_content_hash(raw_text)

        existing = db.query(Artifact).filter_by(content_hash=content_hash).first()
        if existing:
            print(f"[STORAGE] Duplicate found for: {announcement.title[:50]}... Skipping storage.")
            return
        
        metadata = {
            "pdf_url": announcement.pdf_url,
            "source_url": announcement.source_url,
            "category": category.__name__ if category else "UNKNOWN",
            "extracted_data": extracted_data,
            **announcement.metadata
        }

        artifact_data = ArtifactCreate(
            ticker_id=ticker.id,
            platform_id=platform.id,
            artifact_type="asx_announcement",
            title=announcement.title,
            url=announcement.source_url,
            raw_text=raw_text,
            artifact_metadata=metadata,
            published_at=announcement.date,
            content_hash=content_hash
        )

        artifact = artifact_crud.create_artifact(db, artifact_data)
        print(f"[STORAGE] Stored artifact (ID: {artifact.id}): {announcement.title[:50]}...")

    except Exception as e:
        db.rollback()
        print(f"[STORAGE] Error storing artifact: {e}")
        traceback.print_exc()
    finally:
        db.close()