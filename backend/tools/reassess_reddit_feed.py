"""Preview or reassess a bounded batch of legacy Reddit relevance decisions.

Dry-run is the default and makes no LLM calls or database writes. Applying only
changes eligibility metadata; it preserves original links, company associations,
summaries, sentiment, and analysis status.
"""

from __future__ import annotations

import argparse
import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import or_

from app.models.artifact import Artifact
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.ticker import Ticker
from app.services.generation import FeedEligibility
from app.status import AnalysisStatus
from lambdas.artifact_analysis import AnalysisPorts, FixedSentiment, assess_feed_eligibility
from lambdas.artifact_analysis_records import PostgresAnalysisRecords

MAX_LIMIT = 200


def select_candidates(db, *, limit, ticker=None, include_decided=False):
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    decision = Artifact.artifact_metadata["feed_eligible"].as_boolean()
    query = db.query(Artifact).filter(
        Artifact.source_type == "reddit",
        Artifact.analysis_status == AnalysisStatus.COMPLETED,
    )
    if not include_decided:
        query = query.filter(decision.is_(None))
    if ticker:
        symbol = ticker.strip().upper()
        query = query.filter(or_(
            Artifact.ticker.has(Ticker.symbol == symbol),
            Artifact.ticker_mentions.any(ArtifactTickerMention.ticker.has(Ticker.symbol == symbol)),
        ))
    return query.order_by(Artifact.created_at.asc(), Artifact.id.asc()).limit(limit).all()


def run_reassessment(db, *, apply=False, limit=50, ticker=None, include_decided=False, provider=None):
    candidates = select_candidates(db, limit=limit, ticker=ticker, include_decided=include_decided)
    result = {"apply": apply, "selected": len(candidates), "updated": 0, "failed": [], "skipped": [], "records": []}
    records = PostgresAnalysisRecords(lambda: nullcontext(db))
    ports = AnalysisPorts(records=records, scorer=FixedSentiment(label="neutral"), provider=provider)
    for artifact in candidates:
        artifact_id = artifact.id
        result["records"].append({"id": str(artifact_id), "title": artifact.title, "url": artifact.url})
        if not apply:
            continue
        try:
            facts = records.facts(artifact_id)
            if facts is None:
                result["skipped"].append(str(artifact_id))
                continue
            decision = assess_feed_eligibility(
                replace(facts, feed_eligible=None),
                facts.title or "Untitled public discussion",
                facts.raw_text or facts.title or "",
                ports,
            )
            if decision is None:
                raise RuntimeError("Relevance assessment unavailable; no decision changed")
            # Re-read after the LLM call and avoid replacing a concurrent decision.
            current = db.query(Artifact).filter(Artifact.id == artifact_id).populate_existing().with_for_update().one()
            metadata = dict(current.artifact_metadata or {})
            if metadata.get("feed_eligible") != facts.feed_eligible:
                db.rollback()
                result["skipped"].append(str(artifact_id))
                continue
            current.artifact_metadata = {
                **metadata,
                **decision,
                "feed_eligibility_reassessed_at": datetime.now(timezone.utc).isoformat(),
                "feed_eligibility_reassessment_version": FeedEligibility.prompt_version,
            }
            db.commit()
            result["updated"] += 1
        except Exception as exc:  # Continue the bounded batch after one failed assessment.
            db.rollback()
            result["failed"].append({"id": str(artifact_id), "error": type(exc).__name__})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--ticker")
    parser.add_argument("--include-decided", action="store_true", help="Also reassess existing approval/rejection decisions")
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_LIMIT:
        parser.error(f"--limit must be between 1 and {MAX_LIMIT}")
    from app.database.connection import SessionLocal

    with SessionLocal() as db:
        result = run_reassessment(db, apply=args.apply, limit=args.limit, ticker=args.ticker, include_decided=args.include_decided)
    print(json.dumps(result, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
