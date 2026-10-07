"""Collecting public discussion, on Postgres.

A stored post is identified by its content hash. The formats are pinned
here, because changing one would store every existing post again:

- reddit:{post id}
- bluesky:{post URI}
- mastodon:{post URL}, or mastodon:{instance}:{post id} without a URL
- blog:{feed URL}:{entry id, or its link without an id}
"""

import hashlib
import sys
import uuid
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.models.artifact import Artifact
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.ticker import Ticker

FEED_URL = "https://blog.example.test/feed.xml"


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


def _hash(identity: str) -> str:
    return hashlib.sha256(identity.encode()).hexdigest()


def _collect(source: str, raw_posts: list[dict], db: Session, monkeypatch) -> dict:
    """Collect recorded posts from one source into the test database."""
    route = import_module(f"app.api.routes.{source}")
    monkeypatch.setattr(route, "_fetch_posts", lambda *_args, **_kwargs: raw_posts)
    monkeypatch.setattr(route, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(settings, "ANALYSIS_QUEUE_URL", "")
    if source == "reddit":
        monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "client")
        monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "secret")
        return route._scrape_and_store_posts(subreddit="ASX", limit=10)
    target = FEED_URL if source == "blog" else "ASX"
    return route._scrape_and_store_posts(target, 10)


def _stored(db: Session, identity: str) -> Artifact:
    return db.query(Artifact).filter(Artifact.content_hash == _hash(identity)).one()


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _mentions(db: Session, artifact: Artifact) -> set[str]:
    return {
        symbol
        for (symbol,) in db.query(Ticker.symbol)
        .join(ArtifactTickerMention, ArtifactTickerMention.ticker_id == Ticker.id)
        .filter(ArtifactTickerMention.artifact_id == artifact.id)
    }


def reddit_post(post_id: str) -> dict:
    return {
        "id": post_id,
        "title": "$BHP shares rise",
        "body": "Investors discuss earnings.",
        "score": 12,
        "upvote_ratio": 0.9,
        "num_comments": 3,
        "url": f"https://reddit.com/r/ASX/comments/{post_id}/bhp/",
        "external_url": None,
        "author": "investor",
        "flair": "Discussion",
        "is_self": True,
        "created_utc": 1787961600.0,
        "subreddit": "ASX",
    }


def bluesky_post(uri: str, *, created_at: str = "2026-08-29T00:00:00Z") -> dict:
    return {
        "uri": uri,
        "text": "$BHP shares rise on earnings",
        "created_at": created_at,
        "author": "investor.test",
        "display_name": "Investor",
        "reply_count": 1,
        "repost_count": 2,
        "like_count": 5,
        "quote_count": 0,
        "langs": ["en"],
        "tags": ["ASX"],
    }


def mastodon_post(post_id: str, *, url: str, created_at: str = "2026-08-29T00:00:00Z") -> dict:
    return {
        "id": post_id,
        "text": "$BHP shares rise on earnings",
        "created_at": created_at,
        "url": url,
        "author": "investor",
        "display_name": "Investor",
        "replies_count": 1,
        "reblogs_count": 2,
        "favourites_count": 3,
        "language": "en",
        "tags": ["ASX"],
        "sensitive": False,
        "spoiler_text": "",
    }


def blog_post(entry_id: str, *, url: str) -> dict:
    return {
        "id": entry_id,
        "title": "ASX:BHP profit rose",
        "url": url,
        "author": "Reporter",
        "raw_text": "BHP Group Limited reported higher profit.",
        "published_at": datetime(2026, 8, 29, 1, tzinfo=timezone.utc),
    }


def test_reddit_posts_are_identified_by_their_id(db_session: Session, monkeypatch) -> None:
    post_id = _unique("r")

    _collect("reddit", [reddit_post(post_id)], db_session, monkeypatch)

    artifact = _stored(db_session, f"reddit:{post_id}")
    assert artifact.source_type == "reddit"
    assert artifact.artifact_type == "reddit_post"
    assert artifact.title == "$BHP shares rise"
    assert artifact.raw_text == "Investors discuss earnings."
    assert artifact.url == f"https://reddit.com/r/ASX/comments/{post_id}/bhp/"
    assert artifact.published_at == datetime.fromtimestamp(1787961600.0, timezone.utc)
    assert artifact.artifact_metadata["reddit_id"] == post_id
    assert artifact.artifact_metadata["score"] == 12
    assert _mentions(db_session, artifact) == {"BHP"}


