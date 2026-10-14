"""Artifact analysis through its interface, on Postgres.

Each scenario runs the module with the real Postgres records over a
rolled-back session, a fixed sentiment and a scripted LLM, then reads back
what was recorded. The analysis Lambda used to have one private path per
kind of artifact, and its tests patched the steps of each.
"""

import json
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.services import artifact_summary, news_sentiment
from app.services import sentiment as sentiment_service
from app.services.generation.providers import ScriptedProvider
from app.services.llm_errors import LLMUnavailableError
from app.status import AnalysisStatus
from lambdas.artifact_analysis import (
    AlreadyAnalysed,
    Analysed,
    AnalysisPorts,
    FinBertScorer,
    FixedSentiment,
    SentimentScorer,
    analyse_stored_text,
)
from lambdas.artifact_analysis_records import PostgresAnalysisRecords
from lambdas.common import PermanentDocumentError
from parsing import storage

BACKEND = Path(__file__).resolve().parents[1]
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


def _ports(
    db: Session,
    *answers: dict | str | Exception,
    scorer: SentimentScorer | None = None,
) -> AnalysisPorts:
    """Ports over the test session: each answer is scripted in order."""
    return AnalysisPorts(
        records=PostgresAnalysisRecords(lambda: nullcontext(db)),
        scorer=scorer or FixedSentiment("positive", confidence=0.9, model="test-finbert"),
        provider=ScriptedProvider(
            [json.dumps(answer) if isinstance(answer, dict) else answer for answer in answers]
        ),
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
            "artifact_metadata": {"provider": "marketaux", "source_name": "Example News"},
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
            **values,
        },
    )


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
        category="news_article",
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


def test_every_path_gives_finbert_the_title_and_text(
    db_session: Session,
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
        artifact_metadata={"summary": "A generated summary that must not be scored."},
    )

    analyse_stored_text(story.id, _ports(db_session, NEWS_ANSWER, scorer=FinBertScorer()))
    news_sentiment.analyse_news_artifact_sentiment(MagicMock(), story)
    local_input = storage._artifact_sentiment_text(
        SimpleNamespace(title=title, raw_text=raw_text),
        raw_text,
    )

    expected = f"{title}\n\n{raw_text}"
    assert [call.args[0] for call in finbert.call_args_list] == [expected, expected]
    assert local_input == expected
    [sentiment] = _rows(db_session, ArtifactSentiment, story)
    assert (sentiment.sentiment_label, sentiment.stance, sentiment.model_used) == (
        "positive",
        "positive",
        "test-finbert",
    )


def test_importing_the_analysis_handler_builds_no_settings() -> None:
    """The Lambda imports its handler before it loads DATABASE_URL from SSM."""
    loaded = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, lambdas.analysis, lambdas.artifact_analysis; "
            "print(sorted({'app.core.config', 'app.database.connection'} & set(sys.modules)))",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )

    assert loaded.stdout.strip() == "[]"
