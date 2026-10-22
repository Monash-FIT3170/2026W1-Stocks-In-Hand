"""Document links remain specific across current and legacy artifact shapes."""

import pytest
from datetime import datetime, timezone

from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.read_models.ticker_sentiment import aggregate_bucket
from app.services import artifact_card, artifact_summary
from app.services.claim_traceability import artifact_source_url, traceable_claims


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"document_url": " https://example.test/report.pdf "}, "https://example.test/report.pdf"),
        ({"artifact_metadata": {"pdf_url": "https://example.test/legacy.pdf"}}, "https://example.test/legacy.pdf"),
        ({}, "https://example.test/report"),
        ({"canonical_url": None}, "https://example.test/old-report"),
        ({"canonical_url": None, "url": None}, "https://example.test/announcements"),
        ({"document_url": "javascript:alert(1)", "artifact_metadata": {"pdf_url": "https://[bad"}}, "https://example.test/report"),
        ({"canonical_url": " ", "url": "file:///tmp/report.pdf", "artifact_metadata": None}, None),
        ({"canonical_url": None, "url": None, "artifact_metadata": []}, None),
    ],
)
def test_report_link_prefers_safe_documents_then_publication_pages(values, expected):
    fields = {
        "artifact_type": "asx_announcement_other",
        "source_type": "asx_announcement",
        "canonical_url": "https://example.test/report",
        "url": "https://example.test/old-report",
        "artifact_metadata": {"source_url": "https://example.test/announcements"},
    }
    artifact = Artifact(**{**fields, **values})

    assert artifact_source_url(artifact) == expected


def test_current_document_takes_precedence_over_legacy_pdf_and_listing():
    artifact = Artifact(
        artifact_type="asx_announcement_other",
        document_url="https://example.test/current.pdf",
        canonical_url="https://example.test/report",
        url="https://example.test/announcements",
        artifact_metadata={"pdf_url": "https://example.test/legacy.pdf"},
    )

    assert artifact_source_url(artifact) == "https://example.test/current.pdf"


@pytest.mark.parametrize(
    "links",
    [
        {"document_url": "https://example.test/results.pdf"},
        {"artifact_metadata": {"pdf_url": "https://example.test/results.pdf"}},
    ],
)
def test_feed_brief_claims_and_sentiment_share_the_specific_report(links):
    published_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    artifact = Artifact(
        artifact_type="asx_announcement_other",
        source_type="asx_announcement",
        title="Company annual results 2026",
        raw_text="Revenue increased.",
        published_at=published_at,
        canonical_url="https://example.test/announcements",
        url="https://example.test/investors",
        **links,
    )
    summary = artifact_summary.from_answer(
        {"confirmed_facts": ["Revenue increased."], "speculation": []},
        model=None,
        prompt_version=None,
    )
    sentiment = ArtifactSentiment(sentiment_label="positive", confidence_score=0.9)

    card = artifact_card.artifact_card(artifact)
    [source] = artifact_card.sources(artifact)
    [claim] = traceable_claims(artifact, summary)
    bucket = aggregate_bucket("revenue", [(artifact, sentiment)])
    [bucket_source] = bucket.sources

    assert {card.url, source["url"], claim["source"]["url"], bucket_source.url} == {
        "https://example.test/results.pdf"
    }
    assert source["title"] == bucket_source.title == artifact.title
    assert source["published_at"] == claim["source"]["published_at"] == published_at.isoformat()
    assert bucket_source.published_at == published_at


@pytest.mark.parametrize("source_type", ["news", "reddit", "bluesky"])
def test_non_report_sources_keep_their_original_publication_links(source_type):
    artifact = Artifact(
        artifact_type="post",
        source_type=source_type,
        title="Company update",
        canonical_url="https://publisher.test/company-update",
        url="https://publisher.test/legacy-update",
    )
    sentiment = ArtifactSentiment(sentiment_label="neutral", confidence_score=0.8)

    assert artifact_card.artifact_card(artifact).url == "https://publisher.test/company-update"
    assert aggregate_bucket("strategy", [(artifact, sentiment)]).sources[0].url == (
        "https://publisher.test/company-update"
    )


def test_unsafe_urls_do_not_escape_through_feed_or_sentiment_fallbacks():
    artifact = Artifact(
        artifact_type="asx_announcement_other",
        document_url="javascript:alert(1)",
        canonical_url="https://[bad",
        url="file:///tmp/report.pdf",
        artifact_metadata={"pdf_url": "data:text/plain,report", "source_url": " "},
    )
    sentiment = ArtifactSentiment(sentiment_label="neutral", confidence_score=0.8)

    assert artifact_card.artifact_card(artifact).url is None
    assert artifact_card.sources(artifact) == []
    assert aggregate_bucket("strategy", [(artifact, sentiment)]).sources[0].url is None
