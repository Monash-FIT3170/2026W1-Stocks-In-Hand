"""Shared status vocabulary for the discovery -> download -> analysis pipeline.

Using these enum members instead of retyped string literals means a typo is a
NameError/AttributeError at import time (or a static-analysis warning)
instead of a comparison that's silently always False and a pipeline stage
that quietly never advances. Members are `str` subclasses (`StrEnum`), so
they compare equal to and serialise as the same plain strings already stored
in the `scrape_runs.status` / `artifacts.download_status` /
`artifacts.analysis_status` columns — no model or migration changes needed.

See `app/crud/scrape_run.py` for the state machine these values drive, and
its module docstring / `app/crud/README.md` for the transition rules.
"""

from enum import StrEnum


class ScrapeRunStatus(StrEnum):
    ENQUEUEING = "enqueueing"
    QUEUED = "queued"
    DISCOVERING = "discovering"
    DOWNLOADING = "downloading"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class DownloadStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    STORED = "stored"
    FAILED = "failed"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# A run in one of these statuses already has forward progress from discovery
# onward, so a new request for the same ticker should attach to the existing
# run instead of enqueueing a duplicate. Shared by main.py's
# POST /scrape/{ticker} route and lambdas/schedule.py's EventBridge producer.
RUN_ACTIVE_OR_FINISHED = frozenset(
    {
        ScrapeRunStatus.QUEUED,
        ScrapeRunStatus.DISCOVERING,
        ScrapeRunStatus.DOWNLOADING,
        ScrapeRunStatus.ANALYZING,
        ScrapeRunStatus.PARTIAL,
        ScrapeRunStatus.COMPLETED,
    }
)

# A run in one of these statuses is at or past the download stage. A late or
# retried discovery-stage update must not regress it back to an earlier
# status. Used by app/crud/scrape_run.py to keep status transitions
# monotonic under SQS's at-least-once delivery.
RUN_DOWNSTREAM_OF_DISCOVERY = frozenset(
    {
        ScrapeRunStatus.DOWNLOADING,
        ScrapeRunStatus.ANALYZING,
        ScrapeRunStatus.PARTIAL,
        ScrapeRunStatus.COMPLETED,
    }
)
