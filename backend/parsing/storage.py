from __future__ import annotations

import hashlib
import sys
from pathlib import Path
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
) -> None:
    # TODO: implement database storage based on report category
    pass
