import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.public_discussion import (
    ArtifactTickerMentionCreate,
    CollectionStatus,
    PublicDiscussionAdapter,
    PublicDiscussionCollectionResult,
    PublicDiscussionPost,
)
from app.services.public_discussion import find_ticker_mentions


class ExampleAdapter:
    source_type = "example_blog"

    def collect(
        self,
        query: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> PublicDiscussionCollectionResult:
        return PublicDiscussionCollectionResult(
            status=CollectionStatus.COMPLETED,
            posts=[
                PublicDiscussionPost(
                    source_type=self.source_type,
                    source_id="post-1",
                    title=f"Discussion about {query}",
                    url="https://example.test/post-1",
                )
            ][:limit],
            next_cursor=cursor,
        )


def test_source_adapter_contract_normalises_collection_results() -> None:
    adapter = ExampleAdapter()

    result = adapter.collect("BHP", limit=10)

    assert isinstance(adapter, PublicDiscussionAdapter)
    assert result.status == CollectionStatus.COMPLETED
    assert result.posts[0].source_type == "example_blog"
    assert result.posts[0].source_id == "post-1"


def test_collection_status_contract_covers_each_pipeline_state() -> None:
    assert {status.value for status in CollectionStatus} == {
        "queued",
        "running",
        "completed",
        "partial",
        "failed",
    }


def test_ticker_mention_contract_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        ArtifactTickerMentionCreate(
            artifact_id=uuid.uuid4(),
            ticker_id=uuid.uuid4(),
            match_method="ticker_symbol",
            match_confidence=1.1,
        )


@pytest.mark.parametrize(
    ("text", "method", "confidence"),
    [
        ("Watching $BHP today", "cashtag", 1.0),
        ("ASX:BHP released an update", "exchange_qualified", 1.0),
        ("BHP.AX moved today", "exchange_qualified", 1.0),
        ("BHP shares rose after earnings", "ticker_symbol", 0.85),
        ("BHP Group Limited released an update", "company_name", 0.95),
    ],
)
def test_ticker_matcher_records_explainable_match_methods(
    text: str,
    method: str,
    confidence: float,
) -> None:
    ticker = SimpleNamespace(
        id=uuid.uuid4(),
        symbol="BHP",
        company_name="BHP Group Limited",
    )

    matches = find_ticker_mentions(
        title=text,
        raw_text="",
        metadata={},
        tickers=[ticker],
    )

    assert len(matches) == 1
    assert matches[0].match_method == method
    assert matches[0].match_confidence == confidence


def test_ticker_matcher_rejects_bare_symbol_without_finance_context() -> None:
    ticker = SimpleNamespace(
        id=uuid.uuid4(),
        symbol="ANZ",
        company_name="ANZ Group Holdings Limited",
    )

    matches = find_ticker_mentions(
        title="Thanks Anz for helping today",
        raw_text="",
        metadata={},
        tickers=[ticker],
    )

    assert matches == []


def test_ticker_matcher_accepts_asx_subreddit_as_finance_context() -> None:
    ticker = SimpleNamespace(
        id=uuid.uuid4(),
        symbol="ANZ",
        company_name="ANZ Group Holdings Limited",
    )

    matches = find_ticker_mentions(
        title="Thoughts on ANZ?",
        raw_text="",
        metadata={"subreddit": "ASX"},
        tickers=[ticker],
    )

    assert [match.symbol for match in matches] == ["ANZ"]


@pytest.mark.parametrize(
    ("route_name", "arguments", "post"),
    [
        (
            "reddit",
            ("ASX", 1),
            {
                "id": "reddit-1",
                "title": "$BHP shares rise",
                "body": "Investors discuss earnings.",
                "score": 2,
                "upvote_ratio": 0.9,
                "num_comments": 1,
                "url": "https://reddit.test/post-1",
                "external_url": None,
                "author": "investor",
                "flair": "Discussion",
                "is_self": True,
                "created_utc": 1787961600.0,
                "subreddit": "ASX",
            },
        ),
        (
            "bluesky",
            ("BHP", 1),
            {
                "uri": "at://did:plc:test/app.bsky.feed.post/one",
                "text": "$BHP shares rise",
                "created_at": "2026-08-29T00:00:00Z",
                "author": "investor.test",
                "display_name": "Investor",
                "reply_count": 1,
                "repost_count": 1,
                "like_count": 2,
                "quote_count": 0,
                "langs": ["en"],
                "tags": ["ASX"],
            },
        ),
        (
            "mastodon",
            ("BHP", 1),
            {
                "id": "mastodon-1",
                "text": "$BHP shares rise",
                "created_at": "2026-08-29T00:00:00Z",
                "url": "https://aus.social/@investor/one",
                "author": "investor",
                "display_name": "Investor",
                "replies_count": 1,
                "reblogs_count": 1,
                "favourites_count": 2,
                "language": "en",
                "tags": ["ASX"],
                "sensitive": False,
                "spoiler_text": "",
            },
        ),
    ],
)
def test_social_collectors_link_each_saved_artifact(
    route_name: str,
    arguments: tuple[str, int],
    post: dict,
) -> None:
    from importlib import import_module

    route = import_module(f"app.api.routes.{route_name}")
    db = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = db
    artifact = MagicMock(id=uuid.uuid4())
    platform = MagicMock(id=uuid.uuid4())
    platform_function = getattr(route, f"_get_or_create_{route_name}_platform")

    credential_patches = []
    if route_name == "reddit":
        credential_patches = [
            patch.object(route.settings, "REDDIT_CLIENT_ID", "client"),
            patch.object(route.settings, "REDDIT_CLIENT_SECRET", "secret"),
        ]

    for credential_patch in credential_patches:
        credential_patch.start()
    try:
        with patch.object(route, "SessionLocal", return_value=session_context), patch.object(
            route,
            platform_function.__name__,
            return_value=platform,
        ), patch.object(route, "_fetch_posts", return_value=[post]), patch.object(
            route.artifact_crud,
            "get_artifact_by_hash",
            return_value=None,
        ), patch.object(
            route.artifact_crud,
            "create_artifact",
            return_value=artifact,
        ), patch.object(
            route.public_discussion_service,
            "link_artifact_to_tickers",
            return_value=[MagicMock()],
        ) as link_artifact:
            with patch.object(
                route.public_discussion_service,
                "queue_artifact_analysis",
                return_value=True,
            ) as queue_analysis:
                result = route._scrape_and_store_posts(*arguments)
    finally:
        for credential_patch in credential_patches:
            credential_patch.stop()

    assert result == {
        "saved": 1,
        "skipped_duplicates": 0,
        "mentions_linked": 1,
        "analysis_queued": 1,
    }
    link_artifact.assert_called_once_with(db, artifact)
    queue_analysis.assert_called_once_with(db, artifact, link_artifact.return_value)


def test_public_discussion_analysis_queue_requires_a_match_and_configuration() -> None:
    from app.services import public_discussion

    artifact = SimpleNamespace(id=uuid.uuid4(), analysis_status="pending")
    db = MagicMock()
    with patch.object(public_discussion.settings, "ANALYSIS_QUEUE_URL", ""):
        assert (
            public_discussion.queue_artifact_analysis(db, artifact, [MagicMock()])
            is False
        )

    with patch.object(public_discussion.settings, "ANALYSIS_QUEUE_URL", "queue-url"), patch(
        "app.services.analysis_queue.enqueue_public_discussion_analysis",
        return_value="message-1",
    ) as enqueue, patch(
        "app.crud.scrape_run.mark_inline_artifact_analysis_queued",
    ) as mark_queued:
        assert (
            public_discussion.queue_artifact_analysis(db, artifact, [MagicMock()])
            is True
        )

    enqueue.assert_called_once_with(artifact.id)
    mark_queued.assert_called_once_with(db, artifact.id)


def test_public_discussion_status_aggregates_analysis_states() -> None:
    from datetime import datetime, timezone

    from app.services import public_discussion

    ticker = SimpleNamespace(id=uuid.uuid4(), symbol="BHP")
    collected_at = datetime(2026, 8, 29, tzinfo=timezone.utc)
    artifacts = [
        SimpleNamespace(
            analysis_status="completed",
            source_type="reddit",
            published_at=collected_at,
            created_at=collected_at,
        ),
        SimpleNamespace(
            analysis_status="queued",
            source_type="blog",
            published_at=None,
            created_at=collected_at,
        ),
        SimpleNamespace(
            analysis_status="failed",
            source_type="reddit",
            published_at=None,
            created_at=collected_at,
        ),
    ]
    with patch.object(
        public_discussion,
        "_ticker_for_symbol",
        return_value=ticker,
    ), patch.object(
        public_discussion,
        "_ticker_discussion_artifacts",
        return_value=artifacts,
    ):
        result = public_discussion.public_discussion_status(MagicMock(), "bhp")

    assert result == {
        "ticker": "BHP",
        "status": "partial",
        "counts": {
            "total": 3,
            "pending": 0,
            "queued": 1,
            "analyzing": 0,
            "completed": 1,
            "failed": 1,
        },
        "sources": {"blog": 1, "reddit": 2},
        "latest_collected_at": collected_at,
    }


def test_pending_analysis_requeue_is_dry_run_first() -> None:
    from app.services import public_discussion

    artifacts = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
    with patch.object(
        public_discussion,
        "_pending_analysis_artifacts",
        return_value=artifacts,
    ), patch(
        "app.services.analysis_queue.enqueue_public_discussion_analysis",
    ) as enqueue:
        result = public_discussion.requeue_pending_analysis(MagicMock())

    assert result["execute"] is False
    assert result["candidates"] == 2
    assert result["queued"] == 0
    assert result["artifact_ids"] == [artifact.id for artifact in artifacts]
    enqueue.assert_not_called()


def test_pending_analysis_requeue_sends_and_marks_a_bounded_batch() -> None:
    from app.services import public_discussion

    db = MagicMock()
    artifacts = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
    with patch.object(public_discussion.settings, "ANALYSIS_QUEUE_URL", "queue-url"), patch.object(
        public_discussion,
        "_pending_analysis_artifacts",
        return_value=artifacts,
    ) as pending, patch(
        "app.services.analysis_queue.enqueue_public_discussion_analysis",
        return_value="message-id",
    ) as enqueue, patch(
        "app.crud.scrape_run.mark_inline_artifact_analysis_queued",
    ) as mark_queued:
        result = public_discussion.requeue_pending_analysis(
            db,
            limit=25,
            execute=True,
        )

    pending.assert_called_once_with(db, ticker=None, limit=25)
    assert enqueue.call_count == 2
    assert mark_queued.call_count == 2
    assert result["queued"] == 2
    assert result["artifact_ids"] == [artifact.id for artifact in artifacts]


def test_public_discussion_requeue_route_requires_admin_dependency() -> None:
    from app.api.deps import require_admin_investor
    from app.api.routes import public_discussion

    route = next(
        route
        for route in public_discussion.router.routes
        if getattr(route, "path", None) == "/public-discussion/analysis/requeue"
    )

    assert require_admin_investor in {
        dependency.call for dependency in route.dependant.dependencies
    }


@pytest.mark.parametrize("route_name", ["reddit", "bluesky", "mastodon", "blog"])
def test_public_discussion_collectors_require_admin_dependency(
    route_name: str,
) -> None:
    from importlib import import_module

    from app.api.deps import require_admin_investor

    module = import_module(f"app.api.routes.{route_name}")
    route = next(
        route
        for route in module.router.routes
        if getattr(route, "path", "").endswith("/scrape")
        and "POST" in getattr(route, "methods", set())
    )

    assert require_admin_investor in {
        dependency.call for dependency in route.dependant.dependencies
    }


def test_no_public_discussion_does_not_report_neutral_sentiment() -> None:
    from app.api.routes import category_sentiment

    with patch.object(
        category_sentiment.artifact_crud,
        "get_reddit_posts_for_ticker",
        return_value=[],
    ), patch.object(
        category_sentiment.artifact_crud,
        "get_bluesky_posts_for_ticker",
        return_value=[],
    ), patch.object(
        category_sentiment.artifact_crud,
        "get_mastodon_posts_for_ticker",
        return_value=[],
    ):
        result = category_sentiment._summarise_recent_public_discussion(
            ticker="BHP",
            db=MagicMock(),
            days=30,
            reddit_limit=20,
            bluesky_limit=20,
            mastodon_limit=20,
        )

    assert result["dominant_sentiment"] is None
    assert "No public discussion" in result["summary"]


def test_blog_adapter_parses_rss_and_atom_entries() -> None:
    from app.api.routes import blog

    rss = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <guid>rss-1</guid><title>BHP result</title>
      <link>https://example.test/rss-1</link>
      <description><![CDATA[<p>$BHP profit rose.</p>]]></description>
      <pubDate>Sat, 29 Aug 2026 01:00:00 GMT</pubDate>
    </item></channel></rss>"""
    atom = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>atom-1</id><title>ANZ result</title>
      <link rel="alternate" href="https://example.test/atom-1" />
      <summary>ASX:ANZ profit rose.</summary>
      <updated>2026-08-29T02:00:00Z</updated>
      <author><name>Reporter</name></author>
    </entry></feed>"""

    rss_posts = blog._parse_feed(rss, limit=10)
    atom_posts = blog._parse_feed(atom, limit=10)

    assert rss_posts[0]["id"] == "rss-1"
    assert rss_posts[0]["raw_text"] == "$BHP profit rose."
    assert rss_posts[0]["published_at"].isoformat() == "2026-08-29T01:00:00+00:00"
    assert atom_posts[0]["url"] == "https://example.test/atom-1"
    assert atom_posts[0]["author"] == "Reporter"


def test_blog_adapter_rejects_xml_entity_declarations() -> None:
    from app.api.routes import blog

    unsafe_feed = b"""<!DOCTYPE rss [<!ENTITY x "unsafe">]>
    <rss version="2.0"><channel><item><title>&x;</title></item></channel></rss>"""

    with pytest.raises(ValueError, match="declarations are not allowed"):
        blog._parse_feed(unsafe_feed, limit=10)


def test_blog_scrape_endpoint_rejects_unconfigured_feed() -> None:
    from app.api.routes import blog

    with patch.object(blog.settings, "PUBLIC_DISCUSSION_FEED_URLS", []):
        with pytest.raises(Exception) as exc_info:
            blog.scrape_and_store(
                background_tasks=MagicMock(),
                feed_url="https://example.test/feed.xml",
                db=MagicMock(),
            )

    assert exc_info.value.status_code == 400
    assert "allowlist" in exc_info.value.detail


def test_bluesky_public_search_uses_public_appview() -> None:
    from app.api.routes import bluesky

    response = MagicMock()
    response.json.return_value = {"posts": []}
    with patch.object(bluesky.settings, "BLUESKY_IDENTIFIER", ""), patch.object(
        bluesky.settings,
        "BLUESKY_APP_PASSWORD",
        "",
    ), patch.object(
        bluesky.settings,
        "BLUESKY_PUBLIC_API_URL",
        "https://public.api.bsky.test",
    ), patch.object(bluesky.httpx, "get", return_value=response) as get:
        assert bluesky._fetch_posts("BHP", 5) == []

    get.assert_called_once_with(
        "https://public.api.bsky.test/xrpc/app.bsky.feed.searchPosts",
        params={"q": "BHP", "limit": 5},
        headers={},
        timeout=15.0,
    )


def test_bluesky_authenticated_search_uses_app_password_session() -> None:
    from app.api.routes import bluesky

    session_response = MagicMock()
    session_response.json.return_value = {"accessJwt": "access-token"}
    search_response = MagicMock()
    search_response.json.return_value = {"posts": []}
    with patch.object(bluesky.settings, "BLUESKY_IDENTIFIER", "user.bsky.social"), patch.object(
        bluesky.settings,
        "BLUESKY_APP_PASSWORD",
        "app-password",
    ), patch.object(
        bluesky.settings,
        "BLUESKY_SERVICE_URL",
        "https://bsky.test",
    ), patch.object(
        bluesky.httpx,
        "post",
        return_value=session_response,
    ) as post, patch.object(
        bluesky.httpx,
        "get",
        return_value=search_response,
    ) as get:
        assert bluesky._fetch_posts("BHP", 5) == []

    post.assert_called_once_with(
        "https://bsky.test/xrpc/com.atproto.server.createSession",
        json={"identifier": "user.bsky.social", "password": "app-password"},
        timeout=15.0,
    )
    get.assert_called_once_with(
        "https://bsky.test/xrpc/app.bsky.feed.searchPosts",
        params={"q": "BHP", "limit": 5},
        headers={"Authorization": "Bearer access-token"},
        timeout=15.0,
    )


def test_bluesky_rejects_half_configured_credentials() -> None:
    from app.api.routes import bluesky

    with patch.object(bluesky.settings, "BLUESKY_IDENTIFIER", "user.bsky.social"), patch.object(
        bluesky.settings,
        "BLUESKY_APP_PASSWORD",
        "",
    ):
        with pytest.raises(RuntimeError, match="must be configured together"):
            bluesky._search_request_config()


def test_public_discussion_run_records_collection_counts() -> None:
    from app.crud import scrape_run as scrape_run_crud

    run = SimpleNamespace(
        status="queued",
        started_at=None,
        finished_at=None,
        error_message="old error",
        items_found=0,
        items_saved=0,
        items_failed=0,
    )
    db = MagicMock()
    with patch.object(scrape_run_crud, "_lock_run", return_value=run), patch.object(
        scrape_run_crud,
        "_commit",
        side_effect=lambda _db, value: value,
    ):
        scrape_run_crud.mark_public_discussion_run_started(db, uuid.uuid4())
        assert run.status == "running"
        assert run.started_at is not None
        assert run.error_message is None

        scrape_run_crud.mark_public_discussion_run_completed(
            db,
            uuid.uuid4(),
            items_found=4,
            items_saved=3,
            items_failed=1,
        )

    assert run.status == "partial"
    assert run.items_found == 4
    assert run.items_saved == 3
    assert run.items_failed == 1
    assert run.finished_at is not None


def test_public_discussion_run_records_bounded_failure() -> None:
    from app.crud import scrape_run as scrape_run_crud

    run = SimpleNamespace(status="running", finished_at=None, error_message=None)
    with patch.object(scrape_run_crud, "_lock_run", return_value=run), patch.object(
        scrape_run_crud,
        "_commit",
        side_effect=lambda _db, value: value,
    ):
        scrape_run_crud.mark_public_discussion_run_failed(
            MagicMock(),
            uuid.uuid4(),
            error="x" * 9000,
        )

    assert run.status == "failed"
    assert len(run.error_message) == 8000
    assert run.finished_at is not None


def test_inline_analysis_state_does_not_require_a_download() -> None:
    from app.crud import scrape_run as scrape_run_crud

    artifact = SimpleNamespace(
        analysis_status="pending",
        raw_text="Stored discussion text",
        title="Discussion title",
        analyzed_at=None,
        last_error="old error",
    )
    with patch.object(
        scrape_run_crud,
        "_lock_artifact",
        return_value=artifact,
    ), patch.object(
        scrape_run_crud,
        "_commit",
        side_effect=lambda _db, value: value,
    ):
        scrape_run_crud.mark_inline_artifact_analysis_queued(
            MagicMock(),
            uuid.uuid4(),
        )
        assert artifact.analysis_status == "queued"
        assert artifact.last_error is None

        scrape_run_crud.mark_inline_artifact_analysis_started(
            MagicMock(),
            uuid.uuid4(),
        )
        assert artifact.analysis_status == "analyzing"
        assert artifact.last_error is None

        scrape_run_crud.mark_inline_artifact_analysis_completed(
            MagicMock(),
            uuid.uuid4(),
        )

    assert artifact.analysis_status == "completed"
    assert artifact.analyzed_at is not None
