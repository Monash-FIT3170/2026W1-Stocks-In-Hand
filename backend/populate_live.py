"""Bounded local-model loader for a remote PostgreSQL database.

Dry-run discovery is the default. A remote write needs --execute, a separate
LIVE_DATABASE_URL environment variable, and an exact --confirm-host value.
The script never runs Alembic or deletes existing rows.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

DEFAULT_TICKERS = ("ANZ", "BHP", "CBA", "CSL", "WES")
LOCAL_DATABASE_HOSTS = {"127.0.0.1", "::1", "db", "localhost"}
SUMMARY_KEYS = ("summary", "about", "changed", "matters")
REQUIRED_SCHEMA = {
    "alembic_version": {"version_num"},
    "information_platforms": {"id", "name", "platform_type"},
    "tickers": {"id", "symbol", "company_name"},
    "scrape_runs": {
        "id",
        "ticker_id",
        "platform_id",
        "status",
        "idempotency_key",
        "items_found",
        "items_saved",
        "items_downloaded",
        "items_analyzed",
        "items_failed",
    },
    "artifacts": {
        "id",
        "scrape_run_id",
        "source_document_identity",
        "artifact_metadata",
        "raw_text",
        "download_status",
        "analysis_status",
    },
    "artifact_summaries": {"artifact_id", "summary_text", "model_used"},
    "artifact_sentiments": {
        "artifact_id",
        "sentiment_label",
        "confidence_score",
        "model_used",
    },
}


@dataclass(frozen=True)
class DatabaseTarget:
    host: str
    database: str


@dataclass
class TickerResult:
    ticker: str
    discovered: int = 0
    selected: int = 0
    inserted: int = 0
    skipped: int = 0
    failed: int = 0
    scrape_run_id: str | None = None
    run_status: str | None = None
    verified_artifacts: int | None = None
    verified_summaries: int | None = None
    verified_sentiments: int | None = None
    warning: str | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape recent ASX documents and analyse them with local Ollama.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write to the confirmed remote database. The default is dry-run.",
    )
    parser.add_argument(
        "--confirm-host",
        help="Exact remote database hostname required with --execute.",
    )
    parser.add_argument(
        "--database-url-env",
        default="LIVE_DATABASE_URL",
        help="Environment variable holding the remote PostgreSQL URL.",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=list(DEFAULT_TICKERS),
        help="Supported ASX ticker symbols.",
    )
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--max-documents", type=int, default=3)
    parser.add_argument("--model", default="qwen3.5:latest")
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:11434",
    )
    return parser


def _normalise_tickers(values: list[str]) -> list[str]:
    tickers: list[str] = []
    for value in values:
        for part in value.split(","):
            symbol = part.strip().upper()
            if symbol and symbol not in tickers:
                tickers.append(symbol)
    unsupported = sorted(set(tickers) - set(DEFAULT_TICKERS))
    if unsupported:
        raise ValueError(
            "Unsupported tickers: "
            + ", ".join(unsupported)
            + ". Supported: "
            + ", ".join(DEFAULT_TICKERS)
        )
    if not tickers:
        raise ValueError("At least one ticker is required")
    return tickers


def _validate_live_database_url(
    value: str,
    *,
    confirmed_host: str | None,
) -> DatabaseTarget:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        database = unquote(parsed.path.lstrip("/")).strip()
    except ValueError as exc:
        raise ValueError("The live database URL is malformed") from exc
    if parsed.scheme not in {
        "postgres",
        "postgresql",
        "postgresql+psycopg",
        "postgresql+psycopg2",
    }:
        raise ValueError("The live database URL must use PostgreSQL")
    if not host or not database or not parsed.username:
        raise ValueError("The live database URL is missing a host, database, or user")
    if host in LOCAL_DATABASE_HOSTS or host.endswith(".local"):
        raise ValueError("--execute refuses local database hosts")
    if not confirmed_host or confirmed_host.strip().lower() != host:
        raise ValueError(
            f"Pass --confirm-host {host} to confirm the remote write target"
        )
    return DatabaseTarget(host=host, database=database)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bounded_announcements(
    announcements: list[Any],
    *,
    lookback_days: int,
    now: datetime | None = None,
) -> list[Any]:
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=lookback_days)
    bounded = [
        item
        for item in announcements
        if _as_utc(item.date) >= cutoff and _as_utc(item.date) <= current
    ]
    return sorted(bounded, key=lambda item: _as_utc(item.date), reverse=True)


def _safe_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    text = re.sub(
        r"postgres(?:ql)?(?:\+\w+)?://[^\s]+",
        "[database-url-redacted]",
        text,
        flags=re.IGNORECASE,
    )
    return f"{type(exc).__name__}: {text[:500]}"


def _run_key(
    *,
    ticker: str,
    model: str,
    prompt: str,
    lookback_days: int,
    maximum: int,
) -> str:
    day = datetime.now(timezone.utc).date().isoformat()
    settings = f"{model}|{prompt}|{lookback_days}|{maximum}"
    digest = hashlib.sha256(settings.encode("utf-8")).hexdigest()[:12]
    return f"local-populate:{day}:{ticker}:{digest}"


def _summary_text(summary: dict[str, Any]) -> str:
    return "\n\n".join(str(summary[key]).strip() for key in SUMMARY_KEYS)


def _preflight_database() -> str:
    from sqlalchemy import inspect, text

    from app.database.connection import engine

    inspector = inspect(engine)
    available = set(inspector.get_table_names())
    missing_tables = set(REQUIRED_SCHEMA) - available
    if missing_tables:
        raise RuntimeError(
            "Remote schema is missing tables: " + ", ".join(sorted(missing_tables))
        )
    for table, expected in REQUIRED_SCHEMA.items():
        columns = {column["name"] for column in inspector.get_columns(table)}
        missing = expected - columns
        if missing:
            raise RuntimeError(
                f"Remote table '{table}' is missing columns: "
                + ", ".join(sorted(missing))
            )
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    return str(revision)


def _mark_locally_stored(
    artifact_id: UUID,
    *,
    checksum: str,
    content_type: str,
    file_size: int,
    document_format: str,
) -> None:
    from app.database.connection import SessionLocal
    from app.models.artifact import Artifact
    from app.models.scrape_run import ScrapeRun

    with SessionLocal() as db:
        artifact = (
            db.query(Artifact)
            .filter(Artifact.id == artifact_id)
            .with_for_update()
            .one()
        )
        run = (
            db.query(ScrapeRun)
            .filter(ScrapeRun.id == artifact.scrape_run_id)
            .with_for_update()
            .one()
        )
        first_store = artifact.download_status != "stored"
        artifact.download_status = "stored"
        artifact.checksum_sha256 = checksum
        artifact.content_type = content_type
        artifact.file_size_bytes = file_size
        artifact.downloaded_at = artifact.downloaded_at or datetime.now(timezone.utc)
        artifact.last_error = None
        artifact.artifact_metadata = {
            **(artifact.artifact_metadata or {}),
            "storage_environment": "local",
            "document_format": document_format,
        }
        if first_store:
            run.items_downloaded = (run.items_downloaded or 0) + 1
            run.items_saved = (run.items_saved or 0) + 1
        run.status = "analyzing"
        run.finished_at = None
        db.commit()


def _mark_artifact_failed(artifact_id: UUID, *, error: str) -> None:
    from app.crud import scrape_run as scrape_run_crud
    from app.database.connection import SessionLocal
    from app.models.artifact import Artifact

    with SessionLocal() as db:
        artifact = db.query(Artifact).filter(Artifact.id == artifact_id).one()
        download_status = artifact.download_status
    with SessionLocal() as db:
        if download_status == "stored":
            scrape_run_crud.mark_artifact_analysis_failed(
                db,
                artifact_id,
                error=error,
            )
        else:
            scrape_run_crud.mark_artifact_download_failed(
                db,
                artifact_id,
                error=error,
            )


async def _download_announcement(
    *,
    source_adapter: str,
    source_url: str,
    document_url: str,
    title: str,
    metadata: dict,
    max_bytes: int,
):
    if source_adapter == "csl":
        from lambdas.download_validation import download_document

        return await asyncio.to_thread(
            download_document,
            document_url,
            max_bytes=max_bytes,
        )

    from lambdas.source_download import resolve_session_download

    return await resolve_session_download(
        source_adapter=source_adapter,
        source_url=source_url,
        document_url=document_url,
        title=title,
        metadata=metadata,
        max_bytes=max_bytes,
    )


async def _process_artifact(
    *,
    artifact_id: UUID,
    announcement: Any,
    source_adapter: str,
    source_url: str,
) -> None:
    from app.core.config import settings
    from app.crud import artifact as artifact_crud
    from app.crud import scrape_run as scrape_run_crud
    from app.database.connection import SessionLocal
    from app.services import summary as summary_service
    from parsing.analysis import apply_rules, extract_document

    with SessionLocal() as db:
        scrape_run_crud.mark_artifact_download_started(db, artifact_id)

    downloaded = await _download_announcement(
        source_adapter=source_adapter,
        source_url=source_url,
        document_url=announcement.pdf_url,
        title=announcement.title,
        metadata=announcement.metadata,
        max_bytes=settings.MAX_DOCUMENT_BYTES,
    )
    _mark_locally_stored(
        artifact_id,
        checksum=downloaded.checksum,
        content_type=downloaded.content_type,
        file_size=len(downloaded.content),
        document_format=downloaded.document_format,
    )

    with SessionLocal() as db:
        scrape_run_crud.mark_artifact_analysis_started(db, artifact_id)

    parsed = apply_rules(
        extract_document(
            downloaded.content,
            document_format=downloaded.document_format,
            max_pages=settings.MAX_PDF_PAGES,
            max_ocr_pages=settings.MAX_OCR_PAGES,
        ),
        title=announcement.title,
    )
    summary = summary_service.summarise_announcement(
        title=announcement.title,
        category=parsed.category,
        extracted_data=parsed.extracted_data,
        raw_text=parsed.raw_text,
    )
    model = summary_service.active_model_name()
    prompt = summary_service.active_prompt_version()
    sentiment = str(summary["sentiment_label"])
    confidence = float(summary["sentiment_confidence"])
    metadata = {
        "category": parsed.category,
        "category_confidence": parsed.category_confidence,
        "extracted_data": parsed.extracted_data,
        "page_count": parsed.page_count,
        "document_format": downloaded.document_format,
        **{key: summary[key] for key in SUMMARY_KEYS},
        "analysis_provenance": {
            "environment": "local",
            "provider": summary_service.active_provider_name(),
            "model": model,
            "prompt_version": prompt,
            "publication_status": "published",
        },
    }
    with SessionLocal() as db:
        artifact_crud.store_artifact_analysis(
            db,
            artifact_id=artifact_id,
            raw_text=parsed.raw_text,
            metadata=metadata,
            summary={
                "summary_text": _summary_text(summary),
                "model_used": model,
            },
            sentiment={
                "sentiment_label": sentiment,
                "stance": sentiment,
                "confidence_score": confidence,
                "model_used": model,
            },
        )
    with SessionLocal() as db:
        scrape_run_crud.mark_artifact_analysis_completed(db, artifact_id)


async def _discover(ticker: str, *, lookback_days: int) -> list[Any]:
    from scrapers.registry import discover

    return _bounded_announcements(
        await discover(ticker),
        lookback_days=lookback_days,
    )


async def _dry_run(args: argparse.Namespace, tickers: list[str]) -> list[TickerResult]:
    results: list[TickerResult] = []
    for ticker in tickers:
        result = TickerResult(ticker=ticker)
        try:
            announcements = await _discover(ticker, lookback_days=args.lookback_days)
            selected = announcements[: args.max_documents]
            result.discovered = len(announcements)
            result.selected = len(selected)
            if not announcements:
                result.warning = "No recent documents found; verify the source scraper"
            print(f"{ticker}: {len(selected)} of {len(announcements)} recent documents")
            for item in selected:
                print(f"  {_as_utc(item.date).date().isoformat()} | {item.title}")
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            print(f"{ticker}: discovery failed: {_safe_error(exc)}", file=sys.stderr)
        results.append(result)
    return results


async def _execute_ticker(
    args: argparse.Namespace,
    *,
    ticker: str,
) -> TickerResult:
    from app.crud import scrape_run as scrape_run_crud
    from app.database.connection import SessionLocal
    from app.services import summary as summary_service
    from lambdas.common import canonicalize_url
    from scrapers.registry import get_scraper

    result = TickerResult(ticker=ticker)
    scraper = get_scraper(ticker)
    announcements = await _discover(ticker, lookback_days=args.lookback_days)
    result.discovered = len(announcements)
    if not announcements:
        result.warning = "No recent documents found; verify the source scraper"
    key = _run_key(
        ticker=ticker,
        model=summary_service.active_model_name(),
        prompt=summary_service.active_prompt_version(),
        lookback_days=args.lookback_days,
        maximum=args.max_documents,
    )
    with SessionLocal() as db:
        run, _created = scrape_run_crud.get_or_create_queued_run(
            db,
            ticker=ticker,
            source_url=scraper.source_url,
            idempotency_key=key,
            trigger_type="local_model",
        )
        result.scrape_run_id = str(run.id)
        scrape_run_crud.mark_run_discovery_started(db, run.id)
        run_id = run.id

    work: list[tuple[UUID, Any]] = []
    seen_urls: set[str] = set()
    for announcement in announcements:
        if len(work) >= args.max_documents:
            break
        canonical_url = canonicalize_url(str(announcement.pdf_url))
        if canonical_url in seen_urls:
            result.skipped += 1
            continue
        seen_urls.add(canonical_url)
        source_id_value = announcement.metadata.get("source_id")
        source_id = str(source_id_value) if source_id_value is not None else None
        with SessionLocal() as db:
            artifact, created = scrape_run_crud.get_or_create_artifact(
                db,
                scrape_run_id=run_id,
                canonical_url=canonical_url,
                document_url=str(announcement.pdf_url),
                source_adapter=ticker.lower(),
                source_id=source_id,
                title=announcement.title,
                published_at=_as_utc(announcement.date),
                metadata={
                    **announcement.metadata,
                    "source_url": announcement.source_url,
                    "source_adapter": ticker.lower(),
                    "analysis_provenance": {
                        "environment": "local",
                        "provider": summary_service.active_provider_name(),
                        "model": summary_service.active_model_name(),
                        "prompt_version": summary_service.active_prompt_version(),
                        "publication_status": "pending",
                    },
                },
            )
            artifact_run_id = artifact.scrape_run_id
            completed = artifact.analysis_status == "completed"
            artifact_id = artifact.id
        if not created and artifact_run_id != run_id:
            result.skipped += 1
            continue
        if completed:
            result.skipped += 1
            continue
        work.append((artifact_id, announcement))

    result.selected = len(work)
    with SessionLocal() as db:
        scrape_run_crud.mark_run_discovery_completed(
            db,
            run_id,
            items_found=len(work),
        )

    for artifact_id, announcement in work:
        try:
            await _process_artifact(
                artifact_id=artifact_id,
                announcement=announcement,
                source_adapter=ticker.lower(),
                source_url=scraper.source_url,
            )
            result.inserted += 1
            print(f"{ticker}: stored {announcement.title}")
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            error = _safe_error(exc)
            _mark_artifact_failed(artifact_id, error=error)
            print(
                f"{ticker}: failed {announcement.title}: {error}",
                file=sys.stderr,
            )

    from app.models.artifact import Artifact
    from app.models.artifact_sentiment import ArtifactSentiment
    from app.models.artifact_summary import ArtifactSummary
    from app.models.scrape_run import ScrapeRun

    with SessionLocal() as db:
        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).one()
        artifact_ids = [
            row[0]
            for row in db.query(Artifact.id)
            .filter(Artifact.scrape_run_id == run_id)
            .all()
        ]
        result.run_status = run.status
        result.verified_artifacts = len(artifact_ids)
        result.verified_summaries = (
            db.query(ArtifactSummary)
            .filter(ArtifactSummary.artifact_id.in_(artifact_ids))
            .count()
            if artifact_ids
            else 0
        )
        result.verified_sentiments = (
            db.query(ArtifactSentiment)
            .filter(ArtifactSentiment.artifact_id.in_(artifact_ids))
            .count()
            if artifact_ids
            else 0
        )
    return result


async def _execute(args: argparse.Namespace, tickers: list[str]) -> list[TickerResult]:
    from app.services import summary as summary_service

    summary_service.ensure_provider_available()
    revision = _preflight_database()
    print(f"Remote schema preflight passed at Alembic revision {revision}")
    results = []
    for ticker in tickers:
        results.append(await _execute_ticker(args, ticker=ticker))
    return results


def _configure_environment(args: argparse.Namespace) -> DatabaseTarget | None:
    os.environ["SUMMARY_PROVIDER"] = "ollama"
    os.environ["OLLAMA_BASE_URL"] = args.ollama_url
    os.environ["OLLAMA_MODEL"] = args.model
    os.environ["ANALYSIS_ENVIRONMENT"] = "local"
    if not args.execute:
        return None
    value = os.getenv(args.database_url_env, "")
    if not value:
        raise ValueError(
            f"Set {args.database_url_env} without adding it to backend/.env"
        )
    target = _validate_live_database_url(value, confirmed_host=args.confirm_host)
    os.environ["DATABASE_URL"] = value
    return target


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.lookback_days < 1:
            raise ValueError("--lookback-days must be at least 1")
        if not 1 <= args.max_documents <= 10:
            raise ValueError("--max-documents must be between 1 and 10")
        tickers = _normalise_tickers(args.tickers)
        target = _configure_environment(args)
        if target:
            print(
                f"Confirmed remote target: host={target.host} "
                f"database={target.database}"
            )
            results = asyncio.run(_execute(args, tickers))
        else:
            print("DRY RUN: no database or model writes will occur")
            results = asyncio.run(_dry_run(args, tickers))
    except Exception as exc:  # noqa: BLE001
        print(f"Population stopped: {_safe_error(exc)}", file=sys.stderr)
        return 1

    print(json.dumps([asdict(result) for result in results], indent=2))
    return 1 if any(result.failed for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
