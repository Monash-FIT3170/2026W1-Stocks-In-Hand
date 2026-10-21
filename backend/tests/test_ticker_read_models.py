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
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
import main
from app.api.routes import category_sentiment
from app.core.config import settings
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.information_platform import InformationPlatform
from app.models.ticker import Ticker
from app.read_models import ticker_brief, ticker_records, ticker_sentiment
from app.read_models.ticker_records import PAGE_RECORDS, TickerNotFound
from app.schemas.public_discussion import PublicDiscussionSource
from app.schemas.ticker_brief import KeyNumber, TickerBrief, TickerOverview
from app.schemas.ticker_records import NewsFeedRecord
from app.services import artifact_summary
from app.services.artifact_summary import Summary
from app.services.public_discussion import PUBLIC_DISCUSSION_SOURCE_TYPES
from app.services.quotes import FixedQuotes, Quote, QuoteSource, live_quotes
from tools import compare_sentiment_buckets

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
UNCLASSIFIED = {"is_classified": False, "confirmed_facts": [], "speculation": [], "traceable_claims": []}
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


def _brief(db: Session, ticker: Ticker, quotes: QuoteSource | None = None) -> TickerBrief:
    return ticker_brief.read_ticker_brief(
        db, ticker.symbol.lower(), quotes=quotes or FixedQuotes()
    )


def _overview(db: Session, ticker: Ticker) -> TickerOverview:
    return _brief(db, ticker).overview


@contextmanager
def _api(db: Session, quotes: QuoteSource | None = None) -> Iterator[TestClient]:
    """The app, reading through the test's session and a fixed quote source."""
    main.app.dependency_overrides[get_db] = lambda: db
    main.app.dependency_overrides[live_quotes] = lambda: quotes or FixedQuotes()
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(live_quotes, None)


@pytest.mark.usefixtures("without_model_runtime")
def test_a_ticker_with_no_records_has_an_empty_brief(db_session: Session) -> None:
    ticker = _ticker(db_session)

    brief = _brief(db_session, ticker)

    overview = brief.overview
    assert (overview.current_price, overview.day_change) == ("N/A", "N/A")
    assert overview.last_updated == "No updates yet"
    assert overview.story is None
    assert (overview.sources, overview.sources_count) == ([], 0)
    assert (overview.sentiment_status, overview.sentiment_label) == ("unavailable", "Unavailable")
    assert overview.latest_signal_confidence_pct == "N/A"
    assert brief.aside.key_numbers == [
        KeyNumber(label="Latest filing", value="No filings yet"),
        KeyNumber(label="Latest type", value="No filings yet"),
    ]
    assert brief.aside.themes == []


def test_the_brief_formats_the_quote_it_asks_for_once(db_session: Session) -> None:
    ticker = _ticker(db_session)
    quotes = FixedQuotes({ticker.symbol: Quote(price=31.25, previous_close=30.0)})

    overview = _brief(db_session, ticker, quotes).overview

    assert (overview.current_price, overview.day_change) == ("$31.25", "+4.17%")
    assert quotes.requested == [ticker.symbol]
    unchanged = FixedQuotes({ticker.symbol: Quote(price=5.0, previous_close=0.0)})
    no_close = _brief(db_session, ticker, unchanged).overview
    assert (no_close.current_price, no_close.day_change) == ("$5.00", "N/A")


