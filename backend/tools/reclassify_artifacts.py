"""Bounded, idempotent command for reclassifying stored raw artifacts."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from parsing.classification import ClassificationInput, classify_document
from parsing.classification_metadata import merge_classification_metadata


MAX_BATCH_SIZE = 500
MAX_ROW_LIMIT = 10_000
CURRENT_CLASSIFIER_VERSION = classify_document(
    ClassificationInput(title="", text="")
).classifier_version


@dataclass(frozen=True)
class ReclassificationOptions:
    """Validated safety bounds and filters for one command run."""
    dry_run: bool = True
    ticker: str | None = None
    batch_size: int = 100
    limit: int = 1_000

    def __post_init__(self) -> None:
        if not 1 <= self.batch_size <= MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
        if not 1 <= self.limit <= MAX_ROW_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_ROW_LIMIT}")
        if self.ticker:
            object.__setattr__(self, "ticker", self.ticker.strip().upper())


@dataclass
class ReclassificationSummary:
    """Observable outcome counts printed by the command."""
    scanned: int = 0
    changed: int = 0
    unchanged: int = 0
    ambiguous: int = 0
    unknown: int = 0
    failed: int = 0

    def add(self, other: "ReclassificationSummary") -> None:
        """Accumulate one committed or dry-run batch summary."""
        for field in asdict(self):
            setattr(self, field, getattr(self, field) + getattr(other, field))


def _ticker_symbol(artifact: Any) -> str | None:
    ticker = getattr(artifact, "ticker", None)
    symbol = getattr(ticker, "symbol", None)
    return str(symbol).upper() if symbol else None


def _filename(artifact: Any, metadata: dict[str, Any]) -> str | None:
    stored = metadata.get("filename")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    document_url = getattr(artifact, "document_url", None)
    if isinstance(document_url, str) and document_url:
        name = PurePosixPath(unquote(urlparse(document_url).path)).name
        if name:
            return name
    s3_key = getattr(artifact, "s3_key", None)
    if isinstance(s3_key, str) and s3_key:
        return PurePosixPath(s3_key).name
    return None


def _stored_version(metadata: dict[str, Any]) -> str | None:
    classification = metadata.get("classification")
    if not isinstance(classification, dict):
        return None
    version = classification.get("classifier_version")
    return str(version) if version else None


def reclassify_records(
    artifacts: Iterable[Any],
    options: ReclassificationOptions,
) -> ReclassificationSummary:
    """Reclassify an already selected bounded set without other analysis work."""
    summary = ReclassificationSummary()
    for artifact in artifacts:
        if summary.scanned >= options.limit:
            break
        if options.ticker and _ticker_symbol(artifact) != options.ticker:
            continue
        raw_text = getattr(artifact, "raw_text", None)
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue

        summary.scanned += 1
        existing = (
            artifact.artifact_metadata
            if isinstance(getattr(artifact, "artifact_metadata", None), dict)
            else {}
        )
        if _stored_version(existing) == CURRENT_CLASSIFIER_VERSION:
            summary.unchanged += 1
            continue
        try:
            result = classify_document(
                ClassificationInput(
                    title=str(getattr(artifact, "title", None) or ""),
                    text=raw_text,
                    filename=_filename(artifact, existing),
                    source_type=getattr(artifact, "source_type", None),
                    source_adapter=getattr(artifact, "source_adapter", None),
                )
            )
            updated = merge_classification_metadata(existing, result)
            if updated == existing:
                summary.unchanged += 1
            else:
                summary.changed += 1
                if not options.dry_run:
                    artifact.artifact_metadata = updated
            if result.status == "needs_review":
                summary.ambiguous += 1
            elif result.status == "unknown":
                summary.unknown += 1
        except Exception:  # pylint: disable=broad-exception-caught
            summary.failed += 1
    return summary


def _select_batch(
    db,
    *,
    ticker: str | None,
    after_id,
    batch_size: int,
):
    from sqlalchemy import func  # pylint: disable=import-outside-toplevel

    from app.models.artifact import Artifact  # pylint: disable=import-outside-toplevel
    from app.models.ticker import Ticker  # pylint: disable=import-outside-toplevel

    stored_version = Artifact.artifact_metadata["classification"][
        "classifier_version"
    ].astext
    query = (
        db.query(Artifact)
        .filter(Artifact.raw_text.isnot(None))
        .filter(Artifact.raw_text != "")
        .filter(func.coalesce(stored_version, "") != CURRENT_CLASSIFIER_VERSION)
    )
    if ticker:
        query = query.join(Ticker).filter(func.upper(Ticker.symbol) == ticker)
    if after_id is not None:
        query = query.filter(Artifact.id > after_id)
    return query.order_by(Artifact.id).limit(batch_size).all()


def run_reclassification(db, options: ReclassificationOptions) -> ReclassificationSummary:
    """Select and update older classifications in bounded transactions."""
    summary = ReclassificationSummary()
    after_id = None
    while summary.scanned < options.limit:
        batch_limit = min(options.batch_size, options.limit - summary.scanned)
        artifacts = _select_batch(
            db,
            ticker=options.ticker,
            after_id=after_id,
            batch_size=batch_limit,
        )
        if not artifacts:
            break
        batch_options = ReclassificationOptions(
            dry_run=options.dry_run,
            ticker=options.ticker,
            batch_size=options.batch_size,
            limit=batch_limit,
        )
        batch_summary = reclassify_records(artifacts, batch_options)
        if not options.dry_run:
            try:
                db.commit()
            except Exception:  # pylint: disable=broad-exception-caught
                db.rollback()
                batch_summary.failed += batch_summary.changed
                batch_summary.changed = 0
        summary.add(batch_summary)
        after_id = artifacts[-1].id
        if len(artifacts) < batch_limit:
            break
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reclassify existing raw artifacts without rerunning analysis"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", dest="dry_run")
    mode.add_argument("--apply", action="store_false", dest="dry_run")
    parser.add_argument("--ticker")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=1_000)
    return parser


def main() -> int:
    """Parse command options, run bounded reclassification and print JSON."""
    args = _parser().parse_args()
    try:
        options = ReclassificationOptions(
            dry_run=args.dry_run,
            ticker=args.ticker,
            batch_size=args.batch_size,
            limit=args.limit,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    from app.database.connection import (  # pylint: disable=import-outside-toplevel
        SessionLocal,
    )

    db = SessionLocal()
    try:
        summary = run_reclassification(db, options)
    finally:
        db.close()
    print(json.dumps({"dry_run": options.dry_run, **asdict(summary)}, sort_keys=True))
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
