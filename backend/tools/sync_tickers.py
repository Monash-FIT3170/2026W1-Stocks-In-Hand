"""Keep every copy of the ticker list outside Python in step with the catalogue.

The frontend's static ticker pages, the CloudFront route function and the
weekly schedule defaults cannot import ``app.sources``, so they hold copies.
This tool rewrites those copies from the catalogue, and the deployment
contract tests fail when one is out of date.

    python -m tools.sync_tickers          # rewrite the copies
    python -m tools.sync_tickers --check  # exit 1 if any copy is stale

Only the standard library is used: the queue-wiring CI job runs the check
with just pytest and PyYAML installed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from app.sources import SOURCES, scheduled_tickers

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_TICKERS = Path("frontend/src/app/ticker/tickers.json")
TEMPLATE = Path("infra/template.yaml")
DEPLOY_WORKFLOW = Path(".github/workflows/deploy-staging.yml")


@dataclass(frozen=True)
class TickerCopy:
    """One place outside Python that repeats part of the ticker list.

    ``pattern`` must match exactly once, and its ``value`` group is the copy.
    """

    path: Path
    description: str
    pattern: re.Pattern[str]
    value: str


def _copies() -> list[TickerCopy]:
    every_ticker = list(SOURCES)
    scheduled = ",".join(scheduled_tickers())
    return [
        TickerCopy(
            FRONTEND_TICKERS,
            "static ticker pages",
            re.compile(r"\A(?P<value>.*)\Z", re.DOTALL),
            json.dumps(every_ticker, indent=2) + "\n",
        ),
        TickerCopy(
            TEMPLATE,
            "CloudFront ticker route",
            re.compile(r"var tickerRoute = /\^\\/ticker\\/\((?P<value>[^)]*)\)"),
            "|".join(every_ticker),
        ),
        TickerCopy(
            TEMPLATE,
            "ScheduledTickers default",
            re.compile(
                r"^  ScheduledTickers:\n    Type: String\n    Default: (?P<value>\S+)$",
                re.MULTILINE,
            ),
            scheduled,
        ),
        TickerCopy(
            DEPLOY_WORKFLOW,
            "manual deploy scheduled_tickers default",
            re.compile(
                r"^      scheduled_tickers:\n(?:        .*\n)*?"
                r"        default: \"(?P<value>[^\"]*)\"$",
                re.MULTILINE,
            ),
            scheduled,
        ),
        TickerCopy(
            DEPLOY_WORKFLOW,
            "automatic deploy ScheduledTickers fallback",
            re.compile(r"ScheduledTickers (?P<value>[A-Z0-9,]+)\)"),
            scheduled,
        ),
    ]


def _match(copy: TickerCopy, text: str) -> re.Match[str]:
    matches = list(copy.pattern.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one {copy.description} in {copy.path}, found {len(matches)}"
        )
    return matches[0]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def stale_copies(root: Path = REPOSITORY_ROOT) -> list[str]:
    """Describe every copy that differs from the catalogue."""
    stale = []
    for copy in _copies():
        current = _match(copy, _read(root / copy.path))["value"]
        if current != copy.value:
            stale.append(f"{copy.path} ({copy.description}): {current!r} != {copy.value!r}")
    return stale


def write_copies(root: Path = REPOSITORY_ROOT) -> list[Path]:
    """Rewrite the stale copies and return the files that changed."""
    changed: list[Path] = []
    for copy in _copies():
        path = root / copy.path
        text = _read(path)
        match = _match(copy, text)
        updated = text[: match.start("value")] + copy.value + text[match.end("value") :]
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            if copy.path not in changed:
                changed.append(copy.path)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report stale copies and exit 1")
    args = parser.parse_args(argv)
    if args.check:
        stale = stale_copies()
        for line in stale:
            print(f"stale: {line}")
        return 1 if stale else 0
    for path in write_copies():
        print(f"updated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
