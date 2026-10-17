"""Populate a local database with bounded ASX, news, and Reddit content.

ASX documents and news stories are analysed in this process through the
artifact analysis module, exactly as the analysis worker would analyse
them, so the local stack needs no queues. A document already analysed is
not analysed again; it is only summarised again while its summary is
incomplete, for example after an LLM key is added.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from uuid import UUID

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.crud import artifact as artifact_crud
from app.crud import information_platform as platform_crud
from app.crud import ticker as ticker_crud
from app.database.connection import SessionLocal
from app.models.artifact import Artifact
from app.models.information_platform import InformationPlatform
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType
from app.schemas.information_platform import InformationPlatformCreate
from app.services import artifact_summary, discussion_collector, marketaux
from app.services.discussion_sources.reddit import REDDIT
from app.services.title_normalization import normalise_title
from app.sources import source_for_ticker
from lambdas import artifact_analysis
from lambdas.artifact_analysis import AlreadyAnalysed, Analysed, AnalysisPorts
from lambdas.download_validation import DownloadedDocument
from scrapers.adapter import DocumentRequest
from scrapers.base import Announcement
from scrapers.registry import adapter_for


LOCAL_DATABASE_HOSTS = {"127.0.0.1", "::1", "db", "localhost", "postgres"}
SessionScope = Callable[[], AbstractContextManager[Session]]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def bounded_announcements(
    announcements: Iterable[Announcement],
    *,
    lookback_days: int,
    max_documents: int,
    now: datetime | None = None,
) -> list[Announcement]:
    """Return the newest recent announcements within the configured cap."""
    if lookback_days < 1 or max_documents < 1:
        raise ValueError("lookback_days and max_documents must be positive")
    cutoff = _as_utc(now or datetime.now(timezone.utc)) - timedelta(
        days=lookback_days
    )
    recent = [
        announcement
        for announcement in announcements
        if _as_utc(announcement.date) >= cutoff
    ]
    return sorted(recent, key=lambda item: _as_utc(item.date), reverse=True)[
        :max_documents
    ]


def require_local_database() -> None:
    """Refuse to run this development loader against a remote database."""
    host = (make_url(settings.DATABASE_URL).host or "").lower()
    if host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError(
            "Local content loader refused a non-local database host"
        )


async def download_announcement(
    announcement: Announcement,
    directory: Path,
) -> DownloadedDocument:
    """Fetch one document the way the download worker does and save a copy."""
    downloaded = await adapter_for(announcement.ticker).fetch_document(
        DocumentRequest(
            document_url=announcement.pdf_url,
            title=announcement.title,
            metadata=announcement.metadata,
        ),
        max_bytes=settings.MAX_DOCUMENT_BYTES,
    )
    clean_title = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in announcement.title
    ).strip("_")[:120] or "announcement"
    directory.mkdir(parents=True, exist_ok=True)
    announcement.local_path = (
        directory
        / f"{announcement.date:%Y-%m-%d}_{clean_title}.{downloaded.extension}"
    )
    announcement.local_path.write_bytes(downloaded.content)
    return downloaded


def _asx_platform(db: Session) -> InformationPlatform:
    platform = platform_crud.get_platform_by_name(db, "ASX")
    if platform is not None:
        return platform
    return platform_crud.create_platform(
        db,
        InformationPlatformCreate(
            name="ASX",
            platform_type="asx_announcements",
            scrape_enabled=True,
        ),
    )


def _document_artifact(
    db: Session,
    announcement: Announcement,
    document: DownloadedDocument,
) -> tuple[UUID, bool]:
    """The artifact for a downloaded document, created on first sight.

    A document is known by its checksum. Returns the artifact's id and
    whether a summary it already has is incomplete.
    """
    content_hash = f"document:{document.checksum}"
    existing = artifact_crud.get_artifact_by_hash(db, content_hash)
    if existing is not None:
        return existing.id, artifact_summary.needs_summary(existing)
    artifact = artifact_crud.create_artifact(
        db,
        ArtifactCreate(
            source_type=SourceType.ASX_ANNOUNCEMENT,
            # Analysis stores the category's own type.
            artifact_type=ArtifactType.ASX_ANNOUNCEMENT_OTHER,
            title=normalise_title(
                announcement.title,
                announcement.source_url or announcement.pdf_url,
            ),
            url=announcement.source_url or "",
            document_url=announcement.pdf_url,
            published_at=announcement.date,
            content_hash=content_hash,
            raw_text="",
            ticker_id=ticker_crud.ensure_ticker(db, announcement.ticker).id,
            platform_id=_asx_platform(db).id,
            source_adapter=source_for_ticker(announcement.ticker).adapter,
            artifact_metadata={
                "pdf_url": announcement.pdf_url,
                "source_url": announcement.source_url,
                **announcement.metadata,
            },
        ),
    )
    return artifact.id, False


async def collect_asx(
    tickers: list[str],
    *,
    lookback_days: int,
    max_documents: int,
    output_dir: Path,
    session_scope: SessionScope = SessionLocal,
    ports: AnalysisPorts | None = None,
) -> dict:
    """Download each ticker's recent announcements, keep a copy and analyse them."""
    ports = ports or artifact_analysis.local_ports()
    result = {"found": 0, "processed": 0, "errors": []}
    for ticker in tickers:
        try:
            discovered = await adapter_for(ticker).list_documents()
            selected = bounded_announcements(
                discovered,
                lookback_days=lookback_days,
                max_documents=max_documents,
            )
            result["found"] += len(selected)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append({"ticker": ticker, "stage": "discover", "error": str(exc)})
            continue

        for announcement in selected:
            try:
                downloaded = await download_announcement(announcement, output_dir / ticker)
                with session_scope() as db:
                    artifact_id, needs_summary = _document_artifact(
                        db, announcement, downloaded
                    )
                outcome = artifact_analysis.analyse_downloaded_document(
                    artifact_id, downloaded, ports
                )
                if isinstance(outcome, AlreadyAnalysed) and needs_summary:
                    artifact_analysis.summarise(artifact_id, ports)
                result["processed"] += 1
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(
                    {
                        "ticker": ticker,
                        "stage": "process",
                        "title": announcement.title,
                        "error": str(exc),
                    }
                )
    return result


