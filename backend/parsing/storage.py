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


def store(
    announcement: "Announcement",
    category: "type[ReportCategory] | None",
    extracted_data: dict,
) -> None:
    # TODO: implement database storage based on report category
    pass
