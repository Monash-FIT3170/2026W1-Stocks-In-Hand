"""Content topics on Postgres: recording, clustering, analysis, reading and tagging.

Each scenario runs over a rolled-back session with a scripted LLM, then reads
back what was recorded or what a page is answered.
"""

# pylint: disable=redefined-outer-name

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
import main
from app.content_topic_vocabulary import (
    CONTENT_TOPICS,
    TOPICS_METHOD_KEY,
    TOPICS_VERSION_KEY,
)
from app.core.config import settings
from app.crud.announcement import get_announcements
from app.crud.content_topic import TopicRecord, record_topics
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.content_topic import (
    ArtifactContentTopic,
    ContentTopicCluster,
    ContentTopicClusterMember,
)
from app.models.ticker import Ticker
from app.read_models import ticker_records, ticker_topics
from app.read_models.ticker_records import TickerNotFound
from app.services import content_topics
from app.services.content_topics import PostgresContentTopics
from app.services.generation.providers import ScriptedProvider
from app.status import AnalysisStatus
from lambdas.artifact_analysis import (
    AnalysisPorts,
    FixedSentiment,
    analyse_stored_text,
)
from lambdas.artifact_analysis_records import PostgresAnalysisRecords
from parsing.content_topics import RULES_VERSION
from tools import tag_content_topics
from tools.tag_content_topics import TaggingOptions

