"""Bounded, idempotent command for tagging stored artifacts with content topics.

The analysis worker tags each artifact it analyses. This command tags the
ones analysed before content topics existed, or tagged by an older version,
in bounded batches. It reads only analysed artifacts with text that were not
excluded from the feed, and it changes nothing but their topics, topic
clusters and topic metadata.

A dry run asks no LLM: it lists how many artifacts it would tag and what the
rules alone would find. ``--llm`` tags through the configured LLM, at one
call per artifact, so it is capped at ``MAX_LLM_LIMIT`` artifacts a run.

Artifacts are tagged oldest published first, so each topic cluster grows in
the order its developments happened.

    cd backend
    python -m tools.tag_content_topics --dry-run --ticker CSL
    python -m tools.tag_content_topics --apply --ticker CSL --limit 200
    python -m tools.tag_content_topics --apply --llm --limit 50
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_BATCH_SIZE = 200
MAX_ROW_LIMIT = 10_000
MAX_LLM_LIMIT = 200


@dataclass(frozen=True)
class TaggingOptions:
    """Validated safety bounds and filters for one command run."""

    dry_run: bool = True
    ticker: str | None = None
    batch_size: int = 50
    limit: int = 1_000
    llm: bool = False
    # Tag every selected artifact again, whatever version tagged it.
    retag: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.batch_size <= MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
        if not 1 <= self.limit <= MAX_ROW_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_ROW_LIMIT}")
        if self.llm and self.limit > MAX_LLM_LIMIT:
            raise ValueError(f"limit must be at most {MAX_LLM_LIMIT} with --llm")
        if self.ticker:
            object.__setattr__(self, "ticker", self.ticker.strip().upper())


@dataclass
class TaggingSummary:
    """Outcome counts the command prints."""

    selected: int = 0
    tagged: int = 0
    with_topics: int = 0
    without_topics: int = 0
    by_method: dict[str, int] = field(default_factory=dict)
    by_topic: dict[str, int] = field(default_factory=dict)
    failed: list[dict[str, str]] = field(default_factory=list)


def current_versions(*, llm: bool) -> tuple[str, ...]:
    """The versions an artifact already tagged by this run's tagger, or a better one, has."""
    from app.services.generation import TopicTagging  # pylint: disable=import-outside-toplevel
    from parsing.content_topics import RULES_VERSION  # pylint: disable=import-outside-toplevel

    # A rules run does not replace an LLM's topics; an LLM run replaces the rules'.
    return (TopicTagging.prompt_version,) if llm else (RULES_VERSION, TopicTagging.prompt_version)


def select_batch(db, options: TaggingOptions, *, after: tuple[Any, Any] | None, size: int):
    """The next analysed artifacts to tag, oldest published first, after ``after``."""
    # pylint: disable=import-outside-toplevel
    from sqlalchemy import and_, func, or_

    from app.content_topic_vocabulary import TOPICS_VERSION_KEY
    from app.models.artifact import Artifact
    from app.models.ticker import Ticker
    from app.status import AnalysisStatus

    date_value = func.coalesce(Artifact.published_at, Artifact.created_at)
    eligible = Artifact.artifact_metadata["feed_eligible"].as_boolean()
    query = (
        db.query(Artifact)
        .filter(Artifact.analysis_status == AnalysisStatus.COMPLETED)
        .filter(func.btrim(func.coalesce(Artifact.raw_text, "")) != "")
        .filter(or_(eligible.is_(None), eligible.is_(True)))
    )
    if not options.retag:
        stored_version = Artifact.artifact_metadata[TOPICS_VERSION_KEY].astext
        query = query.filter(
            func.coalesce(stored_version, "").notin_(current_versions(llm=options.llm))
        )
    if options.ticker:
        query = query.join(Ticker, Ticker.id == Artifact.ticker_id).filter(
            func.upper(Ticker.symbol) == options.ticker
        )
    if after is not None:
        after_date, after_id = after
        query = query.filter(
            or_(date_value > after_date, and_(date_value == after_date, Artifact.id > after_id))
        )
    return query.order_by(date_value, Artifact.id).limit(size).all()


def run_tagging(db, options: TaggingOptions, *, provider=None) -> TaggingSummary:
    """Select and tag artifacts in bounded, separately committed batches."""
    # pylint: disable=import-outside-toplevel
    from app.services import content_topics

    summary = TaggingSummary()
    methods: Counter[str] = Counter()
    topics: Counter[str] = Counter()
    after = None
    while summary.selected < options.limit:
        size = min(options.batch_size, options.limit - summary.selected)
        artifacts = select_batch(db, options, after=after, size=size)
        if not artifacts:
            break
        last = artifacts[-1]
        after = (last.published_at or last.created_at, last.id)
        for artifact in artifacts:
            summary.selected += 1
            try:
                if options.dry_run:
                    decision = content_topics.decide_topics(
                        content_topics.topic_input(artifact), use_llm=False
                    )
                else:
                    decision = content_topics.tag_artifact(
                        db, artifact, provider=provider, use_llm=options.llm
                    )
            # Continue so one artifact cannot block the batch.
            except Exception as exc:  # pylint: disable=broad-exception-caught
                db.rollback()
                summary.failed.append(
                    {"artifact_id": str(artifact.id), "error": f"{type(exc).__name__}: {exc}"}
                )
                continue
            summary.tagged += 0 if options.dry_run else 1
            methods[decision.method] += 1
            topics.update(record.topic for record in decision.topics)
            if decision.topics:
                summary.with_topics += 1
            else:
                summary.without_topics += 1
        if len(artifacts) < size:
            break
    summary.by_method = dict(sorted(methods.items()))
    summary.by_topic = dict(sorted(topics.items()))
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tag stored artifacts with content topics")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", dest="dry_run")
    mode.add_argument("--apply", action="store_false", dest="dry_run")
    parser.add_argument("--ticker")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--limit", type=int, default=1_000)
    parser.add_argument(
        "--llm",
        action="store_true",
        help=f"tag through the configured LLM, one paid call each, at most {MAX_LLM_LIMIT}",
    )
    parser.add_argument(
        "--retag",
        action="store_true",
        help="tag again artifacts the current version already tagged",
    )
    return parser


def main() -> int:
    """Parse options, run bounded tagging and print a JSON summary."""
    args = _parser().parse_args()
    try:
        options = TaggingOptions(
            dry_run=args.dry_run,
            ticker=args.ticker,
            batch_size=args.batch_size,
            limit=args.limit,
            llm=args.llm,
            retag=args.retag,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    from app.database.connection import SessionLocal  # pylint: disable=import-outside-toplevel

    db = SessionLocal()
    try:
        summary = run_tagging(db, options)
    finally:
        db.close()
    print(json.dumps({**asdict(options), **asdict(summary)}, indent=2, sort_keys=True))
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
