"""Artifact analysis through its interface, on Postgres.

Each scenario runs the module with the real Postgres records over a
rolled-back session, a fixed sentiment and a scripted LLM, then reads back
what was recorded. The analysis Lambda used to have one private path per
kind of artifact, and its tests patched the steps of each.
"""

import json
import uuid
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.alert_vocabulary import ALERT_SENTIMENT_LABELS
from app.core.config import settings
from app.crud import scrape_run as scrape_run_crud
from app.messages import NotificationMessage
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.services import artifact_summary, scrape_runs
from app.services import sentiment as sentiment_service
from app.services.generation.providers import ScriptedProvider
from app.services.llm_errors import LLMUnavailableError
from app.status import AnalysisStatus, DownloadStatus, ScrapeRunStatus
from lambdas import artifact_analysis
from lambdas.artifact_analysis import (
    AlertSender,
    AlreadyAnalysed,
    Analysed,
    AnalysisPorts,
    FinBertScorer,
    FixedSentiment,
    SentimentScorer,
    Summarised,
    SummaryUnavailable,
    analyse_downloaded_document,
    analyse_stored_document,
    analyse_stored_text,
    deployed_ports,
    repair_missing_summaries,
    sqs_alert_sender,
    summarise,
)
from lambdas.artifact_analysis_records import PostgresAnalysisRecords
from lambdas.common import PermanentDocumentError
from lambdas.download_validation import DownloadedDocument, validated_document
from lambdas.raw_documents import InMemoryBucket, RawDocumentStore, locate