def _analyse_story(ports: AnalysisPorts) -> marketaux.AnalyseStory:
    """Analyse a stored story in this process instead of queueing it."""

    def analyse(_db: Session, story: Artifact) -> bool:
        outcome = artifact_analysis.analyse_stored_text(story.id, ports)
        if isinstance(outcome, AlreadyAnalysed) and artifact_summary.needs_summary(story):
            artifact_analysis.summarise(story.id, ports)
        return isinstance(outcome, Analysed)

    return analyse


def collect_news(
    tickers: list[str],
    *,
    limit: int,
    ports: AnalysisPorts | None = None,
) -> dict:
    if not settings.MARKETAUX_API_TOKEN:
        return {"status": "skipped", "reason": "MARKETAUX_API_TOKEN is not configured"}
    analyse = _analyse_story(ports or artifact_analysis.local_ports())
    results = []
    with SessionLocal() as db:
        for ticker in tickers:
            try:
                results.append(
                    marketaux.fetch_and_store_news(ticker, limit, db, analyse=analyse)
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                results.append({"symbol": ticker, "error": str(exc)})
    return {"status": "completed", "tickers": results}


def collect_reddit(*, subreddit: str, limit: int) -> dict:
    if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
        return {
            "status": "skipped",
            "reason": "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are not configured",
        }
    result = discussion_collector.collect(
        REDDIT, subreddit, limit, session_scope=SessionLocal
    )
    return asdict(result)


async def populate(args: argparse.Namespace) -> dict:
    require_local_database()
    tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    selected_sources = {
        source.strip().lower() for source in args.sources.split(",") if source.strip()
    }
    unknown_sources = selected_sources - {"asx", "news", "reddit"}
    if unknown_sources:
        raise ValueError(f"Unsupported sources: {sorted(unknown_sources)}")

    results = {}
    if "asx" in selected_sources:
        results["asx"] = await collect_asx(
            tickers,
            lookback_days=args.lookback_days,
            max_documents=args.max_documents,
            output_dir=Path(args.output_dir),
        )
    if "news" in selected_sources:
        results["news"] = collect_news(tickers, limit=args.news_limit)
    if "reddit" in selected_sources:
        results["reddit"] = collect_reddit(
            subreddit=args.subreddit,
            limit=args.reddit_limit,
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="asx,news,reddit")
    parser.add_argument("--tickers", default=",".join(settings.SUPPORTED_TICKERS))
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--max-documents", type=int, default=3)
    parser.add_argument("--news-limit", type=int, default=10)
    parser.add_argument("--subreddit", default="ASX")
    parser.add_argument("--reddit-limit", type=int, default=10)
    parser.add_argument("--output-dir", default="/app/output")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(populate(parse_args())), indent=2, default=str))
