import argparse
import json

from app.database.connection import SessionLocal
from app.services.public_discussion import (
    PUBLIC_DISCUSSION_SOURCE_TYPES,
    backfill_artifact_ticker_mentions,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find ticker mentions in stored public discussion artifacts.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write matches. Without this flag the command is a dry run.",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(PUBLIC_DISCUSSION_SOURCE_TYPES),
        help="Limit the run to one source. Repeat for more than one source.",
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--offset", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with SessionLocal() as db:
        result = backfill_artifact_ticker_mentions(
            db,
            source_types=args.source,
            limit=args.limit,
            offset=args.offset,
            execute=args.execute,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