HALF_YEAR_REPORT = "Half year report for the six months ended 31 December 2025."
DIVIDEND_NOTICE = (
    "The board declared a dividend of 83 cents per share. "
    "Record date 10 March 2026. Payment date 2 April 2026."
)
ANNOUNCEMENT_ANSWER = {
    "summary": "CSL reported higher half year revenue.",
    "about": "The report covers CSL's half year results.",
    "changed": "Revenue increased.",
    "matters": "Higher revenue may support earnings.",
    "confirmed_facts": ["Revenue increased."],
    "speculation": ["Earnings may rise next year."],
    "claim_evidence": [],
}
NEWS_ANSWER = {
    "summary": "BHP reported higher copper production.",
    "about": "The story covers BHP's quarterly copper output.",
    "changed": "Reported production increased.",
    "matters": "The increase may affect revenue expectations.",
}
DISCUSSION_ANSWER = {
    "summary": "The author expects BHP earnings to rise.",
    "about": "The post discusses BHP earnings.",
    "changed": "The author claims the outlook improved.",
    "matters": "The claim may affect investor expectations.",
}


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"Database is not available: {exc}")
    connection = engine.connect()
    transaction = connection.begin()
    # The Lambda's sessions do not autoflush. Nor does this.
    session = sessionmaker(bind=connection, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture()
def store() -> RawDocumentStore:
    return RawDocumentStore(InMemoryBucket("raw-documents"))


def _ports(
    db: Session,
    *answers: dict | str | Exception,
    scorer: SentimentScorer | None = None,
    documents: RawDocumentStore | None = None,
    alerts: AlertSender | None = None,
) -> AnalysisPorts:
    """Ports over the test session: each answer is scripted in order."""
    return AnalysisPorts(
        records=PostgresAnalysisRecords(lambda: nullcontext(db)),
        scorer=scorer or FixedSentiment("positive", confidence=0.9, model="test-finbert"),
        documents=documents,
        provider=ScriptedProvider(
            [json.dumps(answer) if isinstance(answer, dict) else answer for answer in answers]
        ),
        alerts=alerts,
    )


def _artifact(db: Session, **values) -> Artifact:
    artifact = Artifact(content_hash=f"analysis-{uuid.uuid4()}", **values)
    db.add(artifact)
    db.commit()
    return artifact


def _news(db: Session, **values) -> Artifact:
    return _artifact(
        db,
        **{
            "source_type": "news",
            "artifact_type": "news_article",
            "title": "BHP lifts copper output",
            "raw_text": "BHP reported an increase in quarterly copper production.",
            "artifact_metadata": {
                "provider": "marketaux",
                "source_name": "Example News",
                "feed_eligible": True,
            },
            **values,
        },
    )


def _post(db: Session, **values) -> Artifact:
    return _artifact(
        db,
        **{
            "source_type": "reddit",
            "artifact_type": "reddit_post",
            "title": "$BHP earnings outlook",
            "raw_text": "I think profit will rise next year.",
            "artifact_metadata": {"feed_eligible": True},
            **values,
        },
    )


ELIGIBLE = {
    "feed_eligible": True,
    "eligibility_confidence": 0.94,
    "reason": "The item contains substantive company-specific financial information.",
}
INELIGIBLE = {
    "feed_eligible": False,
    "eligibility_confidence": 0.98,
    "reason": "The item is casual chatter without useful financial information.",
}


def _pipeline_announcement(db: Session, *, title: str = "CSL half year results"):
    """A scrape run that discovered one announcement, not yet downloaded."""
    requested = scrape_runs.request_scrape_run(
        db,
        ticker="CSL",
        idempotency_key=f"analysis:{uuid.uuid4()}",
        send=lambda _message: None,
    )
    run = scrape_run_crud.get_scrape_run(db, requested.scrape_run_id)
    document_url = f"https://investors.csl.com/pdf/{uuid.uuid4()}.pdf"
    artifact, _created = scrape_run_crud.get_or_create_artifact(
        db,
        scrape_run_id=run.id,
        canonical_url=document_url,
        document_url=document_url,
        source_adapter="csl",
        source_id=f"analysis-{uuid.uuid4()}",
        title=title,
    )
    scrape_run_crud.mark_run_discovery_started(db, run.id)
    scrape_run_crud.mark_run_discovery_completed(db, run.id, items_found=1)
    scrape_run_crud.mark_artifact_download_started(db, artifact.id)
    return run, artifact


def _document(artifact: Artifact, text: str = HALF_YEAR_REPORT) -> DownloadedDocument:
    return validated_document(
        text.encode(),
        declared_content_type="text/plain",
        final_url=artifact.document_url,
        max_bytes=4096,
    )


def _put(store: RawDocumentStore, artifact: Artifact, text: str = HALF_YEAR_REPORT):
    return store.put(ticker="CSL", artifact_id=artifact.id, document=_document(artifact, text))


def _local_announcement(db: Session, document_url: str) -> Artifact:
    """An announcement the local loader found, with no scrape run."""
    return _artifact(
        db,
        source_type="asx_announcement",
        artifact_type="asx_announcement_other",
        source_adapter="csl",
        title="CSL half year results",
        raw_text="",
        document_url=document_url,
        artifact_metadata={},
    )


def _stored_document(
    db: Session,
    store: RawDocumentStore,
    *,
    title: str = "CSL half year results",
    text: str = HALF_YEAR_REPORT,
):
    """A scrape run whose one announcement the download stage has stored."""
    run, artifact = _pipeline_announcement(db, title=title)
    stored = _put(store, artifact, text)
    scrape_run_crud.mark_artifact_stored(db, artifact.id, **stored.artifact_fields())
    return run, artifact, stored


def _rows(db: Session, model, artifact: Artifact) -> list:
    return list(db.scalars(select(model).where(model.artifact_id == artifact.id)))


def test_a_news_story_is_summarised_with_the_news_prompt_and_recorded(
    db_session: Session,
) -> None:
    story = _news(db_session)
    ports = _ports(db_session, NEWS_ANSWER)

    outcome = analyse_stored_text(story.id, ports)

    db_session.refresh(story)
    assert outcome == Analysed(
        artifact_id=story.id,
        run_id=None,
        source_type="news",
        source_adapter=None,
        category="news_article",
        page_count=1,
        classification=None,
        summarised=True,
    )
    [call] = ports.provider.calls
    assert call.prompt.startswith("You are summarising a financial news story")
    assert "Source:\nExample News" in call.prompt
    assert ports.scorer.scored == [
        "BHP lifts copper output\n\n"
        "BHP reported an increase in quarterly copper production."
    ]
    assert story.analysis_status == AnalysisStatus.COMPLETED
    assert story.analyzed_at is not None
    assert story.artifact_type == "news_article"
    assert story.artifact_metadata["category"] == "news_article"
    assert story.artifact_metadata["category_confidence"] == 1.0
    assert story.artifact_metadata["provider"] == "marketaux"
    assert artifact_summary.read(story) == artifact_summary.from_answer(
        NEWS_ANSWER,
        model="scripted:test-model",
        prompt_version="llm-news-summary-v2",
    )
    assert len(_rows(db_session, ArtifactSummary, story)) == 1
    [sentiment] = _rows(db_session, ArtifactSentiment, story)
    assert (sentiment.sentiment_label, sentiment.model_used) == ("positive", "test-finbert")


def test_a_discussion_post_uses_the_discussion_prompt_with_its_source_type(
    db_session: Session,
) -> None:
    post = _post(db_session)
    ports = _ports(db_session, DISCUSSION_ANSWER)

    outcome = analyse_stored_text(post.id, ports)

    db_session.refresh(post)
    assert outcome.category == "user_discussion"
    [call] = ports.provider.calls
    assert call.prompt.startswith("You are summarising one public discussion post")
    assert "Source type:\nreddit" in call.prompt
    assert call.prompt.endswith("I think profit will rise next year.")
    assert post.artifact_metadata["category"] == "user_discussion"
    assert artifact_summary.read(post).prompt_version == "llm-public-discussion-summary-v2"


def test_an_eligible_candidate_is_assessed_before_it_is_summarised(
    db_session: Session,
) -> None:
    story = _news(
        db_session,
        artifact_metadata={"provider": "marketaux", "source_name": "Example News"},
    )
    ports = _ports(db_session, ELIGIBLE, NEWS_ANSWER)

    outcome = analyse_stored_text(story.id, ports)

    db_session.refresh(story)
    assert outcome.summarised is True
    assert len(ports.provider.calls) == 2
    assert ports.provider.calls[0].prompt.startswith(
        "You are deciding whether one candidate belongs"
    )
    assert ports.provider.calls[1].prompt.startswith(
        "You are summarising a financial news story"
    )
    assert story.artifact_metadata["feed_eligible"] is True
    assert story.artifact_metadata["eligibility_confidence"] == 0.94
    assert story.artifact_metadata["feed_eligibility_prompt_version"] == (
        "llm-feed-eligibility-v2"
    )


def test_an_ineligible_candidate_is_completed_without_summary_or_sentiment(
    db_session: Session,
) -> None:
    story = _news(
        db_session,
        artifact_metadata={"provider": "marketaux", "source_name": "Example News"},
    )
    ports = _ports(db_session, INELIGIBLE)

    outcome = analyse_stored_text(story.id, ports)

    db_session.refresh(story)
    assert outcome.summarised is False
    assert story.analysis_status == AnalysisStatus.COMPLETED
    assert story.artifact_metadata["feed_eligible"] is False
    assert story.artifact_metadata["eligibility_reason"] == INELIGIBLE["reason"]
    assert ports.scorer.scored == []
    assert _rows(db_session, ArtifactSummary, story) == []
    assert _rows(db_session, ArtifactSentiment, story) == []


def test_an_unmatched_reddit_post_is_rejected_without_calling_the_llm(
    db_session: Session,
) -> None:
    post = _post(db_session, artifact_metadata={})
    ports = _ports(db_session)

    outcome = analyse_stored_text(post.id, ports)

    db_session.refresh(post)
    assert outcome.summarised is False
    assert post.artifact_metadata["feed_eligible"] is False
    assert post.artifact_metadata["eligibility_confidence"] == 1.0
    assert ports.provider.calls == []
    assert ports.scorer.scored == []


def test_a_low_confidence_acceptance_is_excluded(db_session: Session) -> None:
    story = _news(
        db_session,
        artifact_metadata={"provider": "marketaux", "source_name": "Example News"},
    )
    uncertain = {
        "feed_eligible": True,
        "eligibility_confidence": 0.5,
        "reason": "The item may be relevant.",
    }

    analyse_stored_text(story.id, _ports(db_session, uncertain))

    db_session.refresh(story)
    assert story.artifact_metadata["feed_eligible"] is False
    assert story.artifact_metadata["eligibility_reason"].startswith(
        "Low-confidence eligibility decision:"
    )
    assert _rows(db_session, ArtifactSummary, story) == []


def test_an_unavailable_eligibility_assessment_stays_retryable(
    db_session: Session,
) -> None:
    story = _news(
        db_session,
        artifact_metadata={"provider": "marketaux", "source_name": "Example News"},
    )

    with pytest.raises(RuntimeError, match="eligibility assessment is unavailable"):
        analyse_stored_text(
            story.id,
            _ports(db_session, LLMUnavailableError("Amazon Bedrock is disabled")),
        )

    db_session.refresh(story)
    assert story.analysis_status == AnalysisStatus.ANALYZING
    assert story.artifact_metadata["feed_eligibility_status"] == "unavailable"
    assert "feed_eligible" not in story.artifact_metadata
    assert _rows(db_session, ArtifactSummary, story) == []
    assert _rows(db_session, ArtifactSentiment, story) == []


def test_a_post_without_a_title_is_untitled_for_the_summary_and_finbert(
    db_session: Session,
) -> None:
    post = _post(db_session, title=None)
    ports = _ports(db_session, DISCUSSION_ANSWER)

    analyse_stored_text(post.id, ports)

    [call] = ports.provider.calls
    assert "Untitled public discussion" in call.prompt
    assert ports.scorer.scored == [
        "Untitled public discussion\n\nI think profit will rise next year."
    ]


def test_a_post_with_only_a_title_is_analysed_from_its_title(db_session: Session) -> None:
    post = _post(db_session, raw_text="  ")
    ports = _ports(db_session, DISCUSSION_ANSWER)

    analyse_stored_text(post.id, ports)

    db_session.refresh(post)
    assert ports.scorer.scored == ["$BHP earnings outlook\n\n$BHP earnings outlook"]
    assert post.raw_text == "$BHP earnings outlook"


def test_with_no_llm_switched_on_the_sentiment_is_recorded_without_a_summary(
    db_session: Session,
) -> None:
    story = _news(db_session)

    outcome = analyse_stored_text(
        story.id,
        _ports(db_session, LLMUnavailableError("Amazon Bedrock is disabled")),
    )

    db_session.refresh(story)
    assert outcome.summarised is False
    assert story.analysis_status == AnalysisStatus.COMPLETED
    assert _rows(db_session, ArtifactSummary, story) == []
    assert len(_rows(db_session, ArtifactSentiment, story)) == 1


def test_an_answer_without_text_records_the_sentiment_only(db_session: Session) -> None:
    story = _news(db_session)

    outcome = analyse_stored_text(
        story.id,
        _ports(db_session, {key: "" for key in artifact_summary.TEXT_LINES}),
    )

    db_session.refresh(story)
    assert outcome.summarised is False
    assert story.analysis_status == AnalysisStatus.COMPLETED
    assert artifact_summary.read(story) is None
    assert len(_rows(db_session, ArtifactSentiment, story)) == 1


def test_a_failed_llm_call_is_raised_and_leaves_the_analysis_open(
    db_session: Session,
) -> None:
    story = _news(db_session)

    with pytest.raises(RuntimeError, match="invocation failed"):
        analyse_stored_text(
            story.id,
            _ports(db_session, RuntimeError("Amazon Bedrock model invocation failed")),
        )

    db_session.refresh(story)
    assert story.analysis_status == AnalysisStatus.ANALYZING
    assert _rows(db_session, ArtifactSentiment, story) == []


def test_a_completed_artifact_is_not_analysed_again(db_session: Session) -> None:
    story = _news(db_session, analysis_status=AnalysisStatus.COMPLETED)
    ports = _ports(db_session)

    outcome = analyse_stored_text(story.id, ports)

    assert outcome == AlreadyAnalysed(artifact_id=story.id, run_id=None)
    assert ports.scorer.scored == []
    assert ports.provider.calls == []


@pytest.mark.parametrize(
    ("values", "code"),
    [
        (
            {"source_type": "asx_announcement", "artifact_type": "asx_announcement_other"},
            "artifact_identity_mismatch",
        ),
        ({"title": " ", "raw_text": ""}, "no_extractable_text"),
    ],
    ids=["announcement", "no_text"],
)
def test_stored_text_that_cannot_be_analysed_fails_permanently(
    db_session: Session,
    values: dict,
    code: str,
) -> None:
    artifact = _post(db_session, **values)

    with pytest.raises(PermanentDocumentError) as error:
        analyse_stored_text(artifact.id, _ports(db_session))

    assert error.value.code == code
    db_session.refresh(artifact)
    assert artifact.analysis_status == AnalysisStatus.PENDING


def test_an_artifact_that_does_not_exist_is_not_found(db_session: Session) -> None:
    with pytest.raises(PermanentDocumentError) as error:
        analyse_stored_text(uuid.uuid4(), _ports(db_session))

    assert error.value.code == "artifact_not_found"


def test_a_stored_announcement_is_read_classified_summarised_and_recorded(
    db_session: Session,
    store: RawDocumentStore,
) -> None:
    run, artifact, stored = _stored_document(db_session, store)
    alerts: list[NotificationMessage] = []
    ports = _ports(db_session, ANNOUNCEMENT_ANSWER, documents=store, alerts=alerts.append)

    outcome = analyse_stored_document(stored.location, ports)

    db_session.refresh(artifact)
    db_session.refresh(run)
    assert isinstance(outcome, Analysed)
    assert (outcome.category, outcome.page_count, outcome.summarised) == (
        "HalfYearResults",
        1,
        True,
    )
    assert outcome.classification.primary_category == "half_year_results"
    [call] = ports.provider.calls
    assert call.prompt.startswith("You are summarising an official ASX announcement")
    assert "Detected category:\nHalfYearResults" in call.prompt
    assert ports.scorer.scored == [f"CSL half year results\n\n{HALF_YEAR_REPORT}"]
    assert artifact.raw_text == HALF_YEAR_REPORT
    assert artifact.analysis_status == AnalysisStatus.COMPLETED
    assert artifact.artifact_metadata["classification"]["primary_category"] == (
        "half_year_results"
    )
    assert {
        key: artifact.artifact_metadata[key]
        for key in ("category", "extracted_data", "page_count", "document_format")
    } == {
        "category": "HalfYearResults",
        "extracted_data": {},
        "page_count": 1,
        "document_format": "txt",
    }
    assert artifact_summary.read(artifact) == artifact_summary.from_answer(
        ANNOUNCEMENT_ANSWER,
        model="scripted:test-model",
        prompt_version="llm-announcement-summary-v4",
    )
    assert (run.status, run.items_analyzed) == (ScrapeRunStatus.COMPLETED, 1)
    assert alerts == [
        NotificationMessage(
            artifact_id=artifact.id,
            ticker="CSL",
            scrape_run_id=run.id,
            sentiment_label="positive",
            confidence_score=0.9,
        )
    ]


def test_an_announcement_announced_before_its_download_is_recorded_is_reconciled(
    db_session: Session,
    store: RawDocumentStore,
) -> None:
    run, artifact = _pipeline_announcement(db_session)
    stored = _put(store, artifact)

    analyse_stored_document(
        stored.location,
        _ports(db_session, ANNOUNCEMENT_ANSWER, documents=store),
    )

    db_session.refresh(artifact)
    db_session.refresh(run)
    assert (artifact.download_status, artifact.s3_key) == (
        DownloadStatus.STORED,
        stored.location.key,
    )
    assert artifact.analysis_status == AnalysisStatus.COMPLETED
    assert (run.items_downloaded, run.items_analyzed) == (1, 1)


def _untrusted(notification: str, store: RawDocumentStore, stored, artifact: Artifact):
    """What an untrusted notification names, given an object stored for another artifact."""
    key = stored.location.key
    other_id = str(stored.location.artifact_id)
    if notification == "another_bucket":
        return locate("someone-elses-bucket", key)
    if notification == "another_ticker":
        return locate(store.name, key.replace("/CSL/", "/BHP/"))
    if notification == "unknown_artifact":
        return locate(store.name, key.replace(other_id, str(uuid.uuid4())))
    # An object under this artifact's key whose metadata names the other one.
    forged_key = key.replace(other_id, str(artifact.id))
    store.bucket.objects[forged_key] = store.bucket.objects[key]
    return locate(store.name, forged_key)


@pytest.mark.parametrize(
    ("notification", "code"),
    [
        ("another_bucket", "unexpected_bucket"),
        ("another_ticker", "artifact_identity_mismatch"),
        ("unknown_artifact", "artifact_not_found"),
        ("forged_object", "artifact_identity_mismatch"),
    ],
)
def test_a_notification_that_cannot_be_trusted_records_nothing(
    db_session: Session,
    store: RawDocumentStore,
    notification: str,
    code: str,
) -> None:
    _run, artifact = _pipeline_announcement(db_session)
    _other_run, other = _pipeline_announcement(db_session)
    location = _untrusted(notification, store, _put(store, other), artifact)
    ports = _ports(db_session, documents=store)

    with pytest.raises(PermanentDocumentError) as error:
        analyse_stored_document(location, ports)

    assert error.value.code == code
    for untouched in (artifact, other):
        db_session.refresh(untouched)
        assert (untouched.download_status, untouched.analysis_status) == (
            DownloadStatus.DOWNLOADING,
            AnalysisStatus.PENDING,
        )
    assert ports.scorer.scored == []


@pytest.mark.parametrize(
    ("title", "text", "artifact_type"),
    [
        ("Interim Dividend", DIVIDEND_NOTICE, "dividend_announcement"),
        ("CSL half year results", HALF_YEAR_REPORT, "asx_announcement_other"),
        (
            "Product launch",
            "The company launched a new product for enterprise customers.",
            "asx_announcement_other",
        ),
    ],
    ids=["dividend", "category_without_its_own_type", "unclassified"],
)
def test_an_announcement_is_stored_under_its_categorys_artifact_type(
    db_session: Session,
    store: RawDocumentStore,
    title: str,
    text: str,
    artifact_type: str,
) -> None:
    _run, artifact, stored = _stored_document(db_session, store, title=title, text=text)

    analyse_stored_document(
        stored.location,
        _ports(db_session, ANNOUNCEMENT_ANSWER, documents=store),
    )

    db_session.refresh(artifact)
    assert artifact.artifact_type == artifact_type


def test_a_completed_announcement_is_not_analysed_again(
    db_session: Session,
    store: RawDocumentStore,
) -> None:
    _run, artifact, stored = _stored_document(db_session, store)
    analyse_stored_document(
        stored.location,
        _ports(db_session, ANNOUNCEMENT_ANSWER, documents=store),
    )
    ports = _ports(db_session, documents=store)

    outcome = analyse_stored_document(stored.location, ports)

    assert outcome == AlreadyAnalysed(artifact_id=artifact.id, run_id=artifact.scrape_run_id)
    assert ports.scorer.scored == []


@pytest.mark.parametrize("label", sorted(ALERT_SENTIMENT_LABELS))
def test_every_alertable_sentiment_is_sent_to_alert_delivery(
    db_session: Session,
    store: RawDocumentStore,
    label: str,
) -> None:
    _run, artifact, stored = _stored_document(db_session, store)
    alerts: list[NotificationMessage] = []

    analyse_stored_document(
        stored.location,
        _ports(
            db_session,
            ANNOUNCEMENT_ANSWER,
            scorer=FixedSentiment(label),
            documents=store,
            alerts=alerts.append,
        ),
    )

    assert [(alert.artifact_id, alert.sentiment_label) for alert in alerts] == [
        (artifact.id, label)
    ]


def test_a_sentiment_no_rule_can_match_is_not_sent(
    db_session: Session,
    store: RawDocumentStore,
) -> None:
    _run, _artifact, stored = _stored_document(db_session, store)
    alerts: list[NotificationMessage] = []

    analyse_stored_document(
        stored.location,
        _ports(
            db_session,
            ANNOUNCEMENT_ANSWER,
            scorer=FixedSentiment("unknown"),
            documents=store,
            alerts=alerts.append,
        ),
    )

    assert alerts == []


def test_a_failed_alert_never_fails_the_analysis(
    db_session: Session,
    store: RawDocumentStore,
) -> None:
    _run, artifact, stored = _stored_document(db_session, store)

    def unavailable_queue(_message: NotificationMessage) -> None:
        raise RuntimeError("Notification queue is unavailable")

    outcome = analyse_stored_document(
        stored.location,
        _ports(db_session, ANNOUNCEMENT_ANSWER, documents=store, alerts=unavailable_queue),
    )

    db_session.refresh(artifact)
    assert outcome.alert_error == "RuntimeError"
    assert artifact.analysis_status == AnalysisStatus.COMPLETED


def test_the_sqs_alert_sender_sends_the_notification_contract() -> None:
    client = MagicMock()
    message = NotificationMessage(
        artifact_id=uuid.uuid4(),
        ticker="csl",
        scrape_run_id=uuid.uuid4(),
        sentiment_label="negative",
        confidence_score=0.8,
    )

    sqs_alert_sender("https://sqs.example/notifications", client)(message)

    sent = client.send_message.call_args.kwargs
    body = json.loads(sent["MessageBody"])
    assert sent["QueueUrl"] == "https://sqs.example/notifications"
    assert set(body) == {
        "schema_version",
        "artifact_id",
        "ticker",
        "scrape_run_id",
        "sentiment_label",
        "confidence_score",
    }
    assert NotificationMessage.model_validate(body) == message
    with pytest.raises(RuntimeError, match="not configured"):
        sqs_alert_sender("", client)(message)


@pytest.mark.parametrize("enabled", [True, False])
def test_the_lambda_sends_alerts_only_when_notifications_are_enabled(
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", enabled)
    monkeypatch.setattr(settings, "NOTIFICATION_QUEUE_URL", "https://sqs.example/notifications")
    monkeypatch.setattr(settings, "RAW_DOCUMENT_BUCKET", "raw-documents")

    ports = deployed_ports()

    assert (ports.alerts is not None) is enabled
    assert ports.documents.name == "raw-documents"


def _analysed_announcement(db: Session, *, created_day: int = 1, answer: dict | None = None):
    """An analysed dividend announcement, with its sentiment and, if given, a summary."""
    artifact = _artifact(
        db,
        source_type="asx_announcement",
        artifact_type="dividend_announcement",
        title="Interim Dividend",
        raw_text=DIVIDEND_NOTICE,
        artifact_metadata={
            "category": "DividendAnnouncement",
            "extracted_data": {"payment_date": "2026-04-02"},
        },
        analysis_status=AnalysisStatus.COMPLETED,
        created_at=datetime(2000, 1, created_day, tzinfo=timezone.utc),
    )
    db.add(
        ArtifactSentiment(
            artifact_id=artifact.id,
            sentiment_label="neutral",
            model_used="earlier-finbert",
        )
    )
    if answer is not None:
        artifact_summary.record(
            db,
            artifact,
            artifact_summary.from_answer(
                answer,
                model="bedrock:earlier-model",
                prompt_version="llm-announcement-summary-v2",
            ),
        )
    db.commit()
    return artifact


def _lines_only(answer: dict) -> dict:
    return {key: answer[key] for key in artifact_summary.TEXT_LINES}


def _bedrock(db: Session, *answers: dict) -> AnalysisPorts:
    """Ports whose scripted LLM is named as Bedrock, which the summary repair needs."""
    return replace(
        _ports(db),
        provider=ScriptedProvider(
            [json.dumps(answer) for answer in answers],
            name="bedrock:test-model",
        ),
    )


def test_an_announcement_is_summarised_again_from_its_stored_category_and_fields(
    db_session: Session,
) -> None:
    announcement = _analysed_announcement(db_session)
    ports = _ports(db_session, ANNOUNCEMENT_ANSWER)

    outcome = summarise(announcement.id, ports)

    db_session.refresh(announcement)
    assert outcome == Summarised(
        artifact_id=announcement.id,
        model="scripted:test-model",
        prompt_version="llm-announcement-summary-v4",
        complete=True,
    )
    [call] = ports.provider.calls
    assert "Detected category:\nDividendAnnouncement" in call.prompt
    assert '"payment_date": "2026-04-02"' in call.prompt
    assert artifact_summary.read(announcement) == artifact_summary.from_answer(
        ANNOUNCEMENT_ANSWER,
        model="scripted:test-model",
        prompt_version="llm-announcement-summary-v4",
    )
    [sentiment] = _rows(db_session, ArtifactSentiment, announcement)
    assert (sentiment.sentiment_label, sentiment.model_used) == ("neutral", "earlier-finbert")
    assert announcement.analysis_status == AnalysisStatus.COMPLETED
    assert announcement.artifact_metadata["extracted_data"] == {"payment_date": "2026-04-02"}
    assert ports.scorer.scored == []


@pytest.mark.parametrize(
    ("make", "answer", "opening"),
    [
        (_news, NEWS_ANSWER, "You are summarising a financial news story"),
        (_post, DISCUSSION_ANSWER, "You are summarising one public discussion post"),
    ],
    ids=["news", "discussion"],
)
def test_stored_text_is_summarised_again_with_its_own_prompt(
    db_session: Session,
    make,
    answer: dict,
    opening: str,
) -> None:
    artifact = make(db_session)
    ports = _ports(db_session, answer)

    outcome = summarise(artifact.id, ports)

    db_session.refresh(artifact)
    [call] = ports.provider.calls
    assert call.prompt.startswith(opening)
    assert outcome.complete is True
    assert artifact.analysis_status == AnalysisStatus.PENDING
    assert artifact_summary.read(artifact).about == answer["about"]


def test_with_no_llm_switched_on_nothing_is_summarised(db_session: Session) -> None:
    announcement = _analysed_announcement(db_session)

    outcome = summarise(
        announcement.id,
        _ports(db_session, LLMUnavailableError("Amazon Bedrock is disabled")),
    )

    assert outcome == SummaryUnavailable(
        artifact_id=announcement.id,
        reason="Amazon Bedrock is disabled",
    )
    assert _rows(db_session, ArtifactSummary, announcement) == []


def test_an_answer_without_text_is_not_recorded(db_session: Session) -> None:
    story = _news(db_session)

    outcome = summarise(
        story.id,
        _ports(db_session, {key: "" for key in artifact_summary.TEXT_LINES}),
    )

    assert outcome == SummaryUnavailable(
        artifact_id=story.id,
        reason="The answer from scripted:test-model has no text",
    )
    assert _rows(db_session, ArtifactSummary, story) == []


@pytest.mark.parametrize("raw_text", [None, "", " \n\t\r\n "], ids=["none", "empty", "whitespace"])
def test_an_artifact_without_text_cannot_be_summarised(
    db_session: Session,
    raw_text: str | None,
) -> None:
    story = _news(db_session, raw_text=raw_text)

    with pytest.raises(PermanentDocumentError) as error:
        summarise(story.id, _ports(db_session))

    assert error.value.code == "no_extractable_text"


def test_the_repair_dry_run_lists_the_incomplete_announcements_and_changes_nothing(
    db_session: Session,
) -> None:
    incomplete = _analysed_announcement(db_session, answer=_lines_only(ANNOUNCEMENT_ANSWER))
    _analysed_announcement(db_session, answer=ANNOUNCEMENT_ANSWER)
    ports = _bedrock(db_session)

    result = repair_missing_summaries(apply=False, limit=5, ports=ports)

    assert str(incomplete.id) in result["artifact_ids"]
    assert (result["apply"], result["selected"], result["updated"]) == (
        False,
        len(result["artifact_ids"]),
        0,
    )
    assert artifact_summary.read(incomplete).model == "bedrock:earlier-model"
    assert ports.provider.calls == []


def test_the_repair_summarises_at_most_its_limit_and_reports_what_is_left(
    db_session: Session,
) -> None:
    oldest = [
        _analysed_announcement(db_session, created_day=day, answer=_lines_only(ANNOUNCEMENT_ANSWER))
        for day in (1, 2, 3)
    ]
    ports = _bedrock(db_session, ANNOUNCEMENT_ANSWER, ANNOUNCEMENT_ANSWER)

    result = repair_missing_summaries(apply=True, limit=2, ports=ports)

    assert (result["selected"], result["updated"], result["failed"]) == (2, 2, [])
    assert result["missing_after"] == result["missing_before"] - 2
    assert [artifact_summary.read(artifact).model for artifact in oldest] == [
        "bedrock:test-model",
        "bedrock:test-model",
        "bedrock:earlier-model",
    ]


def test_the_repair_records_only_complete_summaries(db_session: Session) -> None:
    incomplete = _analysed_announcement(db_session, answer=_lines_only(ANNOUNCEMENT_ANSWER))
    unrepaired = _analysed_announcement(
        db_session,
        created_day=2,
        answer=_lines_only(ANNOUNCEMENT_ANSWER),
    )
    complete = _analysed_announcement(db_session, answer=ANNOUNCEMENT_ANSWER)

    result = repair_missing_summaries(
        apply=True,
        limit=5,
        ports=_bedrock(db_session, ANNOUNCEMENT_ANSWER, {**ANNOUNCEMENT_ANSWER, "matters": ""}),
    )

    assert artifact_summary.read(incomplete) == artifact_summary.from_answer(
        ANNOUNCEMENT_ANSWER,
        model="bedrock:test-model",
        prompt_version="llm-announcement-summary-v4",
    )
    assert artifact_summary.read(complete).model == "bedrock:earlier-model"
    assert artifact_summary.read(unrepaired).model == "bedrock:earlier-model"
    assert {
        "artifact_id": str(unrepaired.id),
        "error": "RuntimeError: The generated summary omitted structured summary fields",
    } in result["failed"]
    assert result["missing_after"] == result["missing_before"] - 1


def test_the_repair_lists_an_announcement_whose_answer_has_no_text(
    db_session: Session,
) -> None:
    unrepaired = _analysed_announcement(db_session, answer=_lines_only(ANNOUNCEMENT_ANSWER))
    empty = {
        **{key: "" for key in artifact_summary.TEXT_LINES},
        **{key: [] for key in artifact_summary.CLARITY_LISTS},
    }

    result = repair_missing_summaries(apply=True, limit=1, ports=_bedrock(db_session, empty))

    assert (result["updated"], result["failed"]) == (
        0,
        [
            {
                "artifact_id": str(unrepaired.id),
                "error": "RuntimeError: The answer from bedrock:test-model has no text",
            }
        ],
    )
    assert artifact_summary.read(unrepaired).model == "bedrock:earlier-model"


def test_the_repair_lists_an_announcement_removed_while_it_was_summarised(
    db_session: Session,
) -> None:
    removed = _analysed_announcement(db_session, answer=_lines_only(ANNOUNCEMENT_ANSWER))
    removed_id = removed.id
    ports = _bedrock(db_session, ANNOUNCEMENT_ANSWER)
    answer = ports.provider.complete

    def remove_then_answer(prompt: str, **options) -> str:
        for model in (ArtifactSentiment, ArtifactSummary):
            db_session.execute(delete(model).where(model.artifact_id == removed_id))
        db_session.execute(delete(Artifact).where(Artifact.id == removed_id))
        return answer(prompt, **options)

    ports.provider.complete = remove_then_answer

    result = repair_missing_summaries(apply=True, limit=1, ports=ports)

    assert result["updated"] == 0
    assert result["failed"] == [
        {
            "artifact_id": str(removed_id),
            "error": "PermanentDocumentError: Artifact does not exist",
        }
    ]


def test_the_repair_refuses_a_provider_that_is_not_bedrock(db_session: Session) -> None:
    _analysed_announcement(db_session, answer=_lines_only(ANNOUNCEMENT_ANSWER))

    with pytest.raises(RuntimeError, match="requires Amazon Bedrock"):
        repair_missing_summaries(apply=True, limit=1, ports=_ports(db_session))


def test_a_downloaded_document_is_recorded_as_the_worker_records_the_same_bytes(
    db_session: Session,
    store: RawDocumentStore,
) -> None:
    """The local loader read PDFs with pypdf only, kept four summary fields,
    dropped the clarity lists and the prompt version, and set no status."""
    run, stored_copy, stored = _stored_document(db_session, store)
    local = _local_announcement(db_session, stored_copy.document_url)
    worker_ports = _ports(db_session, ANNOUNCEMENT_ANSWER, documents=store)
    alerts: list[NotificationMessage] = []
    loader_ports = _ports(db_session, ANNOUNCEMENT_ANSWER, alerts=alerts.append)

    analyse_stored_document(stored.location, worker_ports)
    outcome = analyse_downloaded_document(local.id, _document(local), loader_ports)

    db_session.refresh(stored_copy)
    db_session.refresh(local)
    db_session.refresh(run)
    assert isinstance(outcome, Analysed)
    assert local.artifact_metadata == stored_copy.artifact_metadata
    assert (local.raw_text, local.artifact_type) == (
        stored_copy.raw_text,
        stored_copy.artifact_type,
    )
    assert artifact_summary.read(local) == artifact_summary.read(stored_copy)
    assert loader_ports.scorer.scored == worker_ports.scorer.scored
    assert loader_ports.provider.calls == worker_ports.provider.calls
    assert (local.analysis_status, local.download_status) == (
        AnalysisStatus.COMPLETED,
        DownloadStatus.PENDING,
    )
    assert run.items_analyzed == 1
    assert alerts == []


def test_a_downloaded_document_already_analysed_is_not_analysed_again(
    db_session: Session,
) -> None:
    local = _local_announcement(db_session, "https://investors.csl.com/pdf/report.pdf")
    analyse_downloaded_document(local.id, _document(local), _ports(db_session, ANNOUNCEMENT_ANSWER))
    ports = _ports(db_session)

    outcome = analyse_downloaded_document(local.id, _document(local), ports)

    assert outcome == AlreadyAnalysed(artifact_id=local.id, run_id=None)
    assert ports.scorer.scored == []


def test_every_path_gives_finbert_the_title_and_text(
    db_session: Session,
    store: RawDocumentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker scored title + raw_text, the admin news route scored the
    uncapped raw_text only and the local loader scored the LLM summary."""
    title = "BHP lifts copper output"
    raw_text = "BHP reported stronger copper production in its quarterly update."
    finbert = MagicMock(
        return_value={
            "sentiment_label": "positive",
            "label": "positive",
            "confidence_score": 0.8,
            "model_used": "test-finbert",
        }
    )
    monkeypatch.setattr(sentiment_service, "analyse_text", finbert)
    story = _news(
        db_session,
        title=title,
        raw_text=raw_text,
        artifact_metadata={
            "summary": "A generated summary that must not be scored.",
            "feed_eligible": True,
        },
    )
    _run, announcement, stored = _stored_document(db_session, store)
    local = _local_announcement(db_session, announcement.document_url)
    ports = _ports(
        db_session,
        NEWS_ANSWER,
        ANNOUNCEMENT_ANSWER,
        ANNOUNCEMENT_ANSWER,
        scorer=FinBertScorer(),
        documents=store,
    )

    analyse_stored_text(story.id, ports)
    analyse_stored_document(stored.location, ports)
    analyse_downloaded_document(local.id, _document(local), ports)

    report = f"CSL half year results\n\n{HALF_YEAR_REPORT}"
    assert [call.args[0] for call in finbert.call_args_list] == [
        f"{title}\n\n{raw_text}",
        report,
        report,
    ]
    [sentiment] = _rows(db_session, ArtifactSentiment, story)
    assert (sentiment.sentiment_label, sentiment.stance, sentiment.model_used) == (
        "positive",
        "positive",
        "test-finbert",
    )
