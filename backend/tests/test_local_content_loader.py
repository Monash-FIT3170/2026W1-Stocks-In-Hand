import asyncio
from datetime import datetime, timedelta, timezone

from lambdas.download_validation import validated_document
from scripts import populate_local_content
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


def test_collect_asx_saves_each_document_before_processing_it(
    monkeypatch,
    tmp_path,
) -> None:
    announcement = _announcement("Half Year Results", 1)
    fetched: list[dict] = []
    processed: list[bytes] = []

    class Scraper:
        async def fetch_announcements(self):
            return [announcement]

    async def fetch_document(**request):
        fetched.append(request)
        return validated_document(
            b"%PDF-1.7\nresults",
            declared_content_type="application/pdf",
            final_url=request["document_url"],
            max_bytes=request["max_bytes"],
        )

    monkeypatch.setattr(populate_local_content, "get_scraper", lambda _ticker: Scraper())
    monkeypatch.setattr(populate_local_content, "fetch_document", fetch_document)
    monkeypatch.setattr(
        populate_local_content,
        "process_announcement",
        lambda item: processed.append(item.local_path.read_bytes()),
    )

    result = asyncio.run(
        populate_local_content.collect_asx(
            ["CSL"],
            lookback_days=30,
            max_documents=3,
            output_dir=tmp_path,
        )
    )

    assert result == {"found": 1, "processed": 1, "errors": []}
    assert fetched[0]["source_adapter"] == "csl"
    assert fetched[0]["document_url"] == announcement.pdf_url
    assert processed == [b"%PDF-1.7\nresults"]
    assert announcement.local_path.parent == tmp_path / "CSL"
