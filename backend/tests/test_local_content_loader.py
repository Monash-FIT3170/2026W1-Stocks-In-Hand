from datetime import datetime, timedelta, timezone

from scripts.populate_local_content import bounded_announcements
from scrapers.base import Announcement


def _announcement(title: str, age_days: int) -> Announcement:
    return Announcement(
        ticker="CSL",
        title=title,
        date=datetime.now(timezone.utc) - timedelta(days=age_days),
        pdf_url=f"https://example.test/{title}.pdf",
        source_url="https://example.test/asx",
    )


def test_bounded_announcements_keeps_only_recent_documents_within_limit() -> None:
    selected = bounded_announcements(
        [_announcement("older", 20), _announcement("newest", 1), _announcement("old", 90)],
        lookback_days=30,
        max_documents=1,
    )

    assert [announcement.title for announcement in selected] == ["newest"]
