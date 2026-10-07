"""The routes that generate on request, on Postgres with a scripted LLM.

The admin summary and category routes, and the investor Reddit digest, call
the structured generation module directly. They record the model and prompt
version it reports, and answer 503 when no LLM is switched on.
"""

import json
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.api.routes import llm, reddit
from app.core.config import settings
from app.models.artifact import Artifact
from app.models.artifact_summary import ArtifactSummary
from app.models.ticker import Ticker
from app.services.generation import providers
from app.services.generation.providers import ScriptedProvider
from app.services.llm_errors import LLMUnavailableError

ANNOUNCEMENT_SUMMARY = {
    "summary": "The company confirmed its dividend timetable.",
    "about": "The filing explains dividend timing.",
    "changed": "The payment date was confirmed.",
    "matters": "Investors can plan income timing.",
    "confirmed_facts": ["The payment date is 2 January 2040."],
    "speculation": ["The dividend may affect future income expectations."],
}
NEWS_SUMMARY = {
    "summary": "BHP reported higher copper production.",
    "about": "The story covers BHP's quarterly copper output.",
    "changed": "Reported production increased.",
    "matters": "The increase may affect revenue expectations.",
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
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture()
def scripted(monkeypatch: pytest.MonkeyPatch):
    def install(*responses: str | Exception) -> ScriptedProvider:
        provider = ScriptedProvider(list(responses))
        monkeypatch.setattr(providers, "configured_provider", lambda: provider)
        return provider

    return install


def _bhp(db: Session) -> Ticker:
    return db.scalars(select(Ticker).where(Ticker.symbol == "BHP")).one()


def _artifact(db: Session, **values) -> Artifact:
    artifact = Artifact(
        content_hash=f"test-{uuid.uuid4()}",
        published_at=datetime.now(timezone.utc) - timedelta(days=1),
        **values,
    )
    db.add(artifact)
    db.commit()
    return artifact


def _announcement(db: Session) -> Artifact:
    return _artifact(
        db,
        source_type="asx_announcement",
        artifact_type="dividend_announcement",
        ticker_id=_bhp(db).id,
        title="Dividend update",
        raw_text="The company confirmed a dividend payment date.",
        artifact_metadata={
            "category": "DividendAnnouncement",
            "extracted_data": {"payment_date": "2040-01-02"},
        },
    )


def _reddit_post(db: Session, title: str, engagement: int) -> Artifact:
    return _artifact(
        db,
        source_type="reddit",
        artifact_type="reddit_post",
        ticker_id=_bhp(db).id,
        title=title,
        raw_text=f"{title} body",
        artifact_metadata={"score": engagement, "engagement": engagement},
    )


def _summary_row(db: Session, artifact: Artifact) -> ArtifactSummary:
    return db.scalars(
        select(ArtifactSummary).where(ArtifactSummary.artifact_id == artifact.id)
    ).one()


def test_artifact_summary_records_the_model_and_prompt_version(
    db_session: Session,
    scripted,
) -> None:
    artifact = _announcement(db_session)
    provider = scripted(json.dumps(ANNOUNCEMENT_SUMMARY))

    result = llm.summarise_artifact(artifact_id=artifact.id, db=db_session)

    row = _summary_row(db_session, artifact)
    assert (row.model_used, row.prompt_version) == (
        "scripted:test-model",
        "llm-announcement-summary-v3",
    )
    assert result["prompt_version"] == "llm-announcement-summary-v3"
    assert result["confirmed_facts"] == ANNOUNCEMENT_SUMMARY["confirmed_facts"]
    assert artifact.artifact_metadata["speculation"] == ANNOUNCEMENT_SUMMARY["speculation"]
    assert '"payment_date": "2040-01-02"' in provider.calls[0].prompt


def test_a_news_artifact_is_summarised_with_the_news_prompt(
    db_session: Session,
    scripted,
) -> None:
    artifact = _artifact(
        db_session,
        source_type="news",
        artifact_type="news_article",
        title="BHP production story",
        raw_text="BHP reported an increase in quarterly copper production.",
        artifact_metadata={"source_name": "Example News"},
    )
    provider = scripted(json.dumps(NEWS_SUMMARY))

    result = llm.summarise_artifact(artifact_id=artifact.id, db=db_session)

    assert result["about"] == NEWS_SUMMARY["about"]
    assert _summary_row(db_session, artifact).prompt_version == "llm-news-summary-v2"
    [call] = provider.calls
    assert call.prompt.startswith("You are summarising a financial news story")
    assert "Example News" in call.prompt


def test_ticker_summaries_skip_artifacts_already_summarised(
    db_session: Session,
    scripted,
) -> None:
    pending = _announcement(db_session)
    _artifact(
        db_session,
        source_type="asx_announcement",
        artifact_type="asx_announcement_other",
        ticker_id=_bhp(db_session).id,
        title="Already summarised",
        raw_text="Text.",
        artifact_metadata={"about": "Done.", "confirmed_facts": [], "speculation": []},
    )
    scripted(json.dumps(ANNOUNCEMENT_SUMMARY))

    result = llm.summarise_ticker_artifacts("BHP", db=db_session)

    assert (result["processed"], result["skipped"], result["errors"]) == (1, 1, [])
    assert _summary_row(db_session, pending).model_used == "scripted:test-model"


def test_category_split_reports_the_model(db_session: Session, scripted) -> None:
    _announcement(db_session)
    scripted(
        json.dumps(
            {
                "revenue": "",
                "strategy": "",
                "risk": "",
                "dividend": "A dividend date was confirmed.",
                "organisational": "",
            }
        )
    )

    result = llm.categorise_recent_artifacts("BHP", db=db_session)

    assert result["model_used"] == "scripted:test-model"
    assert result["categories"]["dividend"] == "A dividend date was confirmed."


def test_reddit_digest_summarises_the_most_engaging_posts(
    db_session: Session,
    scripted,
) -> None:
    _reddit_post(db_session, "BHP quiet week", engagement=2)
    _reddit_post(db_session, "BHP iron ore outlook", engagement=40)
    provider = scripted(
        json.dumps(
            {
                "summary": "Investors debate iron ore demand.",
                "dominant_sentiment": "Mixed",
                "key_themes": ["iron ore"],
            }
        )
    )

    result = reddit.reddit_ticker_sentiment("bhp", db=db_session, _investor=None)

    assert result["summary"] == "Investors debate iron ore demand."
    assert result["dominant_sentiment"] == "mixed"
    assert result["post_count"] == 2
    assert [post["title"] for post in result["posts_used"]] == [
        "BHP iron ore outlook",
        "BHP quiet week",
    ]
    assert "1. [40 upvotes] BHP iron ore outlook" in provider.calls[0].prompt


@pytest.mark.parametrize(
    "route",
    ["summarise_artifact", "summarise_ticker", "categorise", "reddit_digest"],
)
def test_routes_answer_503_when_no_llm_is_on(
    db_session: Session,
    scripted,
    route: str,
) -> None:
    artifact = _announcement(db_session)
    _reddit_post(db_session, "BHP iron ore outlook", engagement=40)
    scripted(LLMUnavailableError("Amazon Bedrock is disabled"))
    call = {
        "summarise_artifact": lambda: llm.summarise_artifact(artifact.id, db=db_session),
        "summarise_ticker": lambda: llm.summarise_ticker_artifacts("BHP", db=db_session),
        "categorise": lambda: llm.categorise_recent_artifacts("BHP", db=db_session),
        "reddit_digest": lambda: reddit.reddit_ticker_sentiment(
            "BHP",
            db=db_session,
            _investor=None,
        ),
    }[route]

    with pytest.raises(HTTPException) as error:
        call()

    assert error.value.status_code == 503
    assert error.value.detail == "Amazon Bedrock is disabled"