DAY = datetime(2040, 3, 1, tzinfo=timezone.utc)
NOW = datetime(2040, 3, 31, tzinfo=timezone.utc)
NEWS_ANSWER = {
    "summary": "The company faces a class action.",
    "about": "The story covers a shareholder class action.",
    "changed": "A class action was filed.",
    "matters": "Litigation may weigh on the company.",
}
CLASS_ACTION_TEXT = (
    "Shareholders filed a class action in the Federal Court alleging the company "
    "misled the market about its guidance."
)
TOPIC_ANSWER = {
    "topics": [
        {
            "topic": "litigation",
            "confidence": 0.85,
            "passage": "Shareholders filed a class action in the Federal Court",
            "event": "Shareholder class action filed",
        }
    ]
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


def _scope(db: Session):
    return lambda: nullcontext(db)


def _ticker(db: Session) -> Ticker:
    ticker = Ticker(
        symbol=f"T{uuid.uuid4().hex[:8].upper()}",
        company_name="Content Topic Test Limited",
        exchange="ASX",
    )
    db.add(ticker)
    db.commit()
    return ticker


def _artifact(db: Session, ticker: Ticker | None, *, day: int = 1, **values) -> Artifact:
    values.setdefault("source_type", "asx_announcement")
    values.setdefault("artifact_type", "asx_announcement_other")
    values.setdefault("title", f"Update {day}")
    values.setdefault("raw_text", "Raw filing text.")
    values.setdefault("published_at", DAY + timedelta(days=day - 1))
    artifact = Artifact(
        ticker_id=ticker.id if ticker else None,
        content_hash=f"content-topic-{uuid.uuid4()}",
        **values,
    )
    db.add(artifact)
    db.commit()
    return artifact


def _record(
    db: Session,
    artifact: Artifact,
    *records: TopicRecord,
    version: str = RULES_VERSION,
    window_days: int = 14,
) -> list[ContentTopicCluster]:
    clusters = record_topics(
        db,
        artifact,
        records,
        version=version,
        method=records[0].method if records else "rules",
        model=None,
        window_days=window_days,
    )
    db.commit()
    return clusters


def _topic(topic: str, confidence: float = 0.8, *, event: str | None = None) -> TopicRecord:
    return TopicRecord(
        topic=topic,
        confidence=confidence,
        method="rules",
        evidence=f"Evidence for {topic}.",
        event_label=event,
    )


def _rows(db: Session, model, artifact: Artifact) -> list:
    return list(db.scalars(select(model).where(model.artifact_id == artifact.id)))


@contextmanager
def _api(db: Session) -> Iterator[TestClient]:
    main.app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(get_db, None)


# Recording and clustering


def test_recording_stores_each_topic_and_the_tagging_version(db_session: Session) -> None:
    ticker = _ticker(db_session)
    filing = _artifact(db_session, ticker, title="Class action filed")

    [cluster] = _record(db_session, filing, _topic("litigation", event="Class action filed"))

    db_session.refresh(filing)
    [row] = _rows(db_session, ArtifactContentTopic, filing)
    assert (row.topic, row.confidence, row.method, row.version) == (
        "litigation",
        0.8,
        "rules",
        RULES_VERSION,
    )
    assert row.evidence == "Evidence for litigation."
    assert filing.artifact_metadata[TOPICS_VERSION_KEY] == RULES_VERSION
    assert filing.artifact_metadata[TOPICS_METHOD_KEY] == "rules"
    assert (cluster.ticker_id, cluster.topic, cluster.label) == (
        ticker.id,
        "litigation",
        "Class action filed",
    )
    assert cluster.first_published_at == cluster.last_published_at == filing.published_at


def test_artifacts_about_one_development_share_a_cluster(db_session: Session) -> None:
    ticker = _ticker(db_session)
    filing = _artifact(db_session, ticker, day=1, title="Shareholder class action filed")
    story = _artifact(
        db_session,
        ticker,
        day=3,
        source_type="news",
        artifact_type="news_article",
        title="Investors launch class action against miner",
    )
    unrelated = _artifact(db_session, ticker, day=4, title="Contractor dispute")

    [first] = _record(
        db_session, filing, _topic("litigation", event="Shareholder class action filed")
    )
    [second] = _record(
        db_session, story, _topic("litigation", event="Shareholder class action")
    )
    [third] = _record(
        db_session, unrelated, _topic("litigation", event="Contractor payment dispute")
    )

    assert first.id == second.id != third.id
    db_session.refresh(first)
    assert first.last_published_at == story.published_at
    # The newest member's development names the cluster.
    assert first.label == "Shareholder class action"
    members = db_session.scalars(
        select(ContentTopicClusterMember.artifact_id).where(
            ContentTopicClusterMember.cluster_id == first.id
        )
    ).all()
    assert set(members) == {filing.id, story.id}


def test_an_artifact_outside_the_window_starts_a_new_cluster(db_session: Session) -> None:
    ticker = _ticker(db_session)
    early = _artifact(db_session, ticker, day=1, title="Class action filed")
    late = _artifact(db_session, ticker, day=25, title="Class action filed")

    [first] = _record(db_session, early, _topic("litigation"), window_days=14)
    [second] = _record(db_session, late, _topic("litigation"), window_days=14)

    assert first.id != second.id


def test_one_development_under_two_topics_is_two_clusters(db_session: Session) -> None:
    ticker = _ticker(db_session)
    filing = _artifact(db_session, ticker, title="ASIC sues over fees")

    clusters = _record(db_session, filing, _topic("regulation"), _topic("litigation"))

    assert {cluster.topic for cluster in clusters} == {"regulation", "litigation"}
    assert len({cluster.id for cluster in clusters}) == 2


def test_tagging_again_replaces_the_topics_and_memberships(db_session: Session) -> None:
    ticker = _ticker(db_session)
    filing = _artifact(db_session, ticker, title="Class action filed")
    _record(db_session, filing, _topic("litigation"), _topic("regulation"))

    _record(db_session, filing, _topic("litigation", 0.9))

    rows = _rows(db_session, ArtifactContentTopic, filing)
    assert [(row.topic, row.confidence) for row in rows] == [("litigation", 0.9)]
    memberships = _rows(db_session, ContentTopicClusterMember, filing)
    assert len(memberships) == 1
    db_session.refresh(filing)
    assert [topic.topic for topic in filing.content_topics] == ["litigation"]


def test_an_artifact_with_no_ticker_is_recorded_without_a_cluster(db_session: Session) -> None:
    post = _artifact(db_session, None, source_type="reddit", artifact_type="reddit_post")

    clusters = _record(db_session, post, _topic("macro_exposure"))

    assert clusters == []
    assert [row.topic for row in _rows(db_session, ArtifactContentTopic, post)] == [
        "macro_exposure"
    ]
    assert _rows(db_session, ContentTopicClusterMember, post) == []


def test_an_artifact_with_no_topics_still_records_its_tagging_version(db_session: Session) -> None:
    filing = _artifact(db_session, _ticker(db_session))

    assert _record(db_session, filing) == []

    db_session.refresh(filing)
    assert filing.artifact_metadata[TOPICS_VERSION_KEY] == RULES_VERSION
    assert _rows(db_session, ArtifactContentTopic, filing) == []


def test_the_database_refuses_an_unknown_topic(db_session: Session) -> None:
    filing = _artifact(db_session, _ticker(db_session))

    with pytest.raises(IntegrityError, match="ck_artifact_content_topics_topic"):
        with db_session.begin_nested():
            db_session.add(
                ArtifactContentTopic(
                    artifact_id=filing.id,
                    topic="astrology",
                    confidence=0.5,
                    method="rules",
                    version=RULES_VERSION,
                )
            )


# Tagging an artifact


def test_tagging_with_an_llm_records_its_topics_quotation_and_event(db_session: Session) -> None:
    ticker = _ticker(db_session)
    story = _artifact(
        db_session,
        ticker,
        source_type="news",
        artifact_type="news_article",
        title="Miner faces shareholder class action",
        raw_text=CLASS_ACTION_TEXT,
    )
    provider = ScriptedProvider([json.dumps(TOPIC_ANSWER)])

    decision = content_topics.tag_artifact(db_session, story, provider=provider, use_llm=True)

    assert decision.method == "llm"
    [row] = _rows(db_session, ArtifactContentTopic, story)
    assert (row.topic, row.method, row.version, row.model_used) == (
        "litigation",
        "llm",
        "llm-content-topics-v1",
        "scripted:test-model",
    )
    assert row.evidence == "Shareholders filed a class action in the Federal Court"
    assert row.event_label == "Shareholder class action filed"
    [membership] = _rows(db_session, ContentTopicClusterMember, story)
    cluster = db_session.get(ContentTopicCluster, membership.cluster_id)
    assert cluster.label == "Shareholder class action filed"


def test_the_topic_port_reads_and_records_in_separate_sessions(db_session: Session) -> None:
    ticker = _ticker(db_session)
    story = _artifact(db_session, ticker, title="Class action", raw_text=CLASS_ACTION_TEXT)
    scopes: list[str] = []

    def scope():
        scopes.append("opened")
        return nullcontext(db_session)

    decision = PostgresContentTopics(scope).tag(
        story.id, provider=ScriptedProvider([json.dumps(TOPIC_ANSWER)])
    )

    assert decision.method == "llm"
    assert scopes == ["opened", "opened"]
    assert [row.topic for row in _rows(db_session, ArtifactContentTopic, story)] == ["litigation"]
    assert PostgresContentTopics(_scope(db_session)).tag(uuid.uuid4()) is None


# Analysis


def _ports(db: Session, *answers: dict, topics=None) -> AnalysisPorts:
    return AnalysisPorts(
        records=PostgresAnalysisRecords(_scope(db)),
        scorer=FixedSentiment("negative", confidence=0.9, model="test-finbert"),
        provider=ScriptedProvider([json.dumps(answer) for answer in answers]),
        topics=topics,
    )


def _story(db: Session, ticker: Ticker) -> Artifact:
    return _artifact(
        db,
        ticker,
        source_type="news",
        artifact_type="news_article",
        title="Miner faces shareholder class action",
        raw_text=CLASS_ACTION_TEXT,
        artifact_metadata={"provider": "marketaux", "feed_eligible": True},
    )


def test_analysis_tags_an_analysed_artifact_after_summarising_it(db_session: Session) -> None:
    story = _story(db_session, _ticker(db_session))
    ports = _ports(
        db_session,
        NEWS_ANSWER,
        TOPIC_ANSWER,
        topics=PostgresContentTopics(_scope(db_session)),
    )

    outcome = analyse_stored_text(story.id, ports)

    assert outcome.topic_error is None
    summary_call, topic_call = ports.provider.calls
    assert summary_call.prompt.startswith("You are summarising a financial news story")
    assert topic_call.prompt.startswith("You are tagging one item")
    db_session.refresh(story)
    assert story.analysis_status == AnalysisStatus.COMPLETED
    assert [row.topic for row in _rows(db_session, ArtifactContentTopic, story)] == ["litigation"]


class _BrokenTopics:
    def tag(self, artifact_id, *, provider=None):
        raise RuntimeError("database went away")


def test_a_topic_failure_never_fails_the_analysis(db_session: Session) -> None:
    story = _story(db_session, _ticker(db_session))
    ports = _ports(db_session, NEWS_ANSWER, topics=_BrokenTopics())

    outcome = analyse_stored_text(story.id, ports)

    assert outcome.topic_error == "RuntimeError"
    assert outcome.summarised is True
    db_session.refresh(story)
    assert story.analysis_status == AnalysisStatus.COMPLETED


def test_analysis_without_a_topic_port_records_no_topics(db_session: Session) -> None:
    story = _story(db_session, _ticker(db_session))
    ports = _ports(db_session, NEWS_ANSWER)

    outcome = analyse_stored_text(story.id, ports)

    assert outcome.topic_error is None
    assert len(ports.provider.calls) == 1
    assert _rows(db_session, ArtifactContentTopic, story) == []


# Reading


def test_the_topic_view_lists_every_topic_with_its_trend_and_clusters(db_session: Session) -> None:
    ticker = _ticker(db_session)
    # Far enough before the recent ones that it is its own development.
    previous = _artifact(db_session, ticker, day=-20, title="Old class action")
    recent = [
        _artifact(db_session, ticker, day=day, title=f"Class action filed {day}")
        for day in (10, 12, 14)
    ]
    _record(db_session, previous, _topic("litigation", event="Old class action"))
    for artifact in recent:
        _record(db_session, artifact, _topic("litigation", 0.7, event="Class action filed"))
    _record(
        db_session,
        recent[0],
        _topic("litigation", 0.7, event="Class action filed"),
        _topic("regulation", 0.6),
    )

    view = ticker_topics.read_ticker_topics(db_session, ticker.symbol.lower(), now=NOW)

    assert view.symbol == ticker.symbol
    assert [topic.topic for topic in view.topics] == list(CONTENT_TOPICS)
    by_topic = {topic.topic: topic for topic in view.topics}
    litigation = by_topic["litigation"]
    assert (litigation.recent_count, litigation.previous_count, litigation.trend) == (3, 1, "rising")
    assert (by_topic["regulation"].recent_count, by_topic["regulation"].trend) == (1, "new")
    assert by_topic["product_launch"].trend == "quiet"
    assert by_topic["product_launch"].clusters == []
    newest = litigation.clusters[0]
    assert newest.label == "Class action filed"
    assert newest.artifact_count == 3
    assert [record.id for record in newest.records] == [artifact.id for artifact in reversed(recent)]
    assert newest.records[0].evidence == "Evidence for litigation."
    assert newest.records[0].date == "Mar 14, 2040"


def test_clusters_outside_the_window_and_emptied_clusters_are_not_shown(db_session: Session) -> None:
    ticker = _ticker(db_session)
    old = _artifact(db_session, ticker, day=-200, title="Ancient class action")
    moved = _artifact(db_session, ticker, day=20, title="Product launch")
    _record(db_session, old, _topic("litigation"))
    _record(db_session, moved, _topic("litigation"))
    # Tagged again under another topic: its litigation cluster is left empty.
    _record(db_session, moved, _topic("product_launch"))

    view = ticker_topics.read_ticker_topics(db_session, ticker.symbol, now=NOW, window_days=90)

    by_topic = {topic.topic: topic for topic in view.topics}
    assert by_topic["litigation"].clusters == []
    assert len(by_topic["product_launch"].clusters) == 1


@pytest.mark.parametrize(
    ("recent", "previous", "expected"),
    [(0, 0, "quiet"), (2, 0, "new"), (6, 3, "rising"), (4, 3, "steady"), (1, 3, "falling")],
)
def test_trend_compares_the_recent_and_previous_counts(
    recent: int, previous: int, expected: str
) -> None:
    assert ticker_topics.trend(recent, previous) == expected


def test_the_topic_route_answers_its_schema_and_404_for_an_unknown_ticker(
    db_session: Session,
) -> None:
    ticker = _ticker(db_session)

    with _api(db_session) as client:
        found = client.get(f"/tickers/symbol/{ticker.symbol}.AX/topics")
        missing = client.get("/tickers/symbol/NOT-A-TICKER/topics")
        bad_days = client.get(f"/tickers/symbol/{ticker.symbol}/topics?days=0")

    assert found.status_code == 200
    assert [topic["topic"] for topic in found.json()["topics"]] == list(CONTENT_TOPICS)
    assert missing.status_code == 404
    assert bad_days.status_code == 422
    with pytest.raises(TickerNotFound):
        ticker_topics.read_ticker_topics(db_session, "NOT-A-TICKER")


def test_feed_cards_carry_their_topics_most_confident_first(db_session: Session) -> None:
    ticker = _ticker(db_session)
    filing = _artifact(db_session, ticker, title="ASIC sues over fees")
    _record(db_session, filing, _topic("litigation", 0.6), _topic("regulation", 0.9))

    [record] = [
        item for item in ticker_records.read_news_feed(db_session, ticker.symbol)
        if item.id == filing.id
    ]
    feed = get_announcements(
        db_session, start_date=date(2040, 3, 1), end_date=date(2040, 3, 1)
    )

    assert record.topics == ["regulation", "litigation"]
    assert [item.topics for item in feed if item.id == filing.id] == [["regulation", "litigation"]]


def test_the_market_feed_filters_by_topic(db_session: Session) -> None:
    ticker = _ticker(db_session)
    tagged = _artifact(db_session, ticker, day=2, title="Class action filed")
    untagged = _artifact(db_session, ticker, day=2, title="Notice of meeting")
    _record(db_session, tagged, _topic("litigation"))
    window = {"start_date": date(2040, 3, 2), "end_date": date(2040, 3, 2)}

    filtered = get_announcements(db_session, topic="litigation", **window)
    unfiltered = get_announcements(db_session, **window)

    assert tagged.id in {item.id for item in filtered}
    assert untagged.id not in {item.id for item in filtered}
    assert {tagged.id, untagged.id} <= {item.id for item in unfiltered}
    with _api(db_session) as client:
        assert client.get("/announcements/?topic=astrology").status_code == 422
        answered = client.get(
            "/announcements/?topic=litigation&start_date=2040-03-02&end_date=2040-03-02"
        )
    assert answered.status_code == 200
    assert tagged.id in {uuid.UUID(item["id"]) for item in answered.json()}


# Tagging stored artifacts


def _analysed(db: Session, ticker: Ticker, **values) -> Artifact:
    return _artifact(
        db,
        ticker,
        analysis_status=AnalysisStatus.COMPLETED,
        **values,
    )


def test_the_tagging_command_tags_untagged_analysed_artifacts_once(db_session: Session) -> None:
    ticker = _ticker(db_session)
    filing = _analysed(
        db_session, ticker, title="Class action filed", raw_text=CLASS_ACTION_TEXT, day=2
    )
    plain = _analysed(db_session, ticker, title="Notice of meeting", day=1)
    pending = _artifact(db_session, ticker, title="Class action", raw_text=CLASS_ACTION_TEXT)
    excluded = _analysed(
        db_session,
        ticker,
        title="Class action",
        raw_text=CLASS_ACTION_TEXT,
        artifact_metadata={"feed_eligible": False},
    )
    options = dict(ticker=ticker.symbol.lower(), batch_size=1, limit=50)

    dry = tag_content_topics.run_tagging(db_session, TaggingOptions(dry_run=True, **options))
    applied = tag_content_topics.run_tagging(db_session, TaggingOptions(dry_run=False, **options))
    again = tag_content_topics.run_tagging(db_session, TaggingOptions(dry_run=False, **options))

    assert (dry.selected, dry.tagged, dry.with_topics) == (2, 0, 1)
    assert (applied.selected, applied.tagged, applied.by_method) == (2, 2, {"rules": 2})
    assert applied.by_topic == {"litigation": 1}
    assert again.selected == 0
    assert [row.topic for row in _rows(db_session, ArtifactContentTopic, filing)] == ["litigation"]
    for artifact in (plain, pending, excluded):
        db_session.refresh(artifact)
    assert plain.artifact_metadata[TOPICS_VERSION_KEY] == RULES_VERSION
    assert TOPICS_VERSION_KEY not in (pending.artifact_metadata or {})
    assert TOPICS_VERSION_KEY not in (excluded.artifact_metadata or {})


def test_an_llm_run_retags_what_the_rules_tagged(db_session: Session) -> None:
    ticker = _ticker(db_session)
    filing = _analysed(db_session, ticker, title="Class action filed", raw_text=CLASS_ACTION_TEXT)
    options = dict(ticker=ticker.symbol, limit=10)
    tag_content_topics.run_tagging(db_session, TaggingOptions(dry_run=False, **options))

    upgraded = tag_content_topics.run_tagging(
        db_session,
        TaggingOptions(dry_run=False, llm=True, **options),
        provider=ScriptedProvider([json.dumps(TOPIC_ANSWER)]),
    )

    assert (upgraded.selected, upgraded.by_method) == (1, {"llm": 1})
    [row] = _rows(db_session, ArtifactContentTopic, filing)
    assert (row.method, row.event_label) == ("llm", "Shareholder class action filed")


def test_the_tagging_command_refuses_unbounded_runs() -> None:
    with pytest.raises(ValueError, match="limit"):
        TaggingOptions(limit=0)
    with pytest.raises(ValueError, match="with --llm"):
        TaggingOptions(llm=True, limit=tag_content_topics.MAX_LLM_LIMIT + 1)
    with pytest.raises(ValueError, match="batch_size"):
        TaggingOptions(batch_size=tag_content_topics.MAX_BATCH_SIZE + 1)
