"""Shared status vocabulary for scrape runs and the artifacts they collect.

Using these enum members instead of retyped string literals means a typo is a
NameError/AttributeError at import time (or a static-analysis warning)
instead of a comparison that's silently always False and a pipeline stage
that quietly never advances. Members are `str` subclasses (`StrEnum`), so
they compare equal to and serialise as the plain strings stored in the
`scrape_runs.status`, `artifacts.download_status` and
`artifacts.analysis_status` columns. CHECK constraints on those columns
(migration `86d9statuschecks`) accept only these values, so a new member
needs a migration too.

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
    # A public discussion collection run between start and finish.
    RUNNING = "running"
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
    # Stored text (news or public discussion) sent to the analysis queue.
    QUEUED = "queued"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# Stored text in one of these statuses must not be sent for analysis again.
ANALYSIS_QUEUED_OR_DONE = frozenset(
    {
        AnalysisStatus.QUEUED,
        AnalysisStatus.ANALYZING,
        AnalysisStatus.COMPLETED,
    }
)

# A run in one of these statuses already has forward progress from discovery
# onward, so a new request for the same ticker should attach to the existing
# run instead of enqueueing a duplicate. Used by app/services/scrape_runs.py,
# which both the API and the EventBridge schedule request runs through.
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