def test_the_brief_tells_the_latest_summary_and_its_clarity(db_session: Session) -> None:
    ticker = _ticker(db_session)
    _record(db_session, _artifact(db_session, ticker, day=2), ANNOUNCEMENT_ANSWER)

    overview = _overview(db_session, ticker)

    assert overview.story == ANNOUNCEMENT_ANSWER["about"]
    assert overview.clarity.model_dump() == {
        "is_classified": True,
        "confirmed_facts": ANNOUNCEMENT_ANSWER["confirmed_facts"],
        "speculation": ANNOUNCEMENT_ANSWER["speculation"],
        "traceable_claims": [
            {"text": "Net profit was $1 billion.", "kind": "confirmed_fact", "source": None},
            {"text": "Management expects costs to fall.", "kind": "speculation", "source": None},
        ],
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
        assert overview.story is None
        assert overview.clarity.model_dump() == UNCLASSIFIED


@pytest.mark.usefixtures("without_model_runtime")
def test_the_brief_shows_the_latest_signal(db_session: Session) -> None:
    ticker = _ticker(db_session)
    _analyse(db_session, _artifact(db_session, ticker, day=2), "positive", 0.91, analysed_day=4)

    overview = _overview(db_session, ticker)

    assert overview.sentiment_status == "available"
    assert overview.sentiment_label == "Generally Positive"
    assert overview.latest_signal_confidence_pct == "91%"
    assert overview.latest_signal_model == "ProsusAI/finbert"
    assert datetime.fromisoformat(overview.latest_signal_analyzed_at) == datetime(
        2040, 2, 4, tzinfo=timezone.utc
    )


def test_the_aside_names_the_latest_filing_and_the_kinds_of_record(
    db_session: Session,
) -> None:
    ticker = _ticker(db_session)
    _artifact(db_session, ticker, day=1, artifact_metadata={"category": "DividendAnnouncement"})
    _artifact(db_session, ticker, day=2, source_type="news", artifact_type="news_article")
    _artifact(db_session, ticker, day=3, artifact_metadata={"category": "HalfYearResults"})
    _artifact(db_session, ticker, day=4, artifact_metadata={"category": "HalfYearResults"})

    aside = _brief(db_session, ticker).aside

    assert aside.key_numbers == [
        KeyNumber(label="Latest filing", value="Jan 2040"),
        KeyNumber(label="Latest type", value="Half Year Results"),
    ]
    assert aside.themes == [
        "Half Year Results activity",
        "News Article activity",
        "Dividend Announcement activity",
    ]


def test_the_brief_finds_the_ticker_with_its_exchange_suffix(db_session: Session) -> None:
    ticker = _ticker(db_session)
    quotes = FixedQuotes()

    brief = ticker_brief.read_ticker_brief(db_session, f"{ticker.symbol}.AX", quotes=quotes)

    assert brief.overview.symbol == ticker.symbol
    assert quotes.requested == [ticker.symbol]
    with pytest.raises(TickerNotFound):
        ticker_brief.read_ticker_brief(db_session, "NOT-A-TICKER", quotes=quotes)


def test_the_brief_route_answers_the_brief_schema(db_session: Session) -> None:
    ticker = _ticker(db_session)
    _record(db_session, _artifact(db_session, ticker, url="https://example.test/a"), NEWS_ANSWER)
    quotes = FixedQuotes({ticker.symbol: Quote(price=31.25, previous_close=30.0)})

    with _api(db_session, quotes) as client:
        response = client.get(f"/tickers/symbol/{ticker.symbol}/brief")
        missing = client.get("/tickers/symbol/NOT-A-TICKER/brief")

    assert response.status_code == 200
    brief = response.json()
    assert set(brief["overview"]) == set(TickerOverview.model_fields)
    assert brief["overview"]["current_price"] == "$31.25"
    assert [source["url"] for source in brief["overview"]["sources"]] == ["https://example.test/a"]
    assert [number["label"] for number in brief["aside"]["key_numbers"]] == [
        "Latest filing",
        "Latest type",
    ]
    assert missing.status_code == 404


def test_the_deep_dive_detail_is_the_recorded_summary_text(db_session: Session) -> None:
    ticker = _ticker(db_session)
    summarised = _artifact(db_session, ticker, day=2, title="Half-year result")
    summary = _record(db_session, summarised, ANNOUNCEMENT_ANSWER)
    _artifact(db_session, ticker, day=3, title="Unsummarised update")

    timeline = {
        event.title: event for event in ticker_records.read_deep_dive(db_session, ticker.symbol)
    }

    assert timeline["Half-year result"].detail == summary.text
    assert timeline["Unsummarised update"].detail is None


def test_the_deep_dive_shows_the_ten_newest_records_newest_first(db_session: Session) -> None:
    ticker = _ticker(db_session)
    for day in range(1, 12):
        _artifact(db_session, ticker, day=day)

    timeline = ticker_records.read_deep_dive(db_session, ticker.symbol)

    assert [event.title for event in timeline] == [f"Update {day}" for day in range(11, 1, -1)]
    assert [event.date for event in timeline[:2]] == ["Jan 11, 2040", "Jan 10, 2040"]


@pytest.mark.parametrize("read", [ticker_records.read_news_feed, ticker_records.read_deep_dive])
def test_duplicate_filings_do_not_use_up_the_ten_record_slots(
    db_session: Session,
    read,
) -> None:
    ticker = _ticker(db_session)
    for day in range(1, 13):
        _artifact(db_session, ticker, day=day, url=f"https://example.test/{day}.pdf")
    for _ in range(PAGE_RECORDS):
        _artifact(db_session, ticker, day=12, url="https://example.test/12.pdf")

    records = read(db_session, ticker.symbol)

    assert [record.title for record in records] == [f"Update {day}" for day in range(12, 2, -1)]
    assert len({record.sources[0].url for record in records}) == PAGE_RECORDS


def test_a_duplicate_filing_keeps_its_available_summary(db_session: Session) -> None:
    ticker = _ticker(db_session)
    filing = _artifact(db_session, ticker, day=2, url="https://example.test/result.pdf")
    summary = _record(db_session, filing, ANNOUNCEMENT_ANSWER)
    _artifact(db_session, ticker, day=3, url="https://example.test/result.pdf")

    history = ticker_records.read_deep_dive(db_session, ticker.symbol)
    feed = ticker_records.read_news_feed(db_session, ticker.symbol)

    assert [event.detail for event in history] == [summary.text]
    assert [item.id for item in feed] == [filing.id]


@pytest.mark.parametrize("url_field", ["canonical_url", "document_url"])
def test_a_legacy_filing_and_its_document_url_are_one_record(
    db_session: Session,
    url_field: str,
) -> None:
    ticker = _ticker(db_session)
    url = "https://example.test/result.pdf"
    _artifact(db_session, ticker, day=2, url=url)
    latest = _artifact(db_session, ticker, day=3, **{url_field: url})

    records = ticker_records.recent_artifacts(db_session, ticker.id, limit=PAGE_RECORDS)

    assert [record.id for record in records] == [latest.id]


def test_distinct_documents_and_records_without_links_are_not_duplicates(
    db_session: Session,
) -> None:
    ticker = _ticker(db_session)
    filings = [
        _artifact(
            db_session,
            ticker,
            day=day,
            title="Quarterly update",
            canonical_url="https://example.test/announcements",
            document_url=f"https://example.test/{day}.pdf",
        )
        for day in (1, 2)
    ]
    unlinked = [
        _artifact(db_session, ticker, day=3),
        _artifact(db_session, ticker, day=4, url="", document_url=" "),
    ]

    records = ticker_records.recent_artifacts(db_session, ticker.id, limit=PAGE_RECORDS)

    assert [record.id for record in records] == [
        unlinked[1].id, unlinked[0].id, filings[1].id, filings[0].id
    ]


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
    unnamed = _artifact(
        db_session,
        ticker,
        day=1,
        source_type="news",
        artifact_type="news_article",
        title="Unattributed story",
    )
    filing = _artifact(
        db_session,
        ticker,
        day=3,
        title="Operational update",
        url="https://example.test/filing",
    )

    feed = {item.id: item for item in ticker_records.read_news_feed(db_session, ticker.symbol)}
    card_fields = ("tag", "source_name", "source_label", "about", "changed", "matters")

    assert feed[news.id].model_dump(include=set(card_fields)) == {
        "tag": "News Article",
        "source_name": "publisher.example",
        "source_label": "View original at publisher.example",
        "about": NEWS_ANSWER["about"],
        "changed": NEWS_ANSWER["changed"],
        "matters": NEWS_ANSWER["matters"],
    }
    assert (feed[unnamed.id].source_name, feed[unnamed.id].source_label) == (
        None,
        "View original source",
    )
    assert feed[filing.id].model_dump(include=set(card_fields)) == {
        "tag": "Asx Announcement Other",
        "source_name": "ASX",
        "source_label": "View original ASX filing",
        "about": None,
        "changed": None,
        "matters": None,
    }
    assert (feed[filing.id].ticker, feed[filing.id].time) == (ticker.symbol, "Jan 3, 2040")
    # The raw text is still offered, but only as the original's evidence.
    assert [source.evidence_text for source in feed[filing.id].sources] == [RAW_TEXT]


@pytest.mark.parametrize("read", [ticker_records.read_news_feed, ticker_records.read_deep_dive])
def test_reading_records_runs_the_same_queries_however_many_there_are(
    db_session: Session,
    read,
) -> None:
    counts = []
    for records in (1, PAGE_RECORDS):
        ticker = _ticker(db_session)
        for day in range(1, records + 1):
            platform = InformationPlatform(name=f"Publisher {day}", platform_type="news")
            db_session.add(platform)
            db_session.flush()
            news = _artifact(
                db_session,
                ticker,
                day=day,
                source_type="news",
                artifact_type="news_article",
                platform_id=platform.id,
            )
            _record(db_session, news, NEWS_ANSWER)
        symbol = ticker.symbol
        db_session.expire_all()
        with _statements(db_session) as statements:
            assert len(read(db_session, symbol)) == records
        counts.append(len(statements))

    assert counts[0] == counts[1]


def test_the_record_routes_answer_their_schemas(db_session: Session) -> None:
    ticker = _ticker(db_session)
    _record(db_session, _artifact(db_session, ticker, url="https://example.test/a"), NEWS_ANSWER)

    with _api(db_session) as client:
        feed = client.get(f"/tickers/symbol/{ticker.symbol.lower()}/news-feed")
        history = client.get(f"/tickers/symbol/{ticker.symbol}.AX/deep-dive-timeline")
        missing = client.get("/tickers/symbol/NOT-A-TICKER/news-feed")

    assert feed.status_code == history.status_code == 200
    assert set(feed.json()[0]) == set(NewsFeedRecord.model_fields)
    # The deep dive sends nothing the page does not read: no month, metrics or tone.
    assert set(history.json()[0]) == {"tag", "title", "date", "detail", "sources"}
    assert missing.status_code == 404


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
def test_classified_announcements_count_once_and_news_by_keyword(db_session: Session) -> None:
    ticker = _ticker(db_session)
    dividend = _artifact(
        db_session,
        ticker,
        day=3,
        title="Dividend declared after revenue growth",
        artifact_metadata={"category": "DividendAnnouncement"},
    )
    notice = _artifact(
        db_session,
        ticker,
        day=2,
        title="Notification of issue of securities",
        artifact_type="security_notification",
        artifact_metadata={"category": "SecurityNotification"},
    )
    news = _artifact(
        db_session,
        ticker,
        day=1,
        source_type="news",
        artifact_type="news_article",
        title="Profit rises",
        artifact_metadata={"category": "news_article"},
    )
    for artifact in (dividend, notice, news):
        _analyse(db_session, artifact, "positive")

    categories = ticker_sentiment.read_category_sentiment(db_session, ticker.symbol).categories

    assert {
        bucket: [source.title for source in result.sources]
        for bucket, result in categories.items()
        if result.available
    } == {
        "dividend": ["Dividend declared after revenue growth"],
        "revenue": ["Profit rises"],
    }


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


def test_the_bucket_comparison_lists_what_the_taxonomy_moves(db_session: Session) -> None:
    ticker = _ticker(db_session)
    dividend = _artifact(
        db_session,
        ticker,
        day=4,
        title="Dividend declared after revenue growth",
        artifact_metadata={"category": "DividendAnnouncement"},
    )
    notice = _artifact(
        db_session,
        ticker,
        day=3,
        title="Notification of issue of securities",
        artifact_type="security_notification",
        artifact_metadata={"category": "SecurityNotification"},
    )
    news = _artifact(
        db_session,
        ticker,
        day=2,
        source_type="news",
        artifact_type="news_article",
        title="Profit rises",
        artifact_metadata={"category": "news_article"},
    )
    post = _post(db_session, ticker, title="Holding for the dividend")
    for artifact, label, confidence in (
        (dividend, "positive", 0.9),
        (notice, "neutral", 0.8),
        (news, "negative", 0.6),
        (post, "positive", 0.7),
    ):
        _analyse(db_session, artifact, label, confidence)

    comparison = compare_sentiment_buckets.compare(
        db_session, ticker.symbol, days=365, limit=250
    )

    def counts(buckets: dict) -> dict:
        return {name: bucket.count for name, bucket in buckets.items() if bucket.count}

    assert comparison.analysed == 4
    assert counts(comparison.keyword) == {
        "revenue": 2,
        "strategy": 2,
        "dividend": 1,
        "user_discussion": 1,
    }
    assert counts(comparison.taxonomy) == {"revenue": 1, "dividend": 1, "user_discussion": 1}
    assert comparison.keyword["revenue"].label == "positive"
    assert comparison.taxonomy["revenue"].label == "negative"
    assert comparison.fallback["revenue"] == 1
    report = compare_sentiment_buckets.report(comparison)
    assert (
        "Dividend declared after revenue growth: revenue, strategy, dividend -> dividend"
        in report
    )
    assert "Notification of issue of securities: strategy -> no bucket" in report
    assert "Profit rises" not in report


def test_the_bucket_comparison_counts_only_what_the_view_counts(db_session: Session) -> None:
    ticker = _ticker(db_session)
    for day, label in ((3, "positive"), (2, "mixed")):
        dividend = _artifact(
            db_session,
            ticker,
            day=day,
            title=f"Dividend declared {day}",
            artifact_metadata={"category": "DividendAnnouncement"},
        )
        _analyse(db_session, dividend, label)
    notice = _artifact(
        db_session,
        ticker,
        day=1,
        title="Notification of issue of securities",
        artifact_type="security_notification",
        artifact_metadata={"category": "SecurityNotification"},
    )
    _analyse(db_session, notice, "mixed")
    news = _artifact(
        db_session,
        ticker,
        day=4,
        source_type="news",
        artifact_type="news_article",
        title="Profit rises",
        artifact_metadata={"category": "news_article"},
    )
    _analyse(db_session, news, "mixed")

    comparison = compare_sentiment_buckets.compare(
        db_session, ticker.symbol, days=365, limit=250
    )
    view = ticker_sentiment.read_category_sentiment(db_session, ticker.symbol).categories

    # The view skips a label that is not a sentiment label, so the tool does too.
    assert comparison.analysed == 1
    assert comparison.taxonomy["dividend"].count == view["dividend"].sources_count == 1
    assert comparison.keyword["dividend"].count == 1
    assert comparison.fallback["revenue"] == 0
    assert comparison.moves == []


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
def test_the_latest_signal_is_each_tickers_latest_filing(db_session: Session) -> None:
    first, second, quiet = _ticker(db_session), _ticker(db_session), _ticker(db_session)
    # Analysed for the first time after the newer filing, but published before it.
    _analyse(db_session, _artifact(db_session, first, day=1), "negative", 0.6, analysed_day=9)
    latest = _artifact(db_session, first, day=2)
    _analyse(db_session, latest, "positive", 0.91, analysed_day=3)
    _analyse(db_session, _artifact(db_session, first, day=6), "mixed", 0.8, analysed_day=4)
    news = _artifact(db_session, first, day=5, source_type="news", artifact_type="news_article")
    _analyse(db_session, news, "negative", 0.99, analysed_day=5)
    _analyse(db_session, _post(db_session, first, day=7), "negative", 0.99, analysed_day=9)
    _analyse(db_session, _artifact(db_session, second, day=2), "positive", 0.7)
    collected = datetime(2040, 1, 3, tzinfo=timezone.utc)
    undated = _artifact(db_session, second, published_at=None, created_at=collected)
    _analyse(db_session, undated, "neutral", 0.7)
    quiet_news = _artifact(db_session, quiet, source_type="news", artifact_type="news_article")
    _analyse(db_session, quiet_news, "positive")
    ticker_ids = [first.id, second.id, quiet.id]
    latest_id = latest.id

    with _statements(db_session) as statements:
        signals = ticker_sentiment.latest_signals(db_session, ticker_ids)

    assert len(statements) == 1
    assert {ticker_id: signal.sentiment_label for ticker_id, signal in signals.items()} == {
        first.id: "positive",
        second.id: "neutral",
    }
    assert signals[first.id].artifact_id == latest_id
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
    post = _unsaved(
        "Dividend talk",
        source_type=source_type,
        artifact_type="reddit_post",
        category="user_discussion",
    )

    assert ticker_sentiment.buckets_for(post) == ("user_discussion",)


@pytest.mark.parametrize(
    ("category", "buckets"),
    [
        ("DividendAnnouncement", ("dividend",)),
        ("HalfYearResults", ("revenue",)),
        ("CorporateAction", ("strategy",)),
        ("ExecutiveTranscript", ("strategy",)),
        ("RegulatoryLegal", ("risk",)),
        ("LeadershipChange", ("organisational",)),
        ("SecurityNotification", ()),
    ],
)
def test_a_classified_announcement_counts_in_its_categorys_bucket_alone(
    category: str,
    buckets: tuple[str, ...],
) -> None:
    # The keywords would file this title under three buckets.
    announcement = _unsaved("Dividend, revenue and director update", category=category)

    assert ticker_sentiment.buckets_for(announcement) == buckets


@pytest.mark.parametrize(
    "values",
    [
        {"source_type": "news", "artifact_type": "news_article", "category": "news_article"},
        {"category": "UNKNOWN"},
        {},
        {"category": "financial_results"},
    ],
    ids=["news", "unclassified", "no category", "a name no definition has"],
)
def test_keywords_place_what_the_taxonomy_cannot(values: dict) -> None:
    artifact = _unsaved("Profit rises", **values)

    assert ticker_sentiment.taxonomy_buckets_for(artifact) is None
    assert ticker_sentiment.buckets_for(artifact) == ("revenue",)


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
    assert bucket in ticker_sentiment.buckets_for(_unsaved(title, category="UNKNOWN"))


def test_keywords_do_not_match_inside_other_words() -> None:
    preview = _unsaved("Investor day preview and asterisked notes", category="UNKNOWN")

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