def test_bluesky_posts_are_identified_by_their_uri(db_session: Session, monkeypatch) -> None:
    uri = f"at://did:plc:test/app.bsky.feed.post/{_unique('b')}"

    _collect("bluesky", [bluesky_post(uri)], db_session, monkeypatch)

    artifact = _stored(db_session, f"bluesky:{uri}")
    assert artifact.source_type == "bluesky"
    assert artifact.artifact_type == "bluesky_post"
    assert artifact.url == (
        f"https://bsky.app/profile/investor.test/post/{uri.rsplit('/', 1)[-1]}"
    )
    assert artifact.published_at == datetime(2026, 8, 29, tzinfo=timezone.utc)
    assert artifact.artifact_metadata["bluesky_uri"] == uri
    assert artifact.artifact_metadata["like_count"] == 5
    assert artifact.artifact_metadata["search_query"] == "ASX"
    assert _mentions(db_session, artifact) == {"BHP"}


def test_mastodon_posts_are_identified_by_their_url_or_instance_and_id(
    db_session: Session,
    monkeypatch,
) -> None:
    with_url = _unique("m")
    without_url = _unique("m")
    url = f"https://aus.social/@investor/{with_url}"

    _collect(
        "mastodon",
        [mastodon_post(with_url, url=url), mastodon_post(without_url, url="")],
        db_session,
        monkeypatch,
    )

    linked = _stored(db_session, f"mastodon:{url}")
    unlinked = _stored(db_session, f"mastodon:https://aus.social:{without_url}")
    assert linked.source_type == "mastodon"
    assert linked.artifact_type == "mastodon_post"
    assert linked.url == url
    assert unlinked.url == f"https://aus.social/@investor/{without_url}"
    assert linked.artifact_metadata["mastodon_id"] == with_url
    assert linked.artifact_metadata["favourites_count"] == 3
    assert _mentions(db_session, linked) == {"BHP"}


def test_blog_entries_are_identified_by_feed_and_entry(db_session: Session, monkeypatch) -> None:
    entry_id = _unique("e")
    link_only = f"https://blog.example.test/{_unique('post')}"

    _collect(
        "blog",
        [
            blog_post(entry_id, url=f"https://blog.example.test/{entry_id}"),
            blog_post("", url=link_only),
        ],
        db_session,
        monkeypatch,
    )

    entry = _stored(db_session, f"blog:{FEED_URL}:{entry_id}")
    linked = _stored(db_session, f"blog:{FEED_URL}:{link_only}")
    assert entry.source_type == "blog"
    assert entry.artifact_type == "blog_post"
    assert entry.source_adapter == "rss_atom"
    assert entry.source_id == entry_id
    assert entry.canonical_url == f"https://blog.example.test/{entry_id}"
    assert entry.artifact_metadata == {"feed_url": FEED_URL}
    assert linked.source_id == link_only
    assert _mentions(db_session, entry) == {"BHP"}


@pytest.mark.parametrize(
    ("source", "make_post", "identity"),
    [
        ("reddit", lambda key: reddit_post(key), lambda key: f"reddit:{key}"),
        ("bluesky", lambda key: bluesky_post(f"at://x/{key}"), lambda key: f"bluesky:at://x/{key}"),
        (
            "mastodon",
            lambda key: mastodon_post(key, url=f"https://aus.social/@a/{key}"),
            lambda key: f"mastodon:https://aus.social/@a/{key}",
        ),
        (
            "blog",
            lambda key: blog_post(key, url=f"https://blog.example.test/{key}"),
            lambda key: f"blog:{FEED_URL}:{key}",
        ),
    ],
)
def test_a_post_collected_again_is_not_stored_twice(
    db_session: Session,
    monkeypatch,
    source: str,
    make_post,
    identity,
) -> None:
    key = _unique(source)

    _collect(source, [make_post(key)], db_session, monkeypatch)
    _collect(source, [make_post(key)], db_session, monkeypatch)

    assert (
        db_session.query(Artifact)
        .filter(Artifact.content_hash == _hash(identity(key)))
        .count()
        == 1
    )
