"""The shared skeleton for one SQS record moving through a pipeline stage.

Discovery, download and analysis each handle a record the same way.
``run_stage`` times the record, logs its outcome, and records a failure
against the scrape run or artifact the record is about (its subject):

- A permanent error (``PermanentDocumentError``) is final. It is recorded and
  the message is acknowledged, so it does not waste dead-letter retries.
- A retryable error records the attempt only, and the message is retried.
- A retryable error on the final receive (``MAX_RECEIVE_COUNT``) is final.

A final failure must be durable before the message is acknowledged, so a
database error while recording one is raised. Recording a retry is best
effort, because the message is retried either way.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from lambdas.common import (
    PermanentDocumentError,
    correlation_id,
    database_session,
    is_final_attempt,
    log_event,
    receive_attempt,
)

# Records an error against the subject inside an open database session.
Transition = Callable[[Any, str], object]


@dataclass(frozen=True)
class StageSubject:
    """The scrape run or artifact a stage records its outcome against."""

    fail: Transition
    record_retry: Transition
    log_fields: Mapping[str, object]
    # Permanent error codes that mean the message cannot be trusted to name
    # this subject. They are logged but never recorded against it.
    untrusted_codes: frozenset[str] = frozenset()


def _scrape_runs():
    # Imported on use: the crud layer reads settings, which database_session()
    # loads from SSM first.
    from app.crud import scrape_run

    return scrape_run


def discovery_run(run_id: UUID) -> StageSubject:
    return StageSubject(
        fail=lambda db, error: _scrape_runs().mark_run_discovery_failed(
            db, run_id, error=error
        ),
        record_retry=lambda db, error: _scrape_runs().record_run_discovery_retry(
            db, run_id, error=error
        ),
        log_fields={"run_id": run_id},
    )


def downloaded_artifact(*, run_id: UUID, artifact_id: UUID) -> StageSubject:
    return StageSubject(
        fail=lambda db, error: _scrape_runs().mark_artifact_download_failed(
            db, artifact_id, error=error
        ),
        record_retry=lambda db, error: _scrape_runs().record_artifact_download_retry(
            db, artifact_id, error=error
        ),
        log_fields={"run_id": run_id, "artifact_id": artifact_id},
        untrusted_codes=frozenset({"artifact_identity_mismatch"}),
    )


_UNTRUSTED_ANALYSIS_EVENT = frozenset(
    {"artifact_identity_mismatch", "artifact_not_found", "unexpected_bucket"}
)


def analysed_document(artifact_id: UUID) -> StageSubject:
    return StageSubject(
        fail=lambda db, error: _scrape_runs().mark_artifact_analysis_failed(
            db, artifact_id, error=error
        ),
        record_retry=lambda db, error: _scrape_runs().record_artifact_analysis_retry(
            db, artifact_id, error=error
        ),
        log_fields={"artifact_id": artifact_id},
        untrusted_codes=_UNTRUSTED_ANALYSIS_EVENT,
    )


def analysed_stored_text(artifact_id: UUID) -> StageSubject:
    """A news or public discussion artifact, analysed from its stored text."""
    return StageSubject(
        fail=lambda db, error: _scrape_runs().mark_inline_artifact_analysis_failed(
            db, artifact_id, error=error
        ),
        record_retry=lambda db, error: _scrape_runs().record_artifact_analysis_retry(
            db, artifact_id, error=error
        ),
        log_fields={"artifact_id": artifact_id},
        untrusted_codes=_UNTRUSTED_ANALYSIS_EVENT,
    )


class StageRecord:
    """One received SQS record, as a stage's work sees it."""

    def __init__(self, stage: str, record: dict) -> None:
        self.stage = stage
        self.record = record
        self.correlation_id = correlation_id(record)
        self.attempt = receive_attempt(record)
        self.started_at = time.monotonic()
        # Set by the work as soon as it knows what the record is about.
        self.subject: StageSubject | None = None

    def log(self, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
        subject_fields = dict(self.subject.log_fields) if self.subject else {}
        log_event(
            stage=self.stage,
            event=event,
            started_at=self.started_at,
            level=level,
            correlation_id=self.correlation_id,
            attempt=self.attempt,
            **{**subject_fields, **fields},
        )


def run_stage(
    stage: str,
    record: dict,
    work: Callable[[StageRecord], None],
) -> None:
    """Run one record's work and record its outcome; raise to retry it."""
    current = StageRecord(stage, record)
    try:
        work(current)
    except PermanentDocumentError as exc:
        subject = current.subject
        if subject is not None and exc.code not in subject.untrusted_codes:
            _record_final(current, subject, f"{exc.code}: {exc}")
        current.log("permanent_failure", level=logging.WARNING, error_code=exc.code)
    except Exception as exc:
        subject = current.subject
        if subject is not None:
            error = f"{type(exc).__name__}: {exc}"
            if is_final_attempt(current.attempt):
                _record_final(current, subject, error)
            else:
                _record_retry(current, subject, error)
        current.log(
            "retryable_failure",
            level=logging.ERROR,
            error_code=type(exc).__name__,
        )
        raise


def _record_final(current: StageRecord, subject: StageSubject, error: str) -> None:
    try:
        with database_session() as db:
            subject.fail(db, error)
    except Exception:
        current.log("state_update_failed", level=logging.ERROR, error_code="database_error")
        # Do not acknowledge a queue message until its failure is durable.
        raise


def _record_retry(current: StageRecord, subject: StageSubject, error: str) -> None:
    try:
        with database_session() as db:
            subject.record_retry(db, error)
    except Exception:  # pylint: disable=broad-exception-caught
        current.log("state_update_failed", level=logging.ERROR, error_code="database_error")
