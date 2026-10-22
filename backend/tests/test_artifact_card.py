"""The artifact card both feeds show, built from unsaved artifacts.

The market feed and a ticker's news feed used to format cards separately,
with different source labels, tags and fallbacks. The market feed showed
the raw text when there was no summary, and the ticker feed showed
placeholder sentences.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.artifact import Artifact
from app.models.artifact_summary import ArtifactSummary
from app.models.information_platform import InformationPlatform
from app.services import artifact_card
from app.services.artifact_card import ArtifactCard

LINES = {
    "summary": "BHP lifted copper output.",
    "about": "The filing covers BHP's   quarterly production.",
    "changed": "Copper output rose.",
    "matters": "Output supports revenue.",
}


def _artifact(**values) -> Artifact:
    values.setdefault("artifact_type", "asx_announcement_other")
    return Artifact(id=uuid.uuid4(), **values)


def test_a_summarised_announcement_card() -> None:
    artifact = _artifact(
        source_type="asx_announcement",
        artifact_type="dividend_announcement",
        title="Dividend  update",
        url="https://example.test/asx/bhp",
        raw_text="Raw announcement text",
        artifact_metadata={"category": "DividendAnnouncement", **LINES},
    )

    assert artifact_card.artifact_card(artifact) == ArtifactCard(
        tag="Dividend Announcement",
        title="Dividend update",
        source_type="asx_announcement",
        source_name="ASX",
        source_label="View original ASX filing",
        url="https://example.test/asx/bhp",
        about="The filing covers BHP's quarterly production.",
        changed="Copper output rose.",
        matters="Output supports revenue.",
    )


@pytest.mark.parametrize(
    ("category", "artifact_type", "tag"),
    [
        ("USER_DISCUSSION", "reddit_post", "User Discussion"),
        ("HalfYearResults", "half_year_results", "Half Year Results"),
        ("UNKNOWN", "asx_announcement_other", "Asx Announcement Other"),
        (None, "news_article", "News Article"),
    ],
)
def test_the_tag_keeps_all_caps_words_whole(
    category: str | None,
    artifact_type: str,
    tag: str,
) -> None:
    artifact = _artifact(
        source_type="news",
        artifact_type=artifact_type,
        title="Story",
        artifact_metadata={"category": category},
    )

    assert artifact_card.artifact_card(artifact).tag == tag


@pytest.mark.parametrize(
    ("source_type", "metadata", "platform", "source_name", "source_label"),
    [
        (
            "asx_announcement",
            {"source_name": "Example News"},
            None,
            "ASX",
            "View original ASX filing",
        ),
        ("reddit", {}, None, "Reddit", "View original Reddit post"),
        ("reddit", {}, "r/ASX_Bets", "r/ASX_Bets", "View original Reddit post"),
        (
            "news",
            {"source_name": "Example News", "provider": "marketaux"},
            "Marketaux",
            "Example News",
            "View original at Example News",
        ),
        ("news", {"provider": "marketaux"}, None, "marketaux", "View original at marketaux"),
        ("bluesky", {}, "Bluesky", "Bluesky", "View original at Bluesky"),
        ("news", {}, None, None, "View original source"),
    ],
)
def test_the_card_names_the_source_and_labels_the_link_to_it(
    source_type: str,
    metadata: dict,
    platform: str | None,
    source_name: str | None,
    source_label: str,
) -> None:
    artifact = _artifact(source_type=source_type, title="Story", artifact_metadata=metadata)
    if platform:
        artifact.platform = InformationPlatform(name=platform, platform_type="test")

    card = artifact_card.artifact_card(artifact)

    assert (card.source_name, card.source_label) == (source_name, source_label)


@pytest.mark.parametrize(
    ("url", "metadata", "expected"),
    [
        (
            "https://example.test/original",
            {"source_url": "https://example.test/page"},
            "https://example.test/original",
        ),
        (
            None,
            {
                "source_url": "https://example.test/page",
                "pdf_url": "https://example.test/file.pdf",
            },
            "https://example.test/file.pdf",
        ),
        ("", {"pdf_url": "https://example.test/file.pdf"}, "https://example.test/file.pdf"),
        (None, {}, None),
    ],
)
def test_the_link_prefers_a_legacy_document_over_the_source_page(
    url: str | None,
    metadata: dict,
    expected: str | None,
) -> None:
    artifact = _artifact(source_type="asx_announcement", url=url, artifact_metadata=metadata)

    assert artifact_card.artifact_card(artifact).url == expected


def test_an_unsummarised_artifact_has_no_lines_and_never_shows_its_raw_text() -> None:
    artifact = _artifact(
        source_type="asx_announcement",
        title="General update",
        raw_text=" ".join(["Long raw text"] * 40),
        artifact_metadata={"category": "UNKNOWN"},
    )

    card = artifact_card.artifact_card(artifact)

    assert (card.about, card.changed, card.matters) == (None, None, None)
    assert "Long raw text" not in str(card.fields())


def test_about_falls_back_to_the_summary_line() -> None:
    artifact = _artifact(
        source_type="asx_announcement",
        title="Trading update",
        artifact_metadata={
            "summary": "The company released a concise generated summary.",
            "changed": "No material change identified.",
        },
    )

    card = artifact_card.artifact_card(artifact)

    assert card.about == "The company released a concise generated summary."
    assert card.changed == "No material change identified."
    assert card.matters is None


def test_a_legacy_joined_summary_fills_the_card() -> None:
    artifact = _artifact(
        source_type="asx_announcement",
        title="Community grants update",
        raw_text="Raw PDF header text",
        artifact_metadata={"category": "UNKNOWN"},
    )
    artifact.summaries.append(
        ArtifactSummary(
            summary_text=(
                "Woodside awarded community grants.\n\n"
                "The filing covers local community funding.\n\n"
                "A new grant round was announced.\n\n"
                "The investment may support Woodside's social licence."
            ),
            model_used="bedrock:openai.gpt-oss-120b-1:0",
        )
    )

    card = artifact_card.artifact_card(artifact)

    assert card.about == "The filing covers local community funding."
    assert card.changed == "A new grant round was announced."
    assert card.matters == "The investment may support Woodside's social licence."


def test_an_untitled_artifact_is_named_after_its_source_type() -> None:
    assert artifact_card.artifact_card(_artifact(title="  ")).title == "Untitled Market Update"
    assert artifact_card.artifact_card(_artifact(source_type="news")).title == "Untitled News"


def test_sources_give_the_original_with_a_short_evidence_preview() -> None:
    artifact = _artifact(
        source_type="news",
        title="BHP story",
        url="https://publisher.example/story",
        raw_text="word " * 100,
        published_at=datetime(2040, 1, 2, tzinfo=timezone.utc),
    )

    [source] = artifact_card.sources(artifact)

    assert source == {
        "label": "News",
        "title": "BHP story",
        "url": "https://publisher.example/story",
        "published_at": "2040-01-02T00:00:00+00:00",
        "evidence_text": f"{('word ' * 36).strip()}...",
    }
    assert artifact_card.sources(_artifact(source_type="news", url=" ")) == []
