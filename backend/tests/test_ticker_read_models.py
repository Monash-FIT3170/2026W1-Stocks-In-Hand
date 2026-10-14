"""A ticker's read-models, read on Postgres.

The brief, the news feed and the deep dive read each artifact's summary
through the artifact summary module: the brief story and clarity, each
news-feed item's card and the deep-dive detail. An artifact with no summary
shows nothing in their place, never placeholder sentences or its raw text.
A fixed quote source stands in for Yahoo.

Ticker sentiment reads what the analysis worker stored: the latest signal
and the sentiment of each bucket. Neither runs FinBERT, so both answer with
torch and transformers impossible to import, as in the API image.
"""

# pylint: disable=redefined-outer-name

import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.routes import category_sentiment
from app.api.routes import ticker as ticker_route
from app.core.config import settings
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.ticker import Ticker
from app.read_models import ticker_sentiment
from app.read_models.ticker_records import TickerNotFound
from app.schemas.public_discussion import PublicDiscussionSource
from app.services import artifact_summary
from app.services.artifact_summary import Summary
from app.services.public_discussion import PUBLIC_DISCUSSION_SOURCE_TYPES
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
BUCKETS = {"revenue", "strategy", "risk", "dividend", "organisational", "user_discussion"}


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
def without_model_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make torch and transformers impossible to import, as they are in the API image."""
    for name in ("torch", "transformers"):
        monkeypatch.setitem(sys.modules, name, None)


@contextmanager
def _statements(db: Session) -> Iterator[list[str]]:
    """The SQL statements the session sends inside the block."""
    statements: list[str] = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", record)


def _ticker(db: Session) -> Ticker:
    ticker = Ticker(
        symbol=f"T{uuid.uuid4().hex[:8].upper()}",
        company_name="Ticker Read Model Test Limited",
        exchange="ASX",
    )
    db.add(ticker)
    db.commit()
    return ticker


def _artifact(db: Session, ticker: Ticker | None, *, day: int = 1, **values) -> Artifact:
    values.setdefault("source_type", "asx_announcement")
    values.setdefault("artifact_type", "asx_announcement_other")
    values.setdefault("title", f"Update {day}")
    values.setdefault("published_at", datetime(2040, 1, day, tzinfo=timezone.utc))
    artifact = Artifact(
        ticker_id=ticker.id if ticker else None,
        raw_text=RAW_TEXT,
        content_hash=f"ticker-read-model-{uuid.uuid4()}",
        **values,
    )
    db.add(artifact)
    db.commit()
    return artifact


def _post(db: Session, ticker: Ticker, **values) -> Artifact:
    """A Reddit post linked to the ticker only by a mention, as collection links them."""
    values.setdefault("source_type", "reddit")
    values.setdefault("artifact_type", "reddit_post")
    post = _artifact(db, None, **values)
    db.add(
        ArtifactTickerMention(
            artifact_id=post.id,
            ticker_id=ticker.id,
            match_method="ticker_symbol",
            match_confidence=0.95,
            matched_text=ticker.symbol,
        )
    )
    db.commit()
    return post


def _analyse(
    db: Session,
    artifact: Artifact,
    label: str,
    confidence: float | None = 0.9,
    *,
    analysed_day: int = 1,
) -> None:
    db.add(
        ArtifactSentiment(
            artifact_id=artifact.id,
            sentiment_label=label,
            confidence_score=confidence,
            model_used="ProsusAI/finbert",
            created_at=datetime(2040, 2, analysed_day, tzinfo=timezone.utc),
        )
    )
    db.commit()


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


@pytest.mark.usefixtures("without_model_runtime")
def test_the_brief_shows_the_latest_signal(db_session: Session) -> None:
    ticker = _ticker(db_session)
    _analyse(db_session, _artifact(db_session, ticker, day=2), "positive", 0.91, analysed_day=4)

    overview = _overview(db_session, ticker)

    assert overview["sentiment_status"] == "available"
    assert overview["sentiment_label"] == "Generally Positive"
    assert overview["latest_signal_confidence_pct"] == "91%"
    assert overview["latest_signal_model"] == "ProsusAI/finbert"
    assert datetime.fromisoformat(overview["latest_signal_analyzed_at"]) == datetime(
        2040, 2, 4, tzinfo=timezone.utc
    )


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


@pytest.mark.usefixtures("without_model_runtime")
def test_category_sentiment_groups_stored_analysis_by_bucket(db_session: Session) -> None:
    ticker = _ticker(db_session)
    filing = _artifact(
        db_session,
        ticker,
        title=f"{ticker.symbol} revenue increased",
        artifact_metadata={"about": "Revenue increased during the half year."},
    )
    _analyse(db_session, filing, "positive", 0.86)
    _analyse(db_session, _post(db_session, ticker, title="Investors discuss it"), "neutral", 0.71)

    result = ticker_sentiment.read_category_sentiment(db_session, ticker.symbol.lower())

    assert result.ticker == ticker.symbol
    assert result.status == "partial"
    assert result.model_used == "ProsusAI/finbert"
    assert set(result.categories) == BUCKETS
    revenue = result.categories["revenue"]
    assert (revenue.available, revenue.sentiment_label) == (True, "positive")
    assert revenue.summary == (
        f"{ticker.symbol} revenue increased Revenue increased during the half year."
    )
    assert result.categories["user_discussion"].sentiment_label == "neutral"
    risk = result.categories["risk"]
    assert (risk.available, risk.sentiment_label) == (False, None)


@pytest.mark.usefixtures("without_model_runtime")
def test_without_stored_analysis_every_bucket_is_unavailable(db_session: Session) -> None:
    ticker = _ticker(db_session)
    _artifact(db_session, ticker)

    result = ticker_sentiment.read_category_sentiment(db_session, ticker.symbol)

    assert result.status == "unavailable"
    assert result.model_used is None
    assert all(not bucket.available for bucket in result.categories.values())
    assert all(bucket.sentiment_label is None for bucket in result.categories.values())


def test_a_post_linked_only_by_a_mention_is_public_discussion(db_session: Session) -> None:
    ticker = _ticker(db_session)
    published_at = datetime.now(timezone.utc) - timedelta(days=2)
    post = _post(
        db_session,
        ticker,
        source_type="mastodon",
        artifact_type="mastodon_post",
        title=f"Investors discuss {ticker.symbol}",
        url="https://aus.social/@investor/123",
        published_at=published_at,
    )
    _analyse(db_session, post, "positive")

    discussion = ticker_sentiment.read_category_sentiment(
        db_session, ticker.symbol
    ).categories["user_discussion"]

    assert discussion.available is True
    assert discussion.sentiment_label == "positive"
    assert discussion.sources_count == 1
    assert discussion.sources == [
        PublicDiscussionSource(
            source_type="mastodon",
            title=f"Investors discuss {ticker.symbol}",
            url="https://aus.social/@investor/123",
            published_at=published_at,
        )
    ]


def test_the_window_counts_back_from_publication_else_collection(db_session: Session) -> None:
    ticker = _ticker(db_session)
    now = datetime.now(timezone.utc)
    long_ago = now - timedelta(days=400)
    for artifact in (
        _artifact(db_session, ticker, title="Dividend declared", published_at=long_ago),
        _artifact(
            db_session, ticker, title="Dividend paid", published_at=None, created_at=long_ago
        ),
        _artifact(
            db_session,
            ticker,
            title="Dividend reinvestment plan",
            published_at=None,
            created_at=now - timedelta(days=3),
        ),
    ):
        _analyse(db_session, artifact, "positive")

    dividend = ticker_sentiment.read_category_sentiment(
        db_session, ticker.symbol
    ).categories["dividend"]

    assert [source.title for source in dividend.sources] == ["Dividend reinvestment plan"]


def test_a_symbol_with_its_exchange_suffix_is_the_same_ticker(db_session: Session) -> None:
    ticker = _ticker(db_session)

    result = ticker_sentiment.read_category_sentiment(db_session, f"{ticker.symbol.lower()}.ax")

    assert result.ticker == ticker.symbol


def test_an_unknown_ticker_is_not_found(db_session: Session) -> None:
    with pytest.raises(TickerNotFound):
        ticker_sentiment.read_category_sentiment(db_session, "NOT-A-TICKER")
    with pytest.raises(HTTPException) as error:
        category_sentiment.get_ticker_category_sentiments("NOT-A-TICKER", db=db_session)

    assert error.value.status_code == 404


@pytest.mark.usefixtures("without_model_runtime")
def test_the_latest_signal_is_each_tickers_newest_analysed_sentiment(
    db_session: Session,
) -> None:
    first, second, quiet = _ticker(db_session), _ticker(db_session), _ticker(db_session)
    _analyse(db_session, _artifact(db_session, first, day=1), "negative", 0.6, analysed_day=1)
    _analyse(db_session, _artifact(db_session, first, day=2), "positive", 0.91, analysed_day=3)
    _analyse(db_session, _artifact(db_session, second, day=1), "neutral", 0.7, analysed_day=2)
    _analyse(db_session, _post(db_session, first), "negative", 0.99, analysed_day=9)
    _artifact(db_session, quiet)
    ticker_ids = [first.id, second.id, quiet.id]

    with _statements(db_session) as statements:
        signals = ticker_sentiment.latest_signals(db_session, ticker_ids)

    assert len(statements) == 1
    assert {ticker_id: signal.sentiment_label for ticker_id, signal in signals.items()} == {
        first.id: "positive",
        second.id: "neutral",
    }
    assert signals[first.id].confidence_score == pytest.approx(0.91)
    assert signals[first.id].model_used == "ProsusAI/finbert"
    assert signals[first.id].analyzed_at == datetime(2040, 2, 3, tzinfo=timezone.utc)


def _unsaved(
    title: str,
    *,
    source_type: str = "asx_announcement",
    artifact_type: str = "asx_announcement_other",
    **metadata,
) -> Artifact:
    return Artifact(
        id=uuid.uuid4(),
        source_type=source_type,
        artifact_type=artifact_type,
        title=title,
        artifact_metadata=metadata,
    )


def _stored(label: str, confidence: float | None) -> ArtifactSentiment:
    return ArtifactSentiment(
        sentiment_label=label,
        confidence_score=confidence,
        model_used="ProsusAI/finbert",
    )


@pytest.mark.parametrize("source_type", sorted(PUBLIC_DISCUSSION_SOURCE_TYPES))
def test_public_discussion_has_a_bucket_of_its_own(source_type: str) -> None:
    post = _unsaved("Dividend talk", source_type=source_type, artifact_type="reddit_post")

    assert ticker_sentiment.buckets_for(post) == ("user_discussion",)


def test_security_notifications_are_not_filed_under_risk() -> None:
    notice = _unsaved(
        "Notification regarding unquoted securities - CSL",
        artifact_type="security_notification",
        category="SecurityNotification",
    )

    assert "risk" not in ticker_sentiment.buckets_for(notice)


@pytest.mark.parametrize(
    ("title", "bucket"),
    [
        ("Cyber security incident update", "risk"),
        ("Impairment of goodwill", "risk"),
        ("Dividends declared for the half year", "dividend"),
        ("Appointment of directors", "organisational"),
        ("Share buy-back completed", "dividend"),
        ("Profit declined in the quarter", "risk"),
    ],
)
def test_keywords_match_whole_words_and_their_inflections(title: str, bucket: str) -> None:
    assert bucket in ticker_sentiment.buckets_for(_unsaved(title))


def test_keywords_do_not_match_inside_other_words() -> None:
    preview = _unsaved("Investor day preview and asterisked notes")

    assert ticker_sentiment.buckets_for(preview) == ("strategy",)


def test_missing_or_zero_confidence_adds_no_weight() -> None:
    artifact = _unsaved("Half year results")
    rows = [
        (artifact, _stored("positive", 0.9)),
        (artifact, _stored("negative", 0)),
        (artifact, _stored("negative", None)),
    ]

    result = ticker_sentiment.aggregate_bucket("revenue", rows)

    assert result.sentiment_label == "positive"
    assert result.distribution == {"positive": 1.0, "neutral": 0.0, "negative": 0.0}


def test_rows_without_any_confidence_are_counted_equally() -> None:
    artifact = _unsaved("Half year results")
    rows = [
        (artifact, _stored("negative", None)),
        (artifact, _stored("negative", 0)),
        (artifact, _stored("positive", None)),
    ]

    result = ticker_sentiment.aggregate_bucket("revenue", rows)

    assert result.sentiment_label == "negative"
    assert result.distribution["negative"] == pytest.approx(0.6667, abs=1e-4)
