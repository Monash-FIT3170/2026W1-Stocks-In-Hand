"""A ticker's brief, news feed and deep dive, read on Postgres.

Each reads an artifact's summary through the artifact summary module: the
brief story and clarity, each news-feed item's card, and the deep-dive
detail. An artifact with no summary shows nothing in their place, never
placeholder sentences or its raw text. Quotes come from Yahoo at request
time, so a fixed quote source with no quotes stands in for it.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.routes import ticker as ticker_route
from app.core.config import settings
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.services import artifact_summary
from app.services.artifact_summary import Summary
from app.services.quotes import FixedQuotes

ANNOUNCEMENT_ANSWER = {
    "summary": "ANZ confirmed its first-half profit.",
    "about": "The filing reports ANZ's first-half result.",
    "changed": "Net profit rose to $1 billion.",
    "matters": "The result supports the dividend outlook.",
    "confirmed_facts": ["Net profit was $1 billion."],
    "speculation": ["Management expects costs to fall."],
}
NEWS_ANSWER = {
    "summary": "A publisher reported higher copper output.",
    "about": "The story covers the company's copper production.",
    "changed": "Copper output rose.",
    "matters": "Output supports revenue.",
}
RAW_TEXT = "Raw filing text that is not a summary."
UNCLASSIFIED = {"is_classified": False, "confirmed_facts": [], "speculation": []}


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


def _ticker(db: Session) -> Ticker:
    ticker = Ticker(
        symbol=f"T{uuid.uuid4().hex[:8].upper()}",
        company_name="Ticker Route Test Limited",
        exchange="ASX",
    )
    db.add(ticker)
    db.commit()
    return ticker


def _artifact(db: Session, ticker: Ticker, *, day: int, **values) -> Artifact:
    values.setdefault("source_type", "asx_announcement")
    values.setdefault("artifact_type", "asx_announcement_other")
    values.setdefault("title", f"Update {day}")
    artifact = Artifact(
        ticker_id=ticker.id,
        raw_text=RAW_TEXT,
        published_at=datetime(2040, 1, day, tzinfo=timezone.utc),
        content_hash=f"ticker-route-{uuid.uuid4()}",
        **values,
    )
    db.add(artifact)
    db.commit()
    return artifact


def _record(db: Session, artifact: Artifact, answer: dict) -> Summary:
    summary = artifact_summary.from_answer(
        answer,
        model="bedrock:test-model",
        prompt_version="llm-announcement-summary-v3",
    )
    artifact_summary.record(db, artifact, summary)
    db.commit()
    return summary


def _overview(db: Session, ticker: Ticker) -> dict:
    brief = ticker_route.get_ticker_brief(ticker.symbol.lower(), db=db, quotes=FixedQuotes())
    return brief["overview"]


def test_the_brief_tells_the_latest_summary_and_its_clarity(db_session: Session) -> None:
    ticker = _ticker(db_session)
    _record(db_session, _artifact(db_session, ticker, day=2), ANNOUNCEMENT_ANSWER)

    overview = _overview(db_session, ticker)

    assert overview["story"] == ANNOUNCEMENT_ANSWER["about"]
    assert overview["clarity"] == {
        "is_classified": True,
        "confirmed_facts": ANNOUNCEMENT_ANSWER["confirmed_facts"],
        "speculation": ANNOUNCEMENT_ANSWER["speculation"],
    }


def test_the_brief_has_no_story_and_no_clarity_without_a_summary(
    db_session: Session,
) -> None:
    ticker = _ticker(db_session)
    no_records = _overview(db_session, ticker)
    _record(db_session, _artifact(db_session, ticker, day=2), ANNOUNCEMENT_ANSWER)
    _artifact(db_session, ticker, day=3)

    latest_unsummarised = _overview(db_session, ticker)

    for overview in (no_records, latest_unsummarised):
        assert overview["story"] is None
        assert overview["clarity"] == UNCLASSIFIED


def test_the_deep_dive_detail_is_the_recorded_summary_text(db_session: Session) -> None:
    ticker = _ticker(db_session)
    summarised = _artifact(db_session, ticker, day=2, title="Half-year result")
    summary = _record(db_session, summarised, ANNOUNCEMENT_ANSWER)
    _artifact(db_session, ticker, day=3, title="Unsummarised update")

    timeline = {
        event["title"]: event
        for event in ticker_route.get_ticker_deep_dive_timeline(ticker.symbol, db=db_session)
    }

    assert timeline["Half-year result"]["detail"] == summary.text
    assert timeline["Unsummarised update"]["detail"] is None


def test_each_news_feed_item_is_the_artifact_card(db_session: Session) -> None:
    ticker = _ticker(db_session)
    news = _artifact(
        db_session,
        ticker,
        day=2,
        source_type="news",
        artifact_type="news_article",
        title="Copper story",
        url="https://publisher.example/story",
        artifact_metadata={"source_name": "publisher.example"},
    )
    _record(db_session, news, NEWS_ANSWER)
    filing = _artifact(
        db_session,
        ticker,
        day=3,
        title="Operational update",
        url="https://example.test/filing",
    )

    feed = {
        item["id"]: item
        for item in ticker_route.get_ticker_news_feed(ticker.symbol.lower(), db=db_session)
    }
    card_fields = ("tag", "source_name", "source_label", "about", "changed", "matters")

    assert {key: feed[str(news.id)][key] for key in card_fields} == {
        "tag": "News Article",
        "source_name": "publisher.example",
        "source_label": "View original at publisher.example",
        "about": NEWS_ANSWER["about"],
        "changed": NEWS_ANSWER["changed"],
        "matters": NEWS_ANSWER["matters"],
    }
    assert {key: feed[str(filing.id)][key] for key in card_fields} == {
        "tag": "Asx Announcement Other",
        "source_name": "ASX",
        "source_label": "View original ASX filing",
        "about": None,
        "changed": None,
        "matters": None,
    }
    # The raw text is still offered, but only as the original's evidence.
    assert [source["evidence_text"] for source in feed[str(filing.id)]["sources"]] == [RAW_TEXT]
